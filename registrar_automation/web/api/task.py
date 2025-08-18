# web/api/task.py

import redis
import json
from fastapi import APIRouter
from celery.result import AsyncResult

router = APIRouter(prefix="/task", tags=["Task"])
redis_client = redis.StrictRedis(host='localhost', port=6379, db=0, decode_responses=True)

@router.get("/status/{task_id}")
async def get_task_status(task_id: str, chat_id: int):
    task_result = AsyncResult(task_id)
    if not task_result.ready():
        return {"status": "pending"}

    if task_result.successful():
        validated_courses = task_result.get()
        if not validated_courses:
            return {"status": "failed", "error": "Course validation failed. Please check your schedule.txt and try again."}

        user_key = f"user:{chat_id}"
        redis_client.hset(user_key, "validated_courses", json.dumps(validated_courses))
        return {"status": "success", "result": validated_courses}
    else:
        return {"status": "failed", "error": "An unexpected error occurred during validation. Please try again later."}
