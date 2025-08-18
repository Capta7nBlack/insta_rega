# web/main.py

from fastapi import FastAPI
from .api import user, schedule, task, registration

# Initialize the FastAPI app
app = FastAPI(
    title="Course Registration Bot API",
    description="The backend API server for the automated course registration system.",
    version="1.0.0"
)

# Include the routers from the 'api' directory
# Each router handles a specific part of the API's functionality.
app.include_router(user.router)
app.include_router(schedule.router)
app.include_router(task.router)
app.include_router(registration.router)

@app.get("/", tags=["Root"])
async def read_root():
    """A simple root endpoint to confirm the API is running."""
    return {"message": "Welcome to the Course Registration API!"}
