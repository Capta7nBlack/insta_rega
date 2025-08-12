import requests
from bs4 import BeautifulSoup
import time

class RegistrarAPI:
    """
    Handles all network communication with the registrar's website.
    """
    BASE_URL = "https://registrar.nu.edu.kz"
    LOGIN_URL = f"{BASE_URL}/user/login"
    REG_PAGE_URL = f"{BASE_URL}/my-registrar/course-registration"
    API_URL = f"{REG_PAGE_URL}/json"

    def __init__(self, session_cookies=None):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
        })
        if session_cookies:
            self.session.cookies.update(session_cookies)

    # --- Public Methods ---

    def login(self, username, password):
        """
        Public method to perform the full login sequence.
        Returns a tuple of (session_cookies, csrf_token) on success.
        """
        print("--- Starting Login Process ---")
        form_build_id = self.__get_login_form_build_id()
        if not form_build_id:
            return None, None

        print("Submitting credentials...")
        login_payload = {
            "name": username, "pass": password, "form_build_id": form_build_id,
            "form_id": "user_login", "op": "Log in"
        }
        
        try:
            login_req = self.session.post(self.LOGIN_URL, data=login_payload, verify=False)
            login_req.raise_for_status()
            if "user/logout" not in login_req.text:
                print("❌ Login failed. Please double-check your credentials.")
                return None, None
            print("✅ Login successful.")
            
            # After successful login, get the CSRF token for registration
            csrf_token = self.__get_csrf_token_from_page()
            if not csrf_token:
                return None, None
                
            return self.session.cookies.get_dict(), csrf_token
            
        except requests.exceptions.RequestException as e:
            print(f"❌ An error occurred during login request: {e}")
            return None, None

    def register_course(self, course_data, user_id, csrf_token):
        """
        Public method to register a single course.
        """
        self.session.headers.update({
            "x-csrf-token": csrf_token,
            "Referer": f"{self.REG_PAGE_URL}/selected",
        })

        component_parts = [
            f"instance_{course_data['instance_id']}_component_{comp['component_id']}_section_{comp['section_id']}"
            for comp in course_data['components']
        ]
        sections_string = "-".join(component_parts)
        
        register_params = {
            "_dc": int(time.time() * 1000),
            "method": "registerSections",
            "sections": sections_string,
            "userid": user_id
        }
        
        print(f"📤 Registering '{course_data['name']}'...")
        print(f"   Submitting sections: {sections_string}")
        
        try:
            r = self.session.get(self.API_URL, params=register_params, verify=False)
            print(f"   ✅Response: {r.status_code} {r.text.strip()}")
            # Further response processing can be added here (success/fail messages)
        except requests.exceptions.RequestException as e:
            print(f"   ❌ An error occurred while registering '{course_data['name']}': {e}")

    def is_session_valid(self):
        """
        Checks if the current session cookies are still valid by making a
        request to a page that requires authentication.
        """
        print("--- Validating session with the server ---")
        try:
            # Access a page that is only available when logged in.
            response = self.session.get(self.REG_PAGE_URL, verify=False, allow_redirects=True)
            response.raise_for_status()
            
            # A valid session should show a "Log out" link. An invalid one might redirect
            # to the login page, which does not have this link.
            if "user/logout" in response.text:
                print("✅ Session is valid.")
                return True
            else:
                print("❌ Session is invalid or expired.")
                return False
        except requests.exceptions.RequestException as e:
            print(f"❌ An error occurred during session validation: {e}")
            return False

    # --- Private Methods ---

    def __get_login_form_build_id(self):
        """Private method to scrape the form_build_id from the login page."""
        print("Fetching login page for form_build_id...")
        try:
            req = self.session.get(self.LOGIN_URL, verify=False)
            req.raise_for_status()
            soup = BeautifulSoup(req.text, 'html.parser')
            tag = soup.find('input', {'name': 'form_build_id'})
            if not tag:
                print("❌ Could not find form_build_id on the login page.")
                return None
            form_id = tag['value']
            print(f"✅ Found form_build_id: {form_id[:15]}...")
            return form_id
        except (requests.exceptions.RequestException, AttributeError) as e:
            print(f"❌ Failed to get form_build_id: {e}")
            return None
            
    def __get_csrf_token_from_page(self):
        """Private method to scrape the CSRF token from the main registration page."""
        print("\n--- Fetching CSRF Token for Registration ---")
        try:
            req = self.session.get(self.REG_PAGE_URL, verify=False)
            req.raise_for_status()
            soup = BeautifulSoup(req.text, 'html.parser')
            tag = soup.find('meta', {'name': 'csrf-token'})
            if not tag:
                print("❌ Could not find the 'csrf-token' meta tag.")
                return None
            token = tag['content']
            print(f"✅ Found CSRF Token: {token[:10]}...")
            return token
        except (requests.exceptions.RequestException, AttributeError) as e:
            print(f"❌ Failed to get or parse the CSRF token: {e}")
            return None
