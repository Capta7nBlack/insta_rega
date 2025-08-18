# web/api/user.py

import redis
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# Import the cancel function to use in reset
from .registration import cancel_registration

router = APIRouter(prefix="/user", tags=["User"])
redis_client = redis.StrictRedis(host='localhost', port=6379, db=0, decode_responses=True)

# --- Pydantic Models ---
class UserCredentials(BaseModel):
    chat_id: int
    user_id: str
    username: str
    password: str

class UserRequest(BaseModel):
    chat_id: int

# --- Endpoints ---
@router.post("/credentials")
async def save_user_credentials(creds: UserCredentials):
    user_key = f"user:{creds.chat_id}"
    user_data = {
        "user_id": creds.user_id,
        "username": creds.username,
        "password": creds.password
    }
    redis_client.hset(user_key, mapping=user_data)
    return {"status": "success", "message": "Credentials saved."}

@router.post("/reset")
async def reset_user_data(req: UserRequest):
    # First, try to cancel any active registration
    await cancel_registration(req)
    # Then, delete the user's main data hash
    redis_client.delete(f"user:{req.chat_id}")
    return {"status": "reset_success", "message": "All your data has been cleared."}
