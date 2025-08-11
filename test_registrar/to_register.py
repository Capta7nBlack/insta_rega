import warnings
from api_registrar import RegistrarAPI         # UPDATED
from api_local_storage import LocalStorageAPI # UPDATED

# Suppress InsecureRequestWarning for verify=False
warnings.filterwarnings('ignore', message='Unverified HTTPS request')

def main():
    """
    Orchestrates the process of validating the session and registering courses.
    """
    # 1. Handle local data
    storage = LocalStorageAPI()
    config = storage.get_config()
    session_data = storage.get_session_data()

    # 2. Prepare API client and validate session data
    api = RegistrarAPI(session_cookies=session_data.get('cookies'))
    if not api.is_session_valid():
        print("\nYour session data is invalid, please refresh it by running to_login.py")
        return

    
    # 3. Register courses
    user_id = config.get('user_info', {}).get('user_id')
    courses = config.get('courses_to_register', [])
    csrf_token = session_data.get('csrf_token')

    if not all([user_id, courses, csrf_token]):
        print("❌ Configuration or session data is incomplete. Cannot proceed.")
        return

    print("\n--- Initiating Final Registration ---")
    for course in courses:
        api.register_course(course, user_id, csrf_token)
        print("-" * 20)

if __name__ == "__main__":
    main()
