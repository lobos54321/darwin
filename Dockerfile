FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY arena_server/ ./arena_server/
COPY agent_template/ ./agent_template/
COPY frontend/ ./frontend/

# Set PYTHONPATH to include root and arena_server for imports
ENV PYTHONPATH=/app:/app/arena_server

# Expose port
EXPOSE 8888

# Run the arena server
CMD ["python", "-m", "uvicorn", "arena_server.main:app", "--host", "0.0.0.0", "--port", "8888"]
