# insta_regponse/core/tasks.py
# response
import json
import redis
import warnings
from .celery_app import celery_app
from .api_registrar import RegistrarAPI
from .api_scraper import ScraperAPI
from .api_local_storage import LocalStorageAPI # We'll use this temporarily for testing

# Suppress warnings for requests
warnings.filterwarnings('ignore', message='Unverified HTTPS request')

# Connect to Redis. This will be used to store the temporary session
# data from the pre_login task.
redis_client = redis.StrictRedis(host='localhost', port=6379, db=0, decode_responses=True)

@celery_app.task(name='tasks.pre_login')
def pre_login(username, password, user_id):
    """
    Celery task to log in ahead of time and store the session in Redis.
    This warms up the session to make the actual registration faster.
    """
    print(f"🚀 [pre_login] Starting pre-login for user_id: {user_id}")
    try:
        api = RegistrarAPI()
        cookies, csrf_token = api.login(username, password)

        if cookies and csrf_token:
            session_data = {
                "cookies": cookies,
                "csrf_token": csrf_token
            }
            # The key is unique to the user.
            # The 'ex=15' sets a 15-second expiration time. This is a short-lived session.
            redis_key = f"session:{user_id}"
            redis_client.set(redis_key, json.dumps(session_data), ex=15)
            print(f"✅ [pre_login] Successfully saved fresh session to Redis for user_id: {user_id}")
            return True
        else:
            print(f"❌ [pre_login] Failed to log in for user_id: {user_id}")
            return False
    except Exception as e:
        print(f"🔥 [pre_login] An exception occurred for user_id {user_id}: {e}")
        return False


@celery_app.task(name='tasks.run_registration')
def run_registration(username, password, user_id, courses_to_register):
    """
    Celery task to perform the actual course registration.
    It first tries to use the fresh session from Redis. If that fails,
    it performs a full login as a fallback.
    """
    print(f"🎯 [run_registration] Starting registration for user_id: {user_id}")
    session_data = None
    
    # --- Step 1: Try to get the fresh session from Redis ---
    try:
        redis_key = f"session:{user_id}"
        session_json = redis_client.get(redis_key)
        if session_json:
            session_data = json.loads(session_json)
            print(f"✅ [run_registration] Found fresh session in Redis for {user_id}.")
        else:
            print(f"⚠️ [run_registration] No fresh session in Redis for {user_id}. Proceeding with manual login.")
    except Exception as e:
        print(f"🔥 [run_registration] Error fetching session from Redis for {user_id}: {e}. Proceeding with manual login.")

    # --- Step 2: Load login data or perform login ---
    try:
        succeeded_courses = []
        failed_courses = []

        # If we have a fresh session, use it.
        if session_data:
            api = RegistrarAPI(session_cookies=session_data.get('cookies'))
            csrf_token = session_data.get('csrf_token')

        # Fallback: If no fresh session, perform a full login.
        else:
            api = RegistrarAPI()
            cookies, csrf_token = api.login(username, password)
            if not (cookies and csrf_token):
                print(f"❌ [run_registration] Fallback login failed for {user_id}. Aborting.")
                return False

        # --- Step 3: Register each course ---
        for course in courses_to_register:
            is_success = api.register_course(course, user_id, csrf_token)
            if is_success:
                succeeded_courses.append(course['name'])
            else:
                failed_courses.append(course['name'])
        
        # --- Step 4: Build the detailed result dictionary ---
        total_attempted = len(courses_to_register)
        total_succeeded = len(succeeded_courses)
        
        result = {
            "total_attempted": total_attempted,
            "total_succeeded": total_succeeded,
            "succeeded_courses": succeeded_courses,
            "failed_courses": failed_courses
        }
        
        print(f"✅ [run_registration] Completed for {user_id}. Result: {result}")
        return result

    except Exception as e:
        print(f"🔥 [run_registration] An exception occurred for user_id {user_id}: {e}")
        return {"status": "exception", "message": str(e)}


@celery_app.task(name='tasks.update_course_ids')
def update_course_ids(credentials, desired_schedule, course_names):
    """
    Celery task to scrape and validate course IDs using Playwright.
    Takes credentials and a desired schedule, returns the final list of
    course objects ready for registration. This is a long-running task.
    """
    username = credentials.get('username')
    print(f"🛠️ [update_ids] Starting course ID scraping for user: {username}")
    
    scraper = ScraperAPI(headless=True)
    scraped_course_map = {}
    final_course_list = []

    try:
        if not scraper.login(credentials):
            print(f"❌ [update_ids] Login failed for {username}")
            return None # Indicate failure

        scraper.add_courses_to_schedule(course_names)
        scraped_course_map = scraper.scrape_all_course_ids(desired_schedule)

    except Exception as e:
        print(f"🔥 [update_ids] An exception occurred during scraping for {username}: {e}")
        return None # Indicate failure
    finally:
        scraper.close() # Ensure the browser is always closed

    if not scraped_course_map:
        print(f"❌ [update_ids] No data was scraped for {username}.")
        return None

    # Perform the final validation
    final_course_list = scraper.validate_and_build_course_list(desired_schedule, scraped_course_map)

    if final_course_list:
        print(f"✅ [update_ids] Successfully scraped and validated courses for {username}")
        return final_course_list # On success, return the structured course data
    else:
        print(f"⚠️ [update_ids] No valid courses found after validation for {username}")
        return None
