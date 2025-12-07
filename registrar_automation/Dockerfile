# Use an official Python runtime that includes Playwright dependencies
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Set the working directory in the container to /app
WORKDIR /app

# Copy the requirements file into the container at /app
COPY requirements.txt .

# Install Python dependencies specified in requirements.txt
# --no-cache-dir keeps the image size smaller
# ADDED: --default-timeout=1000 to fix slow network issues
RUN pip install --default-timeout=1000 --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container at /app
COPY . .
