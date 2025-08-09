from local_storage_api import LocalStorageAPI
from playwright.sync_api import sync_playwright, TimeoutError, Page
import warnings
import re

# Suppress InsecureRequestWarning for verify=False
warnings.filterwarnings('ignore', message='Unverified HTTPS request')

# --- Constants from your reference script ---
BASE_URL = "https://testregistrar.nu.edu.kz"
LOGIN_URL = f"{BASE_URL}/user/login"
COURSE_REG_URL = f"{BASE_URL}/my-registrar/course-registration"
SCHEDULE_TABLE_URL = f"{COURSE_REG_URL}/selected"

def login_to_registrar(page: Page, credentials: dict):
    """Logs into the registrar using Playwright."""
    print("--- Logging In ---")
    page.goto(LOGIN_URL)
    page.wait_for_selector('input[name="name"]')
    page.fill('input[name="name"]', credentials.get('username'))
    page.fill('input[name="pass"]', credentials.get('password'))
    page.click('input[name="op"]')
    print("✅ Login credentials submitted.")
    
    print("Waiting for 'Course registration' link to appear...")
    # Increased attempts and decreased timeout for a more aggressive and responsive check
    for attempt in range(1000): # Try up to 15 times
        try:
            # Use a short timeout to quickly retry if the element isn't there
            page.locator("a:text('Course registration')").click(timeout=2000)
            print("✅ Clicked 'Course registration' link.")
            page.wait_for_load_state('networkidle')
            return True
        except TimeoutError:
            print(f"   Attempt {attempt + 1}/15: Link not found, refreshing...")
            page.reload()
    print("❌ Failed to find 'Course registration' link after multiple attempts.")
    return False

def add_courses_to_schedule(page: Page, course_names: list):
    """Searches for each course and adds it to the schedule table."""
    print("\n--- Adding Courses to Schedule Table ---")
    for course_code in course_names:
        print(f"Processing '{course_code}'...")
        try:
            page.goto(COURSE_REG_URL)
            page.wait_for_selector('input[id="titleText-inputEl"]')
            page.fill('input[id="titleText-inputEl"]', course_code)
            page.click('span[id="show_courses_button-btnIconEl"]')
            
            course_row_selector = f"//tr[contains(., '{course_code}')]"
            page.wait_for_selector(course_row_selector, timeout=10000)

            print(f"  -> Search results for '{course_code}' loaded.")

            if page.locator("//*[text()='SELECTED COURSE']").is_visible():
                print(f"  -> INFO: '{course_code}' is already in the schedule table. Skipping.")
                continue

            page.locator("//*[text()='OPEN']").click()
            
            add_button = page.locator("//a[@class='green-button' and contains(text(), 'Add to Selected Courses')]")
            add_button.click()
            print(f"  -> ✅ Clicked 'Add' for '{course_code}'.")
            page.wait_for_timeout(500)

        except TimeoutError:
            print(f"  -> ⚠️  Could not add '{course_code}'. It might not be 'OPEN', or is already selected/registered.")
        except Exception as e:
            print(f"  -> ❌ An unexpected error occurred while adding '{course_code}': {e}")

