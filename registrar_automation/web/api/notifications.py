# web/api/notifications.py

import os
import requests
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/notifications", tags=["Notifications"])
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")

class NotificationRequest(BaseModel):
    chat_id: int
    text: str

@router.post("/send")
def send_notification(notification: NotificationRequest):
    """
    Sends a message to a Telegram user.
    defined as a synchronous function (def) so FastAPI runs it in a threadpool,
    preventing the blocking requests call from freezing the async event loop.
    """
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is not set in the Web API environment.")
        raise HTTPException(status_code=500, detail="Server configuration error.")

    telegram_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": notification.chat_id,
        "text": notification.text,
        "parse_mode": "Markdown"
    }

    try:
        response = requests.post(telegram_url, json=payload, timeout=5)
        response.raise_for_status()
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        # We return 500 but log the error so the worker knows it failed
        raise HTTPException(status_code=500, detail=str(e))
