# web/api/registration.py

import redis
import json
import uuid
import logging

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from datetime import datetime, timedelta
from web.time_utils import get_ntp_time_offset
from celery.result import AsyncResult
from core.redis_utils import hset_compat

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/registration", tags=["Registration"])
redis_client = redis.StrictRedis(host='localhost', port=6379, db=0, decode_responses=True)


async def check_user_attempts(chat_id: int):
    """
    Проверяет, есть ли у пользователя попытки. 
    Если нет, вызывает исключение.
    Если да, атомарно уменьшает счетчик на 1.
    """
    user_key = f"user:{chat_id}"
    try:
        # HINCRBY - атомарная операция
        new_attempts = redis_client.hincrby(user_key, "attempts_left", -1)
        
        if new_attempts < 0:
            # Если попыток стало < 0, отменяем операцию
            redis_client.hincrby(user_key, "attempts_left", 1)
            logger.warning(f"Chat_id {chat_id} has no registration attempts left.")
            raise HTTPException(status_code=403, detail="No registration attempts left.")
        
        logger.info(f"Attempt debited for chat_id {chat_id}. Remaining: {new_attempts}")
        return new_attempts
    except redis.RedisError as e:
        logger.error(f"Redis error while checking attempts for {chat_id}: {e}")
        raise HTTPException(status_code=500, detail="Database error while checking attempts.")


# --- Pydantic Models ---

class NewRegistrationJob(BaseModel):
    """
    Модель для эндпоинта /create.
    Собирает ВСЕ данные из FSM бота.
    """
    chat_id: int
    username: str
    password: str
    target_time_str: str # Формат: "YYYY-MM-DD HH:MM:SS"
    mode: str            # 'real' или 'test'
    validated_courses: list 

class CancelJobRequest(BaseModel):
    """ Модель для эндпоинта /cancel """
    chat_id: int
    job_id: str



