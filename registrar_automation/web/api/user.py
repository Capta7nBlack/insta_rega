# web/api/user.py

from core.redis_utils import hset_compat
import redis
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from core.tasks import pre_login

# Import the cancel function to use in reset
from .registration import cancel_registration

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

    print(f"✅ Credentials validated successfully for chat_id: {creds.chat_id}. Saving...")
    user_key = f"user:{creds.chat_id}"
    user_data = {
        "student_id": fetched_student_id, # Save the fetched ID with the correct name
        "username": creds.username,
        "password": creds.password
    }

    hset_compat(redis_client, user_key, user_data)
    return {"status": "success", "message": "Credentials have been validated and saved."}


@router.post("/reset")
async def reset_user_data(req: UserRequest):
    # First, try to cancel any active registration
    await cancel_registration(req)
    # Then, delete the user's main data hash
    redis_client.delete(f"user:{req.chat_id}")
    return {"status": "reset_success", "message": "All your data has been cleared."}
