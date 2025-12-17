import json
import redis
import warnings
import requests
from celery.utils.log import get_task_logger
from .celery_app import celery_app
from celery.exceptions import SoftTimeLimitExceeded
from .api_registrar import RegistrarAPI
from .api_scraper import ScraperAPI

# Suppress warnings for requests
warnings.filterwarnings('ignore', message='Unverified HTTPS request')

# Connect to Redis
redis_client = redis.StrictRedis(host='localhost', port=6379, db=0, decode_responses=True)

# Initialize standard Celery logger
logger = get_task_logger(__name__)

def notify_user(chat_id, text):
    """
    Delegates notification to the Web API.
    """
    url = "http://127.0.0.1:8000/notifications/send"
    payload = {"chat_id": chat_id, "text": text}
    
    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
    except Exception as e:
        logger.error(f"⚠️ Failed to request notification via Web API: {e}")


@celery_app.task(name='tasks.pre_login', time_limit=15)
def pre_login(job_id, username, password, mode):
    """
    Pre-authenticates the user.
    Saves Cookies and Student ID to Redis.
    INTENTIONALLY IGNORES missing CSRF token (assumes site is locked).
    """
    logger.info(f"🚀 [pre_login:{job_id}] Starting pre-authentication for: {username}")

    try:
        api = RegistrarAPI(mode=mode)
        
        # We expect login to succeed (return cookies) but token might be None
        cookies, csrf_token = api.login(username, password)

        if cookies:
            # Fetch Student ID (should work if cookies are valid)
            student_id = api.get_student_id()
            if not student_id:
                logger.error(f"❌ [pre_login:{job_id}] Login succeeded but could not fetch student ID.")
                return 

            # Save the session (Cookies + ID)
            # We don't care about the token here, run_registration will fetch a fresh one.
            session_data = {
                "cookies": cookies,
                "student_id": student_id,
                "csrf_token": csrf_token # Saved just in case, but likely None or ignored
            }
            
            redis_key = f"session:{job_id}" 
            redis_client.set(redis_key, json.dumps(session_data), ex=300) # Keep for 5 mins
            
            logger.info(f"✅ [pre_login:{job_id}] Session saved (Token present: {bool(csrf_token)}). Ready for registration.")
            return 
        else:
            logger.warning(f"❌ [pre_login:{job_id}] Failed to log in.")
            return
    except Exception as e:
        logger.error(f"❌ [pre_login:{job_id}] Exception: {e}", exc_info=True)
        return


@celery_app.task(name='tasks.run_registration', time_limit=25)
def run_registration(job_id, chat_id, username, password, courses_to_register, mode):
    """
    Executes the registration.
    STRATEGY:
    1. Load Session (Cookies + ID).
    2. FORCE FETCH FRESH CSRF TOKEN (Assume none exists).
    3. Register.
    """
    logger.info(f"🎯 [run_registration:{job_id}] Waking up for registration!")
 
    user_key = f"user:{chat_id}"
    api = None
    student_id = None
    csrf_token = None
    
    # --- PHASE 1: RESTORE SESSION ---
    try:
        redis_key = f"session:{job_id}"
        session_json = redis_client.get(redis_key)
        
        if session_json:
            session_data = json.loads(session_json)
            saved_cookies = session_data.get('cookies')
            student_id = session_data.get('student_id')
            
            if saved_cookies and student_id:
                api = RegistrarAPI(session_cookies=saved_cookies, mode=mode)
                logger.info(f"✅ [run_registration:{job_id}] Restored session for Student {student_id}.")
            else:
                logger.warning(f"⚠️ [run_registration:{job_id}] Incomplete session data in Redis.")
        else:
            logger.warning(f"⚠️ [run_registration:{job_id}] No cached session found.")

    except Exception as e:
        logger.error(f"❌ [run_registration:{job_id}] Redis error: {e}")

    # --- PHASE 2: EMERGENCY FALLBACK (If Pre-Login Failed) ---
    if not api:
        logger.info(f"🔄 [run_registration:{job_id}] Performing emergency manual login...")
        api = RegistrarAPI(mode=mode)
        cookies, _ = api.login(username, password) # We ignore the token from login, we'll fetch fresh anyway
        if not cookies:
             return fail_job(job_id, chat_id, "Login failed during registration task.")
        student_id = api.get_student_id()

    # --- PHASE 3: FETCH FRESH CSRF TOKEN (CRITICAL) ---
    # We assume the token in Redis (if any) is stale or non-existent.
    # We fetch it NOW, from the live page.
    try:
        logger.info(f"🔎 [run_registration:{job_id}] Fetching FRESH CSRF token from live site...")
        csrf_token = api.fetch_csrf_token()
        
        if not csrf_token:
            return fail_job(job_id, chat_id, "Registration page is still locked (No CSRF token found).")
            
    except Exception as e:
        return fail_job(job_id, chat_id, f"Error fetching CSRF token: {e}")

    if not student_id:
        return fail_job(job_id, chat_id, "Missing Student ID.")

    # --- PHASE 4: EXECUTE REGISTRATION ---
    logger.info(f"🚀 [run_registration:{job_id}] Token obtained. Registering {len(courses_to_register)} courses...")
    
    succeeded_courses = []
    failed_courses = []

    for course in courses_to_register:
        # Prepare display name
        comps_str = ", ".join([f"{c.get('type','?')} {c['section_id']}" for c in course.get('components', [])])
        course_display = f"{course['name']} ({comps_str})"

        is_success, reason = api.register_course(course, student_id, csrf_token)
        
        if is_success:
            succeeded_courses.append(course_display)
        else:
            failed_courses.append({"name": course_display, "reason": reason})

    # --- PHASE 5: REPORTING & CLEANUP ---
    send_report(chat_id, mode, succeeded_courses, failed_courses)
    
    execution_status = "completed" if (succeeded_courses or failed_courses) else "failed"
    update_job_status(chat_id, job_id, execution_status)
    
    # Cleanup schedule keys
    redis_client.hdel(user_key, "trigger_timestamp", "pre_login_timestamp", "target_time_str")

    return {
        "succeeded": succeeded_courses,
        "failed": failed_courses,
        "mode": mode
    }


