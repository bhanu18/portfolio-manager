# 1. Base Image: Use the official lightweight Python image
FROM python:3.10-slim

# 2. Setup Work Directory
WORKDIR /app

# 3. Copy Requirements first (optimizes build caching)
COPY requirements.txt .

# 4. Install Dependencies
# We include 'gunicorn' for production server performance
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# 5. Copy the rest of the application code
COPY . .

# 6. Command to run the application
# Cloud Run injects the $PORT variable (usually 8080) automatically
CMD sh -c "uvicorn main:app --host 0.0.0.0 --port $PORT"