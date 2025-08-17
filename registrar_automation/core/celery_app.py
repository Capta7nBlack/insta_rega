# insta_rega/core/celery_app.py

from celery import Celery

# Initialize the Celery application.
# The first argument 'tasks' is the name of the module where tasks are defined.
# The broker URL points to our Redis instance. Redis is used to pass messages
# between our web server/scheduler and the Celery workers.
# The backend URL is also Redis. This is used to store the results of tasks.
celery_app = Celery(
    'tasks',
    broker='redis://localhost:6379/0',
    backend='redis://localhost:6379/0',
    include=['core.tasks']  # Point to the module where tasks are defined
)

# Optional configuration
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Asia/Almaty', # Use the same timezone as the university
    enable_utc=True,
)

if __name__ == '__main__':
    celery_app.start()