# --- Endpoints ---
@router.post("/create")
async def create_registration_job(job: NewRegistrationJob, attempts_left: int = Depends(check_user_attempts)):
    """
    Конечная точка FSM. Получает все данные о задании,
    создает job_id, сохраняет его в job_index и ставит в очередь шедулера.
    """
    try:
        target_dt = datetime.strptime(job.target_time_str, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Must be YYYY-MM-DD HH:MM:SS")

    try:
        time_offset = get_ntp_time_offset()
    except Exception as e:
        logger.error(f"NTP Time offset failed: {e}. Defaulting to 0.0")
        time_offset = 0.0

    ntp_now = datetime.fromtimestamp(datetime.now().timestamp() - time_offset)

    if target_dt < ntp_now + timedelta(seconds=20):
        logger.warning(f"Job creation failed: Target time {target_dt} is in the past or too soon.")
        raise HTTPException(status_code=400, detail="Registration time must be at least 20 seconds in the future.")

    # Вычисление временных меток для "Timed Strike"
    trigger_timestamp = int(int(target_dt.timestamp()) + 1 - time_offset)
    pre_login_timestamp = trigger_timestamp - 10 # За 10 секунд
    
    job_id = str(uuid.uuid4()) # Уникальный ID для этого задания

    # 1. "План Задания" для шедулера
    job_plan = {
        "job_id": job_id,
        "chat_id": job.chat_id,
        "username": job.username,
        "password": job.password,
        "courses": job.validated_courses,
        "mode": job.mode
    }
    
    # 2. Запись "в приборной панели" для пользователя
    job_dashboard_entry = {
        "username": job.username,
        "target_time": job.target_time_str,
        "mode": job.mode,
        "status": "scheduled",
        "timestamp_pre_login": pre_login_timestamp,
        "timestamp_trigger": trigger_timestamp,
        "courses": [course.get('name', 'N/A') for course in job.validated_courses]
    }

    job_index_key = f"job_index:{job.chat_id}"

    # --- Атомарная запись в Redis ---
    try:
        pipe = redis_client.pipeline()
        job_plan_json = json.dumps(job_plan)
        
        # Помещаем задание в очередь шедулера
        pipe.rpush(f"schedule:{pre_login_timestamp}:pre_login", job_plan_json)
        pipe.rpush(f"schedule:{trigger_timestamp}:registration", job_plan_json)
        
        # Добавляем задание в "приборную панель" пользователя
        pipe.hset(job_index_key, job_id, json.dumps(job_dashboard_entry))
        
        pipe.execute()
        
        logger.info(f"Job {job_id} created successfully for chat_id {job.chat_id}")
        
    except Exception as e:
        # Если что-то пошло не так, возвращаем попытку
        redis_client.hincrby(f"user:{job.chat_id}", "attempts_left", 1)
        logger.error(f"Failed to schedule job {job_id} in Redis: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to schedule job: {e}")

    return {
        "status": "scheduled",
        "job_id": job_id,
        "target_time": job.target_time_str,
        "mode": job.mode,
        "attempts_left": attempts_left
    }


@router.get("/list")
async def get_user_jobs(chat_id: int):
    """
    Реализует команду /show_registration.
    Читает job_index пользователя и возвращает все активные задания.
    """
    job_index_key = f"job_index:{chat_id}"
    if not redis_client.exists(job_index_key):
        return {"status": "success", "jobs": []} # У пользователя еще нет заданий
        
    jobs_raw = redis_client.hgetall(job_index_key)
    jobs = []
    
    for job_id, job_json in jobs_raw.items():
        try:
            job_data = json.loads(job_json)
            job_data['job_id'] = job_id
            jobs.append(job_data)
        except json.JSONDecodeError:
            logger.warning(f"Corrupted job_json for job_id {job_id} in {job_index_key}")
            continue

    # Сортируем по времени для удобства
    jobs.sort(key=lambda x: x.get('target_time', ''))
    
    return {"status": "success", "jobs": jobs}



@router.post("/cancel")
async def cancel_registration_job(req: CancelJobRequest):
    """
    Реализует команду /cancel_registration.
    Находит задание по job_id, удаляет его из job_index и из очередей scheduler'a.
    """
    job_index_key = f"job_index:{req.chat_id}"
    
    # 1. Получаем детали задания, чтобы знать, какие timestamp удалять
    job_json = redis_client.hget(job_index_key, req.job_id)
    if not job_json:
        logger.warning(f"Job {req.job_id} not found for cancellation by chat_id {req.chat_id}")
        raise HTTPException(status_code=404, detail="Job not found or already cancelled.")

    try:
        job_data = json.loads(job_json)
        pre_login_ts = job_data.get("timestamp_pre_login")
        trigger_ts = job_data.get("timestamp_trigger")
        if not (pre_login_ts and trigger_ts):
             raise KeyError("Timestamps are missing from job data")
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Could not parse job data for cancellation {req.job_id}: {e}")
        # Удаляем битую запись из индекса, но не можем очистить очередь
        redis_client.hdel(job_index_key, req.job_id)
        raise HTTPException(status_code=500, detail="Could not parse job data for cancellation.")

    # 2. Находим и удаляем планы из очередей шедулера (LREM)
    keys_to_check = [f"schedule:{pre_login_ts}:pre_login", f"schedule:{trigger_ts}:registration"]
    plans_removed = 0
    
    for key in keys_to_check:
        all_plans_json = redis_client.lrange(key, 0, -1)
        for plan_json in all_plans_json:
            try:
                plan = json.loads(plan_json)
                # Мы ищем по job_id, чтобы удалить нужный план
                if plan.get("job_id") == req.job_id:
                    redis_client.lrem(key, 1, plan_json)
                    plans_removed += 1
                    break 
            except json.JSONDecodeError:
                continue

    # 3. Удаляем задание из "приборной панели" пользователя (HDEL)
    redis_client.hdel(job_index_key, req.job_id)
    
    # 4. Возвращаем попытку
    new_attempts = redis_client.hincrby(f"user:{req.chat_id}", "attempts_left", 1)
    
    logger.info(f"Job {req.job_id} cancelled by {req.chat_id}. Removed {plans_removed} entries. Attempts set to {new_attempts}.")

    return {
        "status": "cancelled", 
        "message": f"Job {req.job_id} has been cancelled.",
        "attempts_left": new_attempts
    }

@router.get("/result/{job_id}")
async def get_registration_result(job_id: str, chat_id: int):
    """
    Бот опрашивает этот эндпоинт, чтобы получить
    окончательный отчет о регистрации.
    """
    job_index_key = f"job_index:{chat_id}"
    job_json = redis_client.hget(job_index_key, job_id)
    if not job_json:
        # Может быть, отчет уже был получен и удален?
        # Или это неверный job_id.
        logger.warning(f"Attempt to get result for unknown/deleted job {job_id} by {chat_id}")
        raise HTTPException(status_code=404, detail="Job not found. It might have been already processed and deleted.")
        
    try:
        job_data = json.loads(job_json)
    except json.JSONDecodeError:
         raise HTTPException(status_code=500, detail="Corrupted job data.")

    task_id = job_data.get("registration_task_id") 

    if not task_id:
        # Шедулер еще не запустил задачу
        return {"status": "scheduled", "message": "The job is scheduled but not yet running."}

    task_result = AsyncResult(task_id)
    if not task_result.ready():
        return {"status": "pending", "message": "Registration is in progress."}

    # Когда задание будет готово, мы получим результат,
    # удалим его из job_index и вернем отчет.
    final_report = None
    status = "unknown"
    
    if task_result.successful():
        final_report = task_result.get()
        status = "success"
        logger.info(f"Job {job_id} result fetched successfully by {chat_id}")
    else:
        final_report = {"error": f"Task failed: {task_result.traceback}"}
        status = "failed"
        logger.error(f"Job {job_id} failed. Traceback: {task_result.traceback}")
    
    # Очистка: удаляем завершенное задание из индекса
    redis_client.hdel(job_index_key, job_id)
    
    return {"status": status, "report": final_report}
