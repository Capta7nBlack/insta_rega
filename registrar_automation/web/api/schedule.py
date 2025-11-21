# web/api/schedule.py
import json
import redis
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from core.tasks import update_course_ids
from core.utils import parse_schedule_text
from celery.result import AsyncResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/schedule", tags=["Schedule"])
redis_client = redis.StrictRedis(host='localhost', port=6379, db=0, decode_responses=True)

# --- Pydantic Models ---
class ScheduleData(BaseModel):
    username: str
    password: str
    schedule_text: str

# --- Endpoints ---
@router.post("/validate")
async def validate_schedule(schedule: ScheduleData):

    logger.info(f"Starting schedule validation task for user: {schedule.username}")
    
    desired_schedule, course_names = parse_schedule_text(schedule.schedule_text)
    if not course_names:
        raise HTTPException(status_code=400, detail="Schedule file is empty or invalid.")

    task = update_course_ids.delay(
        credentials={"username": schedule.username, "password": schedule.password},
        desired_schedule=desired_schedule,
        course_names=course_names
    )

    logger.info(f"Task {task.id} created for schedule validation.")

    return {"status": "processing", "task_id": task.id}


@router.get("/validate/status/{task_id}")
async def get_validation_status(task_id: str):
    """
    The bot polls this endpoint to check the result of the schedule validation task.
    If the task is complete, it saves the result to Redis.
    """
    task_result = AsyncResult(task_id)
    if not task_result.ready():
        return {"status": "pending"}

    if task_result.successful():
        validated_courses = task_result.get()
        if not validated_courses:
            return {"status": "failed", "error": "Course validation failed. Please check your schedule.txt and try again."}

        logger.info(f"Task {task_id} validation successful.")
        return {"status": "success", "result": validated_courses}

    else:

        logger.error(f"Task {task_id} failed with an exception.", exc_info=True)
        return {"status": "failed", "error": "An unexpected error occurred during validation. Please try again later."}
