# core/utils.py

import re

def parse_schedule_text(schedule_text: str):
    """
    Parses the raw text of a schedule.txt file into the two data structures
    needed by the update_course_ids Celery task. This is a shared utility.
    """
    desired_schedule = {}
    course_names = []
    for line in schedule_text.strip().splitlines():
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
                # Normalize different Lab types (e.g., Lb, CLb) into just 'Lb'
                section_type = 'Lb' if 'Lb' in section_type_raw else section_type_raw
                desired_schedule[course_code].append({
                    "section_num": section_num,
                    "type": section_type
                })
    return desired_schedule, course_names
