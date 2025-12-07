import os

# Docker internal URL for the backend
API_BASE_URL = os.getenv("API_BASE_URL", "http://web:8000")
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set in environment variables")
