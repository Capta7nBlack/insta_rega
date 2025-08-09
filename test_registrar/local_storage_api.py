import json
import os
import sys
import time
import re

class LocalStorageAPI:
    """
    Handles all local file interactions: reading configs, writing session data,
    and validating the freshness of the session file.
    """
    def __init__(self, config_file="config.json", session_file="session_data.json", max_age_minutes=10):
        self.config_file = config_file
        self.session_file = session_file
        self.max_age_minutes = max_age_minutes

    # --- Public Methods ---

    def get_config(self):
        """Public method to load and return the entire configuration."""
        return self.__load_json_file(self.config_file)

    def get_validated_session_data(self):
        """
        Public method that validates session freshness and returns the data.
        This is the main entry point for the registrar script.
        """
        self.__validate_session_age()
        return self.__load_json_file(self.session_file)

    def save_session_data(self, session_cookies, csrf_token):
        """Public method to write session data to the file."""
        print(f"💾 Saving session data to '{self.session_file}'...")
        session_data = {
            "cookies": session_cookies,
            "csrf_token": csrf_token
        }
        self.__save_json_file(self.session_file, session_data)
        print(f"✅ Session data successfully saved.")

    def update_config_with_courses(self, new_course_list):
        """Reads the config, replaces the course list, and saves it."""
        print("💾 Updating config.json with new course data...")
        config_data = self.get_config()
        config_data['courses_to_register'] = new_course_list
        self.__save_json_file(self.config_file, config_data)
        print("✅ config.json successfully updated.")

    # --- Public Method for Parsing Schedule ---

    def parse_schedule_txt(self, schedule_file="schedule.txt"):
        """
        Parses schedule.txt into a structured format for validation and a simple list of names.
        It normalizes different Lab types (e.g., Lb, CLb) into just 'Lb'.
        """
        print(f"📖 Reading and parsing '{schedule_file}'...")
        if not os.path.exists(schedule_file):
            print(f"❌ ABORTING: Schedule file not found: '{schedule_file}'")
            sys.exit(1)

        desired_schedule = {}
        course_names = []

        with open(schedule_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or ':' not in line:
                    continue
                
                course_code, sections_str = line.split(':', 1)
                course_code = course_code.strip()
                course_names.append(course_code)
                desired_schedule[course_code] = []

                sections = [s.strip() for s in sections_str.split(',')]
                for section in sections:
                    match = re.match(r'(\d+)([a-zA-Z]+)', section)
                    if match:
                        section_num, section_type_raw = match.groups()
                        
                        # --- NORMALIZATION LOGIC ---
                        # If the type contains 'Lb', treat it as the standard 'Lb'
                        if 'Lb' in section_type_raw:
                            section_type_normalized = 'Lb'
                        else:
                            section_type_normalized = section_type_raw

                        desired_schedule[course_code].append({
                            "section_num": section_num,
                            "type": section_type_normalized
                        })
        
        print("✅ Schedule parsed successfully.")
        return desired_schedule, course_names

    # --- Private Methods ---

    def __load_json_file(self, filepath):
        """Private method to read and parse a JSON file."""
        if not os.path.exists(filepath):
            print(f"❌ ABORTING: Required file not found: '{filepath}'")
            sys.exit(1)
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except (IOError, json.JSONDecodeError, KeyError) as e:
            print(f"❌ ABORTING: Error loading or parsing '{filepath}': {e}")
            sys.exit(1)

    def __save_json_file(self, filepath, data):
        """Private method to write data to a JSON file."""
        try:
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=4)
        except IOError as e:
            print(f"❌ Failed to write to file '{filepath}': {e}")
            sys.exit(1)
            
    def __validate_session_age(self):
        """Private method to check if the session file is fresh."""
        print("--- Validating Session Data ---")
        if not os.path.exists(self.session_file):
            print(f"❌ ABORTING: Session file '{self.session_file}' not found.")
            print("   Please run to_login.py to create it.")
            sys.exit(1)

        file_age_seconds = time.time() - os.path.getmtime(self.session_file)
        max_age_seconds = self.max_age_minutes * 60

        if file_age_seconds > max_age_seconds:
            print(f"❌ ABORTING: Session data is stale (created {int(file_age_seconds / 60)} minutes ago).")
            print(f"   Maximum allowed age is {self.max_age_minutes} minutes.")
            print("   Please run to_login.py to refresh the session.")
            sys.exit(1)

        print(f"✅ Session data is fresh (created {int(file_age_seconds)}s ago).")
