from playwright.sync_api import sync_playwright, TimeoutError, Page, Browser
import warnings

# Suppress warnings
warnings.filterwarnings('ignore', message='Unverified HTTPS request')

class ScraperAPI:
    """
    Handles all browser-based interactions with the registrar website for the purpose of
    scraping course IDs. It encapsulates a Playwright browser instance.
    """
    BASE_URL = "https://testregistrar.nu.edu.kz"
    LOGIN_URL = f"{BASE_URL}/user/login"
    COURSE_REG_URL = f"{BASE_URL}/my-registrar/course-registration"
    SCHEDULE_TABLE_URL = f"{COURSE_REG_URL}/selected"

    def __init__(self, headless=False):
        """Initializes the Playwright instance and launches the browser."""
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=headless)
        self._page = self._browser.new_page()
        print("✅ ScraperAPI initialized, browser launched.")

    def login(self, credentials: dict):
        """
        Logs into the registrar using the provided credentials.
        This is the first step before any scraping can occur.
        """
        print("--- Logging In ---")
        try:
            self._page.goto(self.LOGIN_URL)
            self._page.wait_for_selector('input[name="name"]')
            self._page.fill('input[name="name"]', credentials.get('username'))
            self._page.fill('input[name="pass"]', credentials.get('password'))
            self._page.click('input[name="op"]')
            print("✅ Login credentials submitted.")
            
            print("Waiting for 'Course registration' link to appear...")
            # Wait for navigation and click the main registration link
            self._page.locator("a:text('Course registration')").click(timeout=15000)
            self._page.wait_for_load_state('networkidle')
            print("✅ Clicked 'Course registration' link.")
            return True
        except TimeoutError:
            print("❌ Failed to find 'Course registration' link after logging in.")
            return False
        except Exception as e:
            print(f"❌ An unexpected error occurred during login: {e}")
            return False

    def add_courses_to_schedule(self, course_names: list):
        """
        Searches for each course by its code and adds it to the 'Selected Courses'
        table, making it available for ID scraping.
        """
        print("\n--- Adding Courses to Schedule Table ---")
        for course_code in course_names:
            print(f"Processing '{course_code}'...")
            try:
                self._page.goto(self.COURSE_REG_URL)
                self._page.wait_for_selector('input[id="titleText-inputEl"]')
                self._page.fill('input[id="titleText-inputEl"]', course_code)
                self._page.click('span[id="show_courses_button-btnIconEl"]')
                
                course_row_selector = f"//tr[contains(., '{course_code}')]"
                self._page.wait_for_selector(course_row_selector, timeout=10000)
                print(f"  -> Search results for '{course_code}' loaded.")

                if self._page.locator("//*[text()='SELECTED COURSE']").is_visible():
                    print(f"  -> INFO: '{course_code}' is already in the schedule table. Skipping.")
                    continue

                self._page.locator("//*[text()='OPEN']").click()
                
                add_button = self._page.locator("//a[@class='green-button' and contains(text(), 'Add to Selected Courses')]")
                add_button.click()
                print(f"  -> ✅ Clicked 'Add' for '{course_code}'.")
                self._page.wait_for_timeout(500) # Brief pause to ensure action completes

            except TimeoutError:
                print(f"  -> ⚠️  Could not add '{course_code}'. It might not be 'OPEN', or is already selected/registered.")
            except Exception as e:
                print(f"  -> ❌ An unexpected error occurred while adding '{course_code}': {e}")

    def scrape_all_course_ids(self, desired_schedule: dict) -> dict:
        """
        Navigates to the 'Selected Courses' table and scrapes the instance, component,
        and section IDs for each course listed.
        """
        print("\n--- Navigating to Schedule Table to Scrape IDs ---")
        self._page.goto(self.SCHEDULE_TABLE_URL)
        self._page.wait_for_load_state('networkidle')
        
        scraped_course_map = {}
        for course_code in desired_schedule.keys():
            try:
                print(f"Scraping details for '{course_code}'...")
                course_button_selector = f"//span[contains(text(), '{course_code.upper()} |')]"
                course_button = self._page.locator(course_button_selector)

                if not course_button.is_visible():
                    print(f"  -> ⚠️  Could not find '{course_code}' in the schedule table. Was it added correctly?")
                    continue
                course_button.click()
                
                section_panel_selector = "div#instanceSectionsPanel"
                self._page.wait_for_selector(section_panel_selector, state="visible", timeout=5000)
                
                scraped_course_map[course_code] = {"components": {}}
                
                inputs = self._page.locator(f'{section_panel_selector} input').all()
                for inp in inputs:
                    full_id = inp.get_attribute('id')
                    if not full_id or 'instance' not in full_id: continue

                    parts = full_id.split('_')
                    instance_id = parts[1]
                    comp_id = parts[3]
                    sec_num = parts[5]
                    comp_type_raw = inp.get_attribute('name')

                    # Normalize component type (e.g., 'Lab', 'Lecture')
                    comp_type_normalized = 'Lab' if 'Lab' in comp_type_raw else comp_type_raw
                    
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

    def validate_and_build_course_list(self, desired_schedule: dict, scraped_course_map: dict) -> list:
        """
        Validates the user's desired schedule against the scraped data and builds the
        final list of course objects for the configuration file.
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
            is_valid = True
            for section in desired_sections:
                type_map = {"L": "Lecture", "Lb": "Lab", "S": "Seminar", "R": "Recitation"}
                scraped_comp_type = type_map.get(section['type'])

                if not scraped_comp_type or scraped_comp_type not in scraped_course['components']:
                    print(f"❌ ERROR: For '{course_code}', component type '{section['type']}' ('{scraped_comp_type}') not found in scraped data.")
                    is_valid = False
                    break
                
                component_data = scraped_course['components'][scraped_comp_type]
                if section['section_num'] not in component_data['available_sections']:
                    print(f"❌ ERROR: For '{course_code}', {scraped_comp_type} section '{section['section_num']}' is not available.")
                    print(f"   Available sections are: {component_data['available_sections']}")
                    is_valid = False
                    break
                
                course_obj['components'].append({
                    "component_id": component_data['component_id'],
                    "section_id": section['section_num']
                })
            
            if is_valid:
                final_course_list.append(course_obj)
                print(f"✅ '{course_code}' successfully validated.")
        
        return final_course_list

    def close(self):
        """Closes the browser and stops the Playwright instance."""
        print("\n--- Closing Browser ---")
        self._browser.close()
        self._playwright.stop()
        print("✅ Browser closed.")