@celery_app.task(name='tasks.update_course_ids', soft_time_limit=50, time_limit=60)
def update_course_ids(credentials, desired_schedule, course_names):
    """
    Celery task to scrape and validate course IDs using Playwright.
    """
    username = credentials.get('username')
    logger.info(f"🛠️ [update_ids] Starting course ID scraping for user: {username}")
    
    scraper = ScraperAPI(headless=True, mode='test')
    
    try:
        final_course_list = []

        if not scraper.login(credentials):
            logger.error(f"❌ [update_ids] Login failed for {username}")
            return {"valid_courses": [], "errors": ["Login failed during scraping."]}
            
        scraper.add_courses_to_schedule(course_names)
        scraped_course_map = scraper.scrape_all_course_ids(desired_schedule)

        if not scraped_course_map:
            logger.error(f"❌ [update_ids] No data was scraped for {username}.")
            return {"valid_courses": [], "errors": ["No data scraped from schedule table."]}

        final_course_list = scraper.validate_and_build_course_list(desired_schedule, scraped_course_map)
        return final_course_list

    except SoftTimeLimitExceeded:
        logger.error(f"❌ [update_ids] SOFT TIME LIMIT EXCEEDED for user {username}. Aborting task.")
        return None
    except Exception as e:
        logger.error(f"❌ [update_ids] An exception occurred during scraping for {username}: {e}", exc_info=True)
        return None
    finally:
        scraper.close()


# --- Helper Functions ---

def fail_job(job_id, chat_id, reason):
    logger.error(f"❌ [run_registration:{job_id}] FAILED: {reason}")
    notify_user(chat_id, f"❌ **Registration Failed**\nReason: {reason}")
    update_job_status(chat_id, job_id, "failed")
    return {"status": "error", "message": reason}


def send_report(chat_id, mode, succeeded, failed):
    report_text = f"🏁 **Registration Report**\nMode: {mode.upper()}\n\n"
    if succeeded:
        report_text += "✅ **Successfully Registered:**\n" + "\n".join([f"- {c}" for c in succeeded]) + "\n\n"
    if failed:
        report_text += "❌ **Failed:**\n"
        for fail in failed:
            report_text += f"- {fail['name']}: {fail['reason']}\n"
    
    if not succeeded and not failed:
        report_text += "⚠️ No courses were processed."
    
    notify_user(chat_id, report_text)


def update_job_status(chat_id, job_id, status):
    try:
        job_index_key = f"job_index:{chat_id}"
        job_data_json = redis_client.hget(job_index_key, job_id)
        if job_data_json:
            job_entry = json.loads(job_data_json)
            job_entry['status'] = status
            redis_client.hset(job_index_key, job_id, json.dumps(job_entry))
            logger.info(f"📝 Job {job_id} status updated to: {status}")
    except Exception as e:
        logger.error(f"⚠️ Failed to update Redis status: {e}")
