from registrar_api import RegistrarAPI
from local_storage_api import LocalStorageAPI
import warnings

# Suppress InsecureRequestWarning for verify=False
warnings.filterwarnings('ignore', message='Unverified HTTPS request')

def main():
    """
    Orchestrates the process of validating the session and registering courses.
    """
    # 1. Handle local data
    storage = LocalStorageAPI()
    config = storage.get_config()
    session_data = storage.get_validated_session_data()

    # 2. Prepare API client with loaded session
    api = RegistrarAPI(session_cookies=session_data.get('cookies'))
    
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
