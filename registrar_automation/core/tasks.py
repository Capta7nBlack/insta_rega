# core/tasks.py

import json
import redis
import warnings
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

@celery_app.task(name='tasks.pre_login', time_limit=8)
def pre_login(job_id, username, password, mode):
    """
    Logs in, fetches the student ID, and saves a temporary session.
    Returns the student_id on success, None on failure.
    """
    logger.info(f"🚀 [pre_login:{job_id}] Starting credential validation for user: {username} on mode {mode}")

    try:
        api = RegistrarAPI(mode=mode)
        cookies, csrf_token = api.login(username, password)

        if cookies and csrf_token:
            # After successful login, fetch the student ID
            student_id = api.get_student_id()
            if not student_id:
                logger.error(f"❌ [pre_login:{job_id}] Login succeeded but could not fetch student ID.")
                return None 

            # Save the temporary session using job_id so run_registration can find it
            session_data = {
                "cookies": cookies,
                "csrf_token": csrf_token,
                "student_id": student_id
            }
            redis_key = f"session:{job_id}" 
            redis_client.set(redis_key, json.dumps(session_data), ex=15)
            logger.info(f"✅ [pre_login:{job_id}] Successfully validated and fetched ID {student_id}")
            return 
        else:
            logger.warning(f"❌ [pre_login:{job_id}] Failed to log in for user: {username}")
            return None
    except Exception as e:
        logger.error(f"❌ [pre_login:{job_id}] An exception occurred: {e}", exc_info=True)
        return None

@celery_app.task(name='tasks.run_registration', time_limit=15)
def run_registration(job_id, chat_id, username, password, courses_to_register, mode):
    """
    Celery task to perform course registration.
    """
    logger.info(f"🎯 [run_registration:{job_id}] Starting registration for mode: {mode}")
 
    user_key = f"user:{chat_id}"
    session_data = None
    student_id = None
    
    # 1. Try to retrieve the session created by pre_login
    try:
        # Use job_id to find the session, not student_id (which we don't have yet)
        redis_key = f"session:{job_id}"
        session_json = redis_client.get(redis_key)
        
        if session_json:
            session_data = json.loads(session_json)
            student_id = session_data.get('student_id')
            logger.info(f"✅ [run_registration:{job_id}] Found fresh session in Redis for {student_id}.")
        else:
            logger.warning(f"⚠️ [run_registration:{job_id}] No fresh session found. Proceeding with manual login.")
    except Exception as e:
        logger.error(f"❌ [run_registration:{job_id}] Error fetching session from Redis: {e}. Proceeding with manual login.")

    # 2. Login or Initialize API
    try:
        succeeded_courses = []
        failed_courses = []
        api = None
        csrf_token = None

        if session_data:
            api = RegistrarAPI(session_cookies=session_data.get('cookies'), mode=mode)
            csrf_token = session_data.get('csrf_token')
        else:
            # Fallback: Login manually if session is missing
            api = RegistrarAPI(mode=mode)
            cookies, csrf_token = api.login(username, password)
            if not (cookies and csrf_token):
                logger.error(f"❌ [run_registration:{job_id}] Fallback login failed. Aborting.")
                return {"status": "login_failed", "message": "Could not log in to the registrar."}
            
            student_id = api.get_student_id()

        if not all([student_id, courses_to_register, csrf_token]):
            logger.error(f"❌ [run_registration:{job_id}] Incomplete data. StudentID: {bool(student_id)}, Courses: {bool(courses_to_register)}, Token: {bool(csrf_token)}")
            return {"status": "error", "message": "Incomplete data provided to the registration task."}

        logger.info(f"📤 [run_registration:{job_id}] Initiating course registration for student {student_id}...")

        # 3. Register Courses
        for course in courses_to_register:
            is_success, reason = api.register_course(course, student_id, csrf_token) # Removed mode arg if not supported by register_course
            if is_success:
                succeeded_courses.append(course['name'])
            else:
                failed_courses.append({"name": course['name'], "reason": reason})

        result = {
            "total_attempted": len(courses_to_register),
            "total_succeeded": len(succeeded_courses),
            "succeeded_courses": succeeded_courses,
            "failed_courses": failed_courses,
            "mode": mode
        }
        
        logger.info(f"✅ [run_registration:{job_id}] Completed for {student_id}. Result: {result}")
        return result

    except Exception as e:
        logger.error(f"❌ [run_registration:{job_id}] An exception occurred: {e}", exc_info=True)
        return {"status": "exception", "message": str(e)}
    finally:
        logger.info(f"🧹 [run_registration:{job_id}] Cleaning up schedule data for chat_id: {chat_id}")
        redis_client.hdel(user_key, "trigger_timestamp", "pre_login_timestamp", "target_time_str")

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
            return None

        scraper.add_courses_to_schedule(course_names)
        scraped_course_map = scraper.scrape_all_course_ids(desired_schedule)

        if not scraped_course_map:
            logger.error(f"❌ [update_ids] No data was scraped for {username}.")
            return None

        final_course_list = scraper.validate_and_build_course_list(desired_schedule, scraped_course_map)

        if final_course_list:
            logger.info(f"✅ [update_ids] Successfully scraped and validated courses for {username}")
            return final_course_list
        else:
            logger.warning(f"⚠️ [update_ids] No valid courses found after validation for {username}")
            return None

    except SoftTimeLimitExceeded:
        logger.error(f"❌ [update_ids] SOFT TIME LIMIT EXCEEDED for user {username}. Aborting task.")
        return None
    except Exception as e:
        logger.error(f"❌ [update_ids] An exception occurred during scraping for {username}: {e}", exc_info=True)
        return None
    finally:
        scraper.close()