def scrape_all_course_ids(page: Page, desired_schedule: dict) -> dict:
    """Navigates to the schedule table and scrapes all instance and component IDs."""
    print("\n--- Navigating to Schedule Table to Scrape IDs ---")
    page.goto(SCHEDULE_TABLE_URL)
    page.wait_for_load_state('networkidle')
    
    scraped_course_map = {}
    for course_code in desired_schedule.keys():
        try:
            print(f"Scraping details for '{course_code}'...")

            course_button_selector = f"//span[contains(text(), '{course_code.upper()} |')]"
            course_button = page.locator(course_button_selector)

            if not course_button.is_visible():
                print(f"  -> ⚠️  Could not find '{course_code}' in the schedule table. Was it added correctly?")
                continue
            course_button.click()
            
            
            section_panel_selector = "div#instanceSectionsPanel"
            page.wait_for_selector(section_panel_selector, state="visible", timeout=5000)
            
            scraped_course_map[course_code] = {"components": {}}
            
            inputs = page.locator(f'{section_panel_selector} input').all()
            for inp in inputs:
                full_id = inp.get_attribute('id')
                if not full_id or 'instance' not in full_id: continue

                parts = full_id.split('_')
                instance_id = parts[1]
                comp_id = parts[3]
                sec_num = parts[5]
                comp_type_raw = inp.get_attribute('name')

                # --- NORMALIZATION LOGIC ---
                # If the component name from the website contains 'Lab', treat it as 'Lab'
                if 'Lab' in comp_type_raw:
                    comp_type_normalized = 'Lab'
                else:
                    comp_type_normalized = comp_type_raw
                
                scraped_course_map[course_code]['instance_id'] = instance_id
                if comp_type_normalized not in scraped_course_map[course_code]['components']:
                    scraped_course_map[course_code]['components'][comp_type_normalized] = {
                        "component_id": comp_id,
                        "available_sections": []
                    }
                scraped_course_map[course_code]['components'][comp_type_normalized]['available_sections'].append(sec_num)
            print(f"  -> ✅ Scraped {len(inputs)} sections for '{course_code}'.")
        except TimeoutError:
            print(f"  -> ❌ Timed out waiting for section details for '{course_code}'.")
        except Exception as e:
            print(f"  -> ❌ An unexpected error occurred scraping '{course_code}': {e}")
            
    return scraped_course_map

def validate_and_build_course_list(desired_schedule: dict, scraped_course_map: dict) -> list:
    """
    Validates the user's desired schedule against the scraped data and builds the final list for config.json.
    """
    print("\n--- Validating Scraped Data and Building Final Config ---")
    final_course_list = []
    for course_code, desired_sections in desired_schedule.items():
        if course_code not in scraped_course_map:
            print(f"⚠️ WARNING: '{course_code}' was in schedule.txt but couldn't be scraped. Skipping.")
            continue

        scraped_course = scraped_course_map[course_code]
        course_obj = {
            "name": course_code,
            "instance_id": scraped_course.get('instance_id', ''),
            "components": []
        }
        valid = True
        for section in desired_sections:
            # This map connects the normalized input ('Lb') to the normalized scraped data ('Lab')
            type_map = {"L": "Lecture", "Lb": "Lab", "S": "Seminar", "R": "Recitation"}
            scraped_comp_type = type_map.get(section['type'])

            if not scraped_comp_type or scraped_comp_type not in scraped_course['components']:
                print(f"❌ ERROR: For '{course_code}', component type '{section['type']}' ('{scraped_comp_type}') not found.")
                valid = False; break
            
            component_data = scraped_course['components'][scraped_comp_type]
            if section['section_num'] not in component_data['available_sections']:
                print(f"❌ ERROR: For '{course_code}', {scraped_comp_type} section '{section['section_num']}' not found.")
                print(f"   Available sections are: {component_data['available_sections']}")
                valid = False; break
            
            course_obj['components'].append({
                "component_id": component_data['component_id'],
                "section_id": section['section_num']
            })
        
        if valid:
            final_course_list.append(course_obj)
            print(f"✅ '{course_code}' successfully validated.")
    
    return final_course_list

def main():
    """Orchestrates the entire ID update process using a single Playwright session."""
    storage = LocalStorageAPI()
    config = storage.get_config()
    credentials = config.get('credentials', {})

    desired_schedule, course_names = storage.parse_schedule_txt()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        
        try:
            if not login_to_registrar(page, credentials):
                return

            add_courses_to_schedule(page, course_names)
            
            scraped_course_map = scrape_all_course_ids(page, desired_schedule)

        finally:
            print("\n--- Closing Browser ---")
            browser.close()

    if not scraped_course_map:
        print("❌ No data was scraped. Halting before config update.")
        return

    # --- Validation and Finalization ---
    final_course_list = validate_and_build_course_list(desired_schedule, scraped_course_map)

    # --- Save to Config ---
    if final_course_list:
        storage.update_config_with_courses(final_course_list)
    else:
        print("⚠️  No valid courses were found after validation. config.json will not be updated.")

if __name__ == "__main__":
    main()

