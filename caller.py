import requests
import json
import time
from bs4 import BeautifulSoup
import warnings

# Suppress InsecureRequestWarning for verify=False
warnings.filterwarnings('ignore', message='Unverified HTTPS request')

# --- 1. CONFIGURE YOUR COURSES HERE ---
# As you requested, using the IDs from the test server.
# If the script fails, the most likely reason is that these IDs are different on the live server.
COURSES_TO_REGISTER = [
    {
        "name": "CSCI 361 (Lec+Lab)",
        "instance_id": "28008",
        "components": [
            {"component_id": "34172", "section_id": "2"},
            {"component_id": "34173", "section_id": "2"}
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

# --- 3. API AND URL CONFIGURATION (FOR LIVE SERVER) ---
LOGIN_URL = "https://registrar.nu.edu.kz/user/login"
REGISTRATION_PAGE_URL = "https://registrar.nu.edu.kz/my-registrar/course-registration"
API_URL = "https://registrar.nu.edu.kz/my-registrar/course-registration/json"

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
    

    print("\n--- Processing Shopping Cart ---")
    successful_courses = add_courses_to_cart(session, csrf_token, COURSES_TO_REGISTER)
    
    if not successful_courses:
        print("\nNo courses were successfully added to the cart. Exiting.")
        return

    print("\n--- Initiating Final Registration (One by One) ---")
    register_courses(session, csrf_token, successful_courses)

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

def add_courses_to_cart(session, csrf_token, courses):
    """Loops through courses and adds them to the shopping cart."""
    session.headers.update({
        "X-Requested-With": "XMLHttpRequest", "headerval": csrf_token,
        "Referer": REGISTRATION_PAGE_URL, "Origin": "https://registrar.nu.edu.kz"
    })
    
    successfully_added = []
    for course in courses:
        cart_payload = {"method": "shoppingCartAddRemove", "instanceid": course["instance_id"], "action": "1"}
        print(f"🛒 Adding '{course['name']}' (Instance: {course['instance_id']}) to cart...")
        try:
            r = session.post(API_URL, data=cart_payload, verify=False)
            print(f"   Response: {r.status_code} \"{r.text.strip()}\"")
            if r.status_code == 200 and ("Adding to Shopping Cart" in r.text or "Already in Shopping Cart" in r.text):
                print(f"   ✅ Success for '{course['name']}'.")
                successfully_added.append(course)
            else:
                print(f"   ❌ Failed to add '{course['name']}' to cart.")
        except requests.exceptions.RequestException as e:
            print(f"   ❌ Request failed for '{course['name']}': {e}")
        
        print("-" * 20)
    return successfully_added

def register_courses(session, csrf_token, courses):
    """Sends a separate registration request for each course."""
    session.headers.update({
        "x-csrf-token": csrf_token,
        "Referer": "https://registrar.nu.edu.kz/my-registrar/course-registration/selected",
    })
    session.headers.pop("headerval", None)

    total_success = 0
    for course in courses:
        component_parts = [
            f"instance_{course['instance_id']}_component_{comp['component_id']}_section_{comp['section_id']}"
            for comp in course['components']
        ]
        sections_string_for_this_course = "-".join(component_parts)
        register_params = {
            "_dc": int(time.time() * 1000), "method": "registerSections",
            "sections": sections_string_for_this_course, "userid": USER_ID
        }
        
        print(f"📤 Registering '{course['name']}'...")
        try:
            r = session.get(API_URL, params=register_params, verify=False)
            print(f"   Response: {r.status_code} {r.text.strip()}")

            if "OCI_EXECUTE ERROR" in r.text:
                print(f"   ❌ FAILED for '{course['name']}': Server returned a database error.")
                continue

            r_json = r.json()
            if "Registration Successful" in r_json.get("message", ""):
                print(f"   ✅ SUCCESS for '{course['name']}'.")
                total_success += 1
            else:
                print(f"   ❌ FAILED for '{course['name']}': {r_json.get('message', 'Unknown error.')}")
        except json.JSONDecodeError:
            print(f"   ❌ FAILED for '{course['name']}': The server's response was not valid JSON.")
        except (requests.exceptions.RequestException, KeyError) as e:
            print(f"   ❌ An error occurred while registering '{course['name']}': {e}")
        finally:
            print("-" * 20)
            time..sleep(1) # Wait 1s between final registration calls

    print(f"\n--- Registration Complete: Successfully registered for {total_success} out of {len(courses)} courses. ---")


if __name__ == "__main__":
    main()
