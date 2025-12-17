import requests
from bs4 import BeautifulSoup
import time
import json

class RegistrarAPI:
    """
    Handles all network communication with the registrar's website.
    """

    def __init__(self, session_cookies=None, mode='test'):

        # Determine URL based on mode
        if mode == 'real':
            self.BASE_URL = "https://registrar.nu.edu.kz"
        else:
            self.BASE_URL = "https://testregistrar.nu.edu.kz"
            
        self.LOGIN_URL = f"{self.BASE_URL}/user/login"
        self.REG_PAGE_URL = f"{self.BASE_URL}/my-registrar/course-registration"
        self.API_URL = f"{self.REG_PAGE_URL}/json"
        self.GRADES_PAGE_URL = f"{self.BASE_URL}/my-registrar/check-grades"
        self.MAIN_PAGE_URL = f"{self.BASE_URL}/my-registrar"


        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
        })
        if session_cookies:
            self.session.cookies.update(session_cookies)

    # --- Public Methods ---
    def validate_login(self, username, password):
        """
        NEW METHOD: Validates credentials by attempting to log in. 
        It returns True if login is successful (session established), 
        but DOES NOT attempt to fetch the CSRF token.
        This allows validation to pass even if registration is closed.
        """
        print(f"--- Validating Credentials Only (User: {username}) ---")
        form_build_id = self.__get_login_form_build_id()
        if not form_build_id:
            return False

        login_payload = {
            "name": username, "pass": password, "form_build_id": form_build_id,
            "form_id": "user_login", "op": "Log in"
        }
        
        try:
            login_req = self.session.post(self.LOGIN_URL, data=login_payload, verify=False)
            login_req.raise_for_status()
            
            # If the response contains a logout link, we are logged in.
            if "user/logout" in login_req.text:
                print("✅ Credentials valid (Login successful).")
                return True
            else:
                print("❌ Login failed (Invalid credentials).")
                return False
        except Exception as e:
            print(f"❌ Validation error: {e}")
            return False


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


    def fetch_csrf_token(self):
        """
        Public wrapper to explicitly fetch the CSRF token.
        Useful for run_registration task.
        """
        return self.__get_csrf_token_from_page()


    def get_student_id(self):
        """
        After a successful login, this method scrapes the student ID from the
        'Check Grades' page.
        """
        print("--- Fetching Student ID ---")
        try:
            req = self.session.get(self.GRADES_PAGE_URL, verify=False)
            req.raise_for_status()
            soup = BeautifulSoup(req.text, 'html.parser')
            
            # Find the script tag containing the Drupal settings
            script_tag = soup.find('script', string=lambda text: text and 'Drupal.settings' in text)
            if not script_tag:
                print("❌ Could not find the settings script tag on the grades page.")
                return None

            # Extract the JSON string from the script tag
            json_string = script_tag.string.split('jQuery.extend(Drupal.settings, ', 1)[1].rsplit(');', 1)[0]
            
            # Parse the JSON
            data = json.loads(json_string)
            student_id = data['checkGrades']['studentDetails']['midterm']['STUDENTID']
            
            if student_id:
                print(f"✅ Found Student ID: {student_id}")
                return student_id
            else:
                print("❌ Student ID not found in the page data.")
                return None
        except (requests.exceptions.RequestException, json.JSONDecodeError, KeyError, IndexError) as e:
            print(f"❌ Failed to get or parse student ID: {e}")
            return None


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

        course_name = course_data['name']
        
        print(f"📤 Registering '{course_data['name']}'...")
        print(f"   Submitting sections: {sections_string}")
        
        try:
            r = self.session.get(self.API_URL, params=register_params, verify=False)
            r.raise_for_status()
            
            # --- Parse the response ---
            response_data = r.json()
            message = response_data.get("message","")
            if response_data.get("success") is True or "Registration Successful" in message:
                print(f"   ✅ SUCCESS: Successfully registered '{course_name}'.")
                return True, course_name
            else:
                # Extract the error message if available
                error_message = response_data.get("message", "No reason provided.")
                print(f"   ❌ FAILED: Could not register '{course_name}'. Reason: {error_message}")
                return False, error_message   
        except requests.exceptions.RequestException as e:
            print(f"   ❌ An error occurred while registering '{course_name}': {e}")
            return False, str(e)


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
            req = self.session.get(self.MAIN_PAGE_URL, verify=False)
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
