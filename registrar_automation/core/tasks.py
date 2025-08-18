# core/tasks.py

import json
import redis
import warnings
from .celery_app import celery_app
from celery.exceptions import SoftTimeLimitExceeded # Import the exception
from .api_registrar import RegistrarAPI
from .api_scraper import ScraperAPI

# Suppress warnings for requests
warnings.filterwarnings('ignore', message='Unverified HTTPS request')

# Connect to Redis
redis_client = redis.StrictRedis(host='localhost', port=6379, db=0, decode_responses=True)

@celery_app.task(name='tasks.pre_login', time_limit=7)
def pre_login(username, password, user_id):
    """
    Celery task to log in ahead of time and store the session in Redis.
    It has a hard time limit of 8 seconds to prevent collisions.
    """
    print(f"🚀 [pre_login] Starting pre-login for user_id: {user_id}")
    try:
        api = RegistrarAPI()
        cookies, csrf_token = api.login(username, password)

        if cookies and csrf_token:
            session_data = {"cookies": cookies, "csrf_token": csrf_token}
            redis_key = f"session:{user_id}"
            redis_client.set(redis_key, json.dumps(session_data), ex=15)
            print(f"✅ [pre_login] Successfully saved fresh session to Redis for user_id: {user_id}")
            return True
        else:
            print(f"❌ [pre_login] Failed to log in for user_id: {user_id}")
            return False
    except Exception as e:
        print(f"❌ [pre_login] An exception occurred for user_id {user_id}: {e}")
        return False


@celery_app.task(name='tasks.run_registration', time_limit=12)
def run_registration(username, password, user_id, courses_to_register):
    """
    Celery task to perform course registration.
    It has a hard time limit of 15 seconds.
    """
    print(f"🎯 [run_registration] Starting registration for user_id: {user_id}")
    
    session_data = None
    
    try:
        redis_key = f"session:{user_id}"
        session_json = redis_client.get(redis_key)
        if session_json:
            session_data = json.loads(session_json)
            print(f"✅ [run_registration] Found fresh session in Redis for {user_id}.")
        else:
            print(f"⚠️ [run_registration] No fresh session in Redis for {user_id}. Proceeding with manual login.")
    except Exception as e:
        print(f"❌ [run_registration] Error fetching session from Redis for {user_id}: {e}. Proceeding with manual login.")

    try:
        succeeded_courses = []
        failed_courses = []

        if session_data:
            api = RegistrarAPI(session_cookies=session_data.get('cookies'))
            csrf_token = session_data.get('csrf_token')
        else:
            api = RegistrarAPI()
            cookies, csrf_token = api.login(username, password)
            if not (cookies and csrf_token):
                print(f"❌ [run_registration] Fallback login failed for {user_id}. Aborting.")
                return {"status": "login_failed", "message": "Could not log in to the registrar."}

        if not all([user_id, courses_to_register, csrf_token]):
            print(f"❌ [run_registration] Incomplete data for {user_id}. Cannot register.")
            return {"status": "error", "message": "Incomplete data provided to the registration task."}

        print(f"📤 [run_registration] Initiating course registration for {user_id}...")
        
        for course in courses_to_register:
            is_success = api.register_course(course, user_id, csrf_token)
            if is_success:
                succeeded_courses.append(course['name'])
            else:
                failed_courses.append(course['name'])
        
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
        print(f"❌ [run_registration] An exception occurred for user_id {user_id}: {e}")
        return {"status": "exception", "message": str(e)}


@celery_app.task(name='tasks.update_course_ids', soft_time_limit=25, time_limit=30)
def update_course_ids(credentials, desired_schedule, course_names):
    """
    Celery task to scrape and validate course IDs using Playwright.
    It has a soft time limit to gracefully fail before the hard limit.
    """
    username = credentials.get('username')
    print(f"🛠️ [update_ids] Starting course ID scraping for user: {username}")
    
    scraper = ScraperAPI(headless=True)
    
    try:
        final_course_list = []

        if not scraper.login(credentials):
            print(f"❌ [update_ids] Login failed for {username}")
            return None

        scraper.add_courses_to_schedule(course_names)
        scraped_course_map = scraper.scrape_all_course_ids(desired_schedule)

        if not scraped_course_map:
            print(f"❌ [update_ids] No data was scraped for {username}.")
            return None

        final_course_list = scraper.validate_and_build_course_list(desired_schedule, scraped_course_map)

        if final_course_list:
            print(f"✅ [update_ids] Successfully scraped and validated courses for {username}")
            return final_course_list
        else:
            print(f"⚠️ [update_ids] No valid courses found after validation for {username}")
            return None

    except SoftTimeLimitExceeded:
        print(f"❌ [update_ids] SOFT TIME LIMIT EXCEEDED for user {username}. Aborting task.")
        # Returning None will be interpreted as a failure by the web server's polling endpoint.
        return None
    except Exception as e:
        print(f"❌ [update_ids] An exception occurred during scraping for {username}: {e}")
        return None
    finally:
        # This block will run even if the time limit is exceeded, ensuring the browser closes.
        scraper.close()
