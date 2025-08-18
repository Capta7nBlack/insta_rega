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
def pre_login(username, password):
    """
    Logs in, fetches the student ID, and saves a temporary session.
    Returns the student_id on success, None on failure.
    """
    print(f"🚀 [pre_login] Starting credential validation for user: {username}")
    try:
        api = RegistrarAPI()
        cookies, csrf_token = api.login(username, password)

        if cookies and csrf_token:
            # After successful login, fetch the student ID
            student_id = api.get_student_id()
            if not student_id:
                print(f"❌ [pre_login] Login succeeded but could not fetch student ID.")
                return None # Return None if ID fetch fails

            # Save the temporary session for the real registration
            session_data = {"cookies": cookies, "csrf_token": csrf_token}
            redis_key = f"session:{student_id}" # Use student_id in the key
            redis_client.set(redis_key, json.dumps(session_data), ex=15)
            print(f"✅ [pre_login] Successfully validated and fetched ID for user: {student_id}")
            return student_id # Return the student_id on success
        else:
            print(f"❌ [pre_login] Failed to log in for user: {username}")
            return None
    except Exception as e:
        print(f"❌ [pre_login] An exception occurred for user {username}: {e}")
        return None

@celery_app.task(name='tasks.run_registration', time_limit=12)
def run_registration(username, password, student_id, courses_to_register):
    """
    Celery task to perform course registration.
    The parameter 'user_id' has been renamed to 'student_id' for clarity.
    """
    print(f"🎯 [run_registration] Starting registration for student_id: {student_id}")
    
    session_data = None
    
    try:
        # The session key is now consistently based on student_id
        redis_key = f"session:{student_id}"
        session_json = redis_client.get(redis_key)
        if session_json:
            session_data = json.loads(session_json)
            print(f"✅ [run_registration] Found fresh session in Redis for {student_id}.")
        else:
            print(f"⚠️ [run_registration] No fresh session in Redis for {student_id}. Proceeding with manual login.")
    except Exception as e:
        print(f"❌ [run_registration] Error fetching session from Redis for {student_id}: {e}. Proceeding with manual login.")

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
                print(f"❌ [run_registration] Fallback login failed for {student_id}. Aborting.")
                return {"status": "login_failed", "message": "Could not log in to the registrar."}

        if not all([student_id, courses_to_register, csrf_token]):
            print(f"❌ [run_registration] Incomplete data for {student_id}. Cannot register.")
            return {"status": "error", "message": "Incomplete data provided to the registration task."}

        print(f"📤 [run_registration] Initiating course registration for {student_id}...")
        
        for course in courses_to_register:
            # Pass the student_id to the API method
            is_success = api.register_course(course, student_id, csrf_token)
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
        
        print(f"✅ [run_registration] Completed for {student_id}. Result: {result}")
        return result

    except Exception as e:
        print(f"❌ [run_registration] An exception occurred for student_id {student_id}: {e}")
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
