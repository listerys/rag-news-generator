FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --default-timeout=100 -r requirements.txt

# Copy application code
COPY . .

# Create output directories
RUN mkdir -p /app/output /app/logs

# Set Python path
ENV PYTHONPATH=/app/src

CMD ["python", "src/controller.py"]
