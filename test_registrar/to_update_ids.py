from api_local_storage import LocalStorageAPI
from api_scraper import ScraperAPI

def main():
    """
    Orchestrates the entire ID update process by coordinating the local storage
    and scraper APIs.
    """
    # 1. Load local data
    storage = LocalStorageAPI()
    config = storage.get_config()
    credentials = config.get('credentials', {})
    desired_schedule, course_names = storage.parse_schedule_txt()

    # 2. Initialize and use the scraper
    scraper = ScraperAPI(headless=True)
    scraped_course_map = {}
    try:
        if not scraper.login(credentials):
            return # Exit if login fails

        scraper.add_courses_to_schedule(course_names)
        scraped_course_map = scraper.scrape_all_course_ids(desired_schedule)

    finally:
        scraper.close() # Ensure browser is always closed

    # 3. Validate data and update config
    if not scraped_course_map:
        print("\n❌ No data was scraped. Halting before config update.")
        return

    # Call the validation method directly from the scraper instance
    final_course_list = scraper.validate_and_build_course_list(desired_schedule, scraped_course_map)

    if final_course_list:
        storage.update_config_with_courses(final_course_list)
    else:
        print("\n⚠️  No valid courses were found after validation. config.json will not be updated.")

if __name__ == "__main__":
    main()
