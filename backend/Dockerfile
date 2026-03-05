# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set the working directory in the container
WORKDIR /app

# Install dependencies
# We copy requirements.txt first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose the port the app runs on (Cloud Run uses PORT env var)
EXPOSE 8080

# Command to run the application
# We use 0.0.0.0 to bind to all interfaces
# Cloud Run sets the PORT environment variable
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
