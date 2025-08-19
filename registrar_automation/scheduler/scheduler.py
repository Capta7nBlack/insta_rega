# scheduler/scheduler.py

import time
import redis
import json
from celery import Celery

# Configure a Celery app instance just for sending tasks
celery_app = Celery(
    'scheduler_tasks',
    broker='redis://localhost:6379/0'
)

# Connect to Redis to check for scheduled jobs
redis_client = redis.StrictRedis(host='localhost', port=6379, db=0, decode_responses=True)

def run_scheduler():
    """
    The main loop for the scheduler. It runs once per second, checks for jobs,
    and creates Celery tasks for any jobs it finds.
    """
    print("✅ Scheduler started. Waiting for jobs...")
    
    # On startup, set the last checked time to a minute ago to catch up on missed jobs
    last_checked_timestamp = int(time.time()) - 60

    while True:
        current_timestamp = int(time.time())
        
        # Only run the main logic if the second has changed
        if current_timestamp > last_checked_timestamp:
            
            # --- CATCH-UP LOGIC ---
            # Check for all jobs from the last time we checked up to now
            for ts in range(last_checked_timestamp + 1, current_timestamp + 1):
                
                # Check for pre-login jobs
                pre_login_key = f"schedule:{ts}:pre_login"
                pre_login_jobs = redis_client.lrange(pre_login_key, 0, -1)
                if pre_login_jobs:
                    print(f"Found {len(pre_login_jobs)} pre-login job(s) for timestamp {ts}")
                    for job_json in pre_login_jobs:
                        job_data = json.loads(job_json)
                        # Send the pre_login task to the Celery workers
                        task = celery_app.send_task(
                                'tasks.pre_login',
                                args=[
                                    job_data['username'],
                                    job_data['password']
                                    ]
                                )
                        # Save the task ID to the redis data base
                        redis_client.hset(f"user:{job_data['chat_id']}", "pre_login_task_id", task.id)

                    # Atomically delete the key so jobs aren't run twice
                    redis_client.delete(pre_login_key)

                # Check for main registration jobs
                reg_key = f"schedule:{ts}:registration"
                reg_jobs = redis_client.lrange(reg_key, 0, -1)
                if reg_jobs:
                    print(f"Found {len(reg_jobs)} registration job(s) for timestamp {ts}")
                    for job_json in reg_jobs:
                        job_data = json.loads(job_json)
                        # Send the run_registration task to the Celery workers
                        task = celery_app.send_task(
                                'tasks.run_registration',
                                args=[
                                    job_data['chat_id'],
                                    job_data['username'],
                                    job_data['password'],
                                    job_data['student_id'],
                                    job_data['courses']
                                    ]
                                )

                        redis_client.hset(f"user:{job_data['chat_id']}", "registration_task_id", task.id)
                    # Atomically delete the key
                    redis_client.delete(reg_key)

            # Update the last checked timestamp
            last_checked_timestamp = current_timestamp
        
        # Sleep for a short interval to prevent high CPU usage
        time.sleep(0.1)

if __name__ == "__main__":
    run_scheduler()
