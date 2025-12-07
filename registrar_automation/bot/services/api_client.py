import aiohttp
import logging
from bot.config import API_BASE_URL

logger = logging.getLogger(__name__)

class BackendAPI:
    """
    Async client to communicate with the FastAPI backend.
    """
    
    @staticmethod
    async def validate_user(username, password, mode):
        """
        Hits /user/validate to check credentials.
        """
        url = f"{API_BASE_URL}/user/validate"
        payload = {"username": username, "password": password, "mode": mode}
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        return True, "Credentials valid."
                    elif resp.status == 401:
                        return False, "Invalid username or password."
                    else:
                        text = await resp.text()
                        logger.error(f"Validation error: {text}")
                        return False, "University website might be down."
            except Exception as e:
                logger.error(f"Connection error: {e}")
                return False, "Could not connect to backend service."

    @staticmethod
    async def validate_schedule(username, password, schedule_text):
        """
        Hits /schedule/validate to start the scraping task.
        Returns task_id.
        """
        url = f"{API_BASE_URL}/schedule/validate"
        payload = {
            "username": username, 
            "password": password, 
            "schedule_text": schedule_text
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data.get("task_id")

    @staticmethod
    async def get_schedule_status(task_id):
        """
        Polls /schedule/validate/status/{task_id}
        """
        url = f"{API_BASE_URL}/schedule/validate/status/{task_id}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                return await resp.json()

    @staticmethod
    async def create_job(job_data):
        """
        Hits /registration/create to schedule the final job.
        """
        url = f"{API_BASE_URL}/registration/create"
        params = {"chat_id": job_data["chat_id"]}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, params=params, json=job_data) as resp:
                resp.raise_for_status()
                return await resp.json()

    @staticmethod
    async def get_active_jobs(chat_id):
        url = f"{API_BASE_URL}/registration/list?chat_id={chat_id}"
        async with aiohttp.ClientSession() as session:
             async with session.get(url) as resp:
                 if resp.status == 200:
                     data = await resp.json()
                     return data.get("jobs", [])
                 return []
                 
    @staticmethod
    async def cancel_job(chat_id, job_id):
        url = f"{API_BASE_URL}/registration/cancel"
        payload = {"chat_id": chat_id, "job_id": job_id}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                return resp.status == 200
