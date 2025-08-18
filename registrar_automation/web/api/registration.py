# web/api/registration.py

import redis
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime, timedelta
from web.time_utils import get_ntp_time_offset

from core.redis_utils import hset_compat

router = APIRouter(prefix="/registration", tags=["Registration"])
redis_client = redis.StrictRedis(host='localhost', port=6379, db=0, decode_responses=True)

# --- Pydantic Models ---
class RegistrationTime(BaseModel):
    chat_id: int
    target_time_str: str

class UserRequest(BaseModel):
    chat_id: int

# --- Endpoints ---
@router.post("/set_time")
async def set_registration_time(reg_time: RegistrationTime):
    user_key = f"user:{reg_time.chat_id}"
    user_data = redis_client.hgetall(user_key)
    if not user_data:
        raise HTTPException(status_code=404, detail="User data not found.")
        
    if user_data.get("trigger_timestamp"):
        raise HTTPException(status_code=409, detail="You already have an active registration scheduled.")

    validated_courses_json = user_data.get("validated_courses")
    if not validated_courses_json:
        raise HTTPException(status_code=400, detail="Validated courses not found.")
    
    validated_courses = json.loads(validated_courses_json)

    try:
        target_dt = datetime.strptime(reg_time.target_time_str, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format.")

    if target_dt < datetime.now() + timedelta(minutes=1):
        raise HTTPException(status_code=400, detail="Registration time must be at least 1 minute in the future.")

    time_offset = get_ntp_time_offset()
    trigger_timestamp = int(target_dt.timestamp()) + 1 - time_offset
    pre_login_timestamp = trigger_timestamp - 10

    registration_plan = {
        "chat_id": reg_time.chat_id,
        "student_id": user_data['student_id'],
        "username": user_data['username'],
        "password": user_data['password'],
        "courses": validated_courses
    }
    
    hset_compat(redis_client, user_key, {
        "trigger_timestamp": trigger_timestamp,
        "pre_login_timestamp": pre_login_timestamp,
        "target_time_str": reg_time.target_time_str
    })

    redis_client.rpush(f"schedule:{pre_login_timestamp}:pre_login", json.dumps(registration_plan))
    redis_client.rpush(f"schedule:{trigger_timestamp}:registration", json.dumps(registration_plan))

    return {"status": "scheduled", "target_time": reg_time.target_time_str}

@router.post("/cancel")
async def cancel_registration(req: UserRequest):
    user_key = f"user:{req.chat_id}"
    user_data = redis_client.hgetall(user_key)
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found.")

    trigger_ts = user_data.get("trigger_timestamp")
    pre_login_ts = user_data.get("pre_login_timestamp")

    if not (trigger_ts and pre_login_ts):
        return {"status": "not_scheduled", "message": "No active registration was found to cancel."}

    keys_to_check = [f"schedule:{pre_login_ts}:pre_login", f"schedule:{trigger_ts}:registration"]
    
    for key in keys_to_check:
        all_plans_json = redis_client.lrange(key, 0, -1)
        for plan_json in all_plans_json:
            plan = json.loads(plan_json)
            if plan.get("chat_id") == req.chat_id:
                redis_client.lrem(key, 1, plan_json)
                break

    redis_client.hdel(user_key, "trigger_timestamp", "pre_login_timestamp", "target_time_str")
    
    return {"status": "cancelled", "message": "Your scheduled registration has been cancelled."}

@router.get("/status")
async def get_registration_status(chat_id: int):
    user_key = f"user:{chat_id}"
    user_data = redis_client.hgetall(user_key)
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found.")

    target_time = user_data.get("target_time_str")
    validated_courses_json = user_data.get("validated_courses")

    if not (target_time and validated_courses_json):
        return {"status": "not_scheduled", "message": "You do not have an active registration scheduled."}

    courses = [course['name'] for course in json.loads(validated_courses_json)]

    return {"status": "scheduled", "scheduled_time": target_time, "courses": courses}
