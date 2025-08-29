# web/api/user.py

import logging
import redis
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from core.tasks import pre_login

# Redis back compatibility function
from core.redis_utils import hset_compat

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/user", tags=["User"])
redis_client = redis.StrictRedis(host='localhost', port=6379, db=0, decode_responses=True)

# --- Pydantic Models ---
class UserCredentials(BaseModel):
    chat_id: int
    username: str
    password: str

class UserRequest(BaseModel):
    chat_id: int

# --- Endpoints ---
@router.post("/credentials")
async def save_user_credentials(creds: UserCredentials):
    """
    Receives user credentials, validates them by running a pre_login task
    which also fetches the student ID, and saves all data on success.
    """
    print(f"Received credentials for chat_id: {creds.chat_id}. Validating...")

    # The pre_login task now only needs username and password
    validation_task = pre_login.delay(creds.username, creds.password)
    
    try:
        # The result will be the student_id string or None
        fetched_student_id = validation_task.get(timeout=20)
    except Exception as e:
        print(f"❌ Credential validation task failed for chat_id {creds.chat_id}: {e}")
        raise HTTPException(status_code=500, detail="An error occurred during validation. The university website may be down.")

    if not fetched_student_id:
        print(f"❌ Invalid credentials for chat_id: {creds.chat_id}")
        raise HTTPException(status_code=401, detail="Invalid username or password. Please try again.")

    owner_key = f"student_id_owner:{fetched_student_id}"
    existing_owner_chat_id = redis_client.get(owner_key)

    if existing_owner_chat_id and int(existing_owner_chat_id) != creds.chat_id:
        print(f"Conflict found. Student ID {fetched_student_id} is owned by another user.")
        print("Transferring ownership to the new user...")
        old_owner_req = UserRequest(chat_id=int(existing_owner_chat_id))
        # We call the reset logic directly here to avoid circular imports
        await reset_user_data(old_owner_req)

    print(f"✅ Credentials validated successfully for chat_id: {creds.chat_id}. Saving...")
    user_key = f"user:{creds.chat_id}"
    user_data = {
        "student_id": fetched_student_id,
        "username": creds.username,
        "password": creds.password
    }
    
    hset_compat(redis_client, user_key, user_data)
    redis_client.set(owner_key, creds.chat_id)
    
    return {"status": "success", "message": "Credentials have been validated and saved."}


@router.post("/reset")
async def reset_user_data(req: UserRequest):
    """
    Completely wipes a user's data, including releasing the ownership lock.
    """
    user_key = f"user:{req.chat_id}"
    user_data = redis_client.hgetall(user_key)

    # First, cancel any active registration by deleting its keys
    if user_data:
        trigger_ts = user_data.get("trigger_timestamp")
        pre_login_ts = user_data.get("pre_login_timestamp")

        if trigger_ts and pre_login_ts:
            keys_to_check = [f"schedule:{pre_login_ts}:pre_login", f"schedule:{trigger_ts}:registration"]
            for key in keys_to_check:
                all_plans_json = redis_client.lrange(key, 0, -1)
                for plan_json in all_plans_json:
                    plan = json.loads(plan_json)
                    if plan.get("chat_id") == req.chat_id:
                        redis_client.lrem(key, 1, plan_json)
                        break
    
    # Release the ownership lock if it exists
    if user_data and 'student_id' in user_data:
        student_id = user_data['student_id']
        owner_key = f"student_id_owner:{student_id}"
        print(f"Releasing ownership lock for student_id: {student_id}")
        redis_client.delete(owner_key)

    # Finally, delete the user's main data hash
    redis_client.delete(user_key)
    return {"status": "reset_success", "message": "All your data has been cleared."}





@router.get("/progress")
async def get_user_progress(chat_id: int):
    """
    A single endpoint for the bot to check the user's overall progress
    through the setup flow.
    """
    user_key = f"user:{chat_id}"
    user_data = redis_client.hgetall(user_key)

    # 1. Check if the user has any data at all
    if not user_data:
        return {"status": "uninitialized"}

    # 2. Check if the user has a fully scheduled registration
    if "trigger_timestamp" in user_data and "target_time_str" in user_data:
        try:
            validated_courses_json = user_data.get("validated_courses", "[]")
            courses = [course['name'] for course in json.loads(validated_courses_json)]
            return {
                "status": "scheduled",
                "scheduled_time": user_data['target_time_str'],
                "courses": courses
            }
        except (json.JSONDecodeError, KeyError):
             raise HTTPException(status_code=500, detail="Could not parse user's course data.")


    # 3. Check if the user has validated their schedule
    if "validated_courses" in user_data:
        try:
            validated_courses_json = user_data.get("validated_courses", "[]")
            courses = [course['name'] for course in json.loads(validated_courses_json)]
            return {"status": "schedule_saved", "courses": courses}
        except (json.JSONDecodeError, KeyError):
             raise HTTPException(status_code=500, detail="Could not parse user's course data.")

    # 4. Check if the user has only saved their credentials
    if "student_id" in user_data:
        return {"status": "credentials_saved"}

    # Fallback case, should not typically be reached
    return {"status": "uninitialized"}
