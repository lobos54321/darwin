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

# Expose port (Zeabur uses 8080 by default)
EXPOSE 8080

# Run the arena server (Let main.py handle PORT env var)
CMD ["python", "arena_server/main.py"]
