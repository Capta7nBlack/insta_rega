# web/api/schedule.py

import redis
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from core.tasks import update_course_ids
from core.utils import parse_schedule_text

router = APIRouter(prefix="/schedule", tags=["Schedule"])
redis_client = redis.StrictRedis(host='localhost', port=6379, db=0, decode_responses=True)

# --- Pydantic Models ---
class ScheduleData(BaseModel):
    chat_id: int
    schedule_text: str

# --- Endpoints ---
@router.post("/validate")
async def validate_schedule(schedule: ScheduleData):
    user_key = f"user:{schedule.chat_id}"
    user_data = redis_client.hgetall(user_key)
    if not user_data:
        raise HTTPException(status_code=404, detail="User credentials not found.")

    desired_schedule, course_names = parse_schedule_text(schedule.schedule_text)
    if not course_names:
        raise HTTPException(status_code=400, detail="Schedule file is empty or invalid.")

    task = update_course_ids.delay(
        credentials={"username": user_data['username'], "password": user_data['password']},
        desired_schedule=desired_schedule,
        course_names=course_names
    )
    return {"status": "processing", "task_id": task.id}
