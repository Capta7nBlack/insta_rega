# web/api/user.py

import logging
import redis
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from core.api_registrar import RegistrarAPI
from core.redis_utils import hset_compat


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/user", tags=["User"])
redis_client = redis.StrictRedis(host='localhost', port=6379, db=0, decode_responses=True)

# --- Constant Variables ---
DEFAULT_ATTEMPTS = 100


# --- Pydantic Models ---
class UserCredentials(BaseModel):
    username: str
    password: str
    mode: str


# --- Endpoints ---
@router.post("/validate")
async def validate_user_credentials(creds: UserCredentials):
    """
    НОВЫЙ ЭНДПОИНТ: Синхронно проверяет учетные данные.
    Бот будет вызывать это во время FSM.
    """
    logger.info(f"Validating credentials for user: {creds.username} against mode: {creds.mode}")
    try:
        api = RegistrarAPI()
        # api.login возвращает (cookies, token) при успехе
        # и (None, None) при неудаче.
        cookies, token = api.login(creds.username, creds.password, creds.mode)
        
        if not (cookies and token):
            logger.warning(f"Validation failed for user: {creds.username} on mode: {creds.mode}")
            raise HTTPException(status_code=401, detail="Invalid username or password.")

        logger.info(f"Credentials are valid for user: {creds.username} on mode: {creds.mode}")
        # Мы не сохраняем сессию, мы просто проверили, что она работает.
        # Сессия будет получена заново в задаче pre_login.
        return {"status": "success", "message": "Credentials are valid."}

    except HTTPException as e:
        # Перебрасываем HTTP исключение
        raise e
    except Exception as e:
        # Ловим любые другие ошибки (например, сайт недоступен)
        logger.error(f"Validation error for {creds.username} on mode {creds.mode}: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="The university website may be down. Could not validate credentials.")

@router.get("/status")
async def get_user_status(chat_id: int):
    """
    Получает статус пользователя. Если пользователь новый,
    инициализирует его со стандартным количеством попыток.
    """
    user_key = f"user:{chat_id}"
    
    if not redis_client.exists(user_key):
        print(f"New user detected. Initializing chat_id: {chat_id}")
        hset_compat(redis_client, user_key, {"attempts_left": DEFAULT_ATTEMPTS})
        
    attempts_left = redis_client.hget(user_key, "attempts_left")
    
    return {
        "status": "success",
        "chat_id": chat_id,
        "attempts_left": int(attempts_left)
