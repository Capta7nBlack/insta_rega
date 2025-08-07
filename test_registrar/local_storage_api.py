import json
import os
import sys
import time

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
