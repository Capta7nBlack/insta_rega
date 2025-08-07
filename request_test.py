import requests
import json
import time
from bs4 import BeautifulSoup
import warnings

# Suppress InsecureRequestWarning for verify=False
warnings.filterwarnings('ignore', message='Unverified HTTPS request')

# --- 1. CONFIGURE YOUR COURSES HERE ---
# Updated course name to match your latest output
COURSES_TO_REGISTER = [
{
        "name": "CSCI 390 (Lec)",
        "instance_id": "28009",
        "components": [
            {"component_id": "34175", "section_id": "1"}
        ]
    },

    {
        "name": "CSCI 341 (Lec)",
        "instance_id": "28004",
        "components": [
            {"component_id": "34166", "section_id": "1"}
        ]
    },
    {
        "name": "CSCI 361 (Lec+Lab)",
        "instance_id": "28008",
        "components": [
            {"component_id": "34172", "section_id": "1"},
            {"component_id": "34173", "section_id": "4"}
        ]
    },
    {
        "name": "WCS 150 (Lec Only)",
        "instance_id": "27635",
        "components": [
            {"component_id": "33602", "section_id": "29"}
        ]
    },
    {
        "name": "KAZ 313",
        "instance_id": "27724",
        "components": [
            {"component_id": "33713", "section_id": "2"}
        ]
    }
]

# --- 2. YOUR LOGIN CREDENTIALS ---
USERNAME = "***REMOVED***"
PASSWORD = "***REMOVED***!"
USER_ID = "***REMOVED***"

# --- 3. API AND URL CONFIGURATION ---
LOGIN_URL = "https://testregistrar.nu.edu.kz/user/login"
REGISTRATION_PAGE_URL = "https://testregistrar.nu.edu.kz/my-registrar/course-registration"
API_URL = "https://testregistrar.nu.edu.kz/my-registrar/course-registration/json"

# --- 4. THE SCRIPT ---

def main():
    """Main function to run the registration bot."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
    })
    
    print("--- Starting Login Process ---")
    if not login(session): return

    print("\n--- Fetching CSRF Token ---")
    csrf_token = get_csrf_token(session)
    if not csrf_token: return

    print("\n--- Initiating Final Registration (One by One) ---")
    register_courses(session, csrf_token, COURSES_TO_REGISTER)

def login(session):
    """Handles the entire login process."""
    try:
        print("Fetching login page for form_build_id...")
        login_page_req = session.get(LOGIN_URL, verify=False)
        login_page_req.raise_for_status()
        soup_login = BeautifulSoup(login_page_req.text, 'html.parser')
        form_build_id_tag = soup_login.find('input', {'name': 'form_build_id'})
        form_build_id = form_build_id_tag['value']
        print(f"✅ Found form_build_id: {form_build_id[:15]}...")

        print("Submitting credentials...")
        login_payload = {
            "name": USERNAME, "pass": PASSWORD, "form_build_id": form_build_id,
            "form_id": "user_login", "op": "Log in"
        }
        login_req = session.post(LOGIN_URL, data=login_payload, verify=False)
        login_req.raise_for_status()
        if "user/logout" in login_req.text:
            print("✅ Login successful.")
            return True
        print("❌ Login failed. Please double-check your credentials.")
        return False
    except (requests.exceptions.RequestException, AttributeError) as e:
        print(f"❌ Login request failed: {e}")
        return False

def get_csrf_token(session):
    """Fetches the registration page to scrape the CSRF token."""
    try:
        page_req = session.get(REGISTRATION_PAGE_URL, verify=False)
        page_req.raise_for_status()
        soup = BeautifulSoup(page_req.text, 'html.parser')
        csrf_token_tag = soup.find('meta', {'name': 'csrf-token'})
        token = csrf_token_tag['content']
        print(f"✅ Found shared CSRF Token: {token[:10]}...")
        return token
    except (requests.exceptions.RequestException, AttributeError) as e:
        print(f"❌ Failed to get or parse the CSRF token: {e}")
        return None

def register_courses(session, csrf_token, courses):
    """
    <<< THE FIX: Loop and send a separate registration request for EACH course. >>>
    """
    session.headers.update({
        "x-csrf-token": csrf_token,
        "Referer": "https://testregistrar.nu.edu.kz/my-registrar/course-registration/selected",
    })
    session.headers.pop("headerval", None)

    for course in courses:
        # Build the sections string for this single course and its components
        component_parts = [
            f"instance_{course['instance_id']}_component_{comp['component_id']}_section_{comp['section_id']}"
            for comp in course['components']
        ]
        sections_string_for_this_course = "-".join(component_parts)

        register_params = {
            "_dc": int(time.time() * 1000),
            "method": "registerSections",
            "sections": sections_string_for_this_course,
            "userid": USER_ID
        }
        
        print(f"📤 Registering '{course['name']}'...")
        print(f"   Submitting sections: {sections_string_for_this_course}")
        
        try:
            r = session.get(API_URL, params=register_params, verify=False)
            print(f"   Response: {r.status_code} {r.text.strip()}")

            if "OCI_EXECUTE ERROR" in r.text:
                print(f"   ❌ FAILED for '{course['name']}': Server returned a database error.")
                continue # Skip to the next course

            r_json = r.json()
            if "Registration Successful" in r_json.get("message", ""):
                print(f"   ✅ SUCCESS for '{course['name']}'.")
            else:
                print(f"   ❌ FAILED for '{course['name']}': {r_json.get('message', 'Unknown error in JSON response.')}")

        except json.JSONDecodeError:
            print(f"   ❌ FAILED for '{course['name']}': The server's response was not valid JSON.")
        except (requests.exceptions.RequestException, KeyError) as e:
            print(f"   ❌ An error occurred while registering '{course['name']}': {e}")
        finally:
            print("-" * 20)

if __name__ == "__main__":
    main()
