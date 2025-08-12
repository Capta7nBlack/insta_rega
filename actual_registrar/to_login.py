import warnings
from api_registrar import RegistrarAPI
from api_local_storage import LocalStorageAPI

# Suppress InsecureRequestWarning for verify=False
warnings.filterwarnings('ignore', message='Unverified HTTPS request')

def main():
    """
    Orchestrates the process of logging in and saving the session.
    """
    storage = LocalStorageAPI()
    config = storage.get_config()
    credentials = config.get('credentials', {})

    api = RegistrarAPI()
    cookies, csrf_token = api.login(credentials.get('username'), credentials.get('password'))

    if cookies and csrf_token:
        storage.save_session_data(cookies, csrf_token)
    else:
        print("\n❌ Authentication failed. Session data not saved.")

if __name__ == "__main__":
    main()
