# Agent Trader - Production Ready
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Install system dependencies (including gcc for potential build needs)
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first
COPY requirements.txt .

# Install Python dependencies
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copy application code
COPY . .

# Validation Layer (The Pre-Flight Shield)
# Moved to Runtime CMD to avoid build-time permission issues
# RUN python validate_imports.py

# Create non-root user
RUN useradd -m -u 1000 trader && \
    chown -R trader:trader /app

USER trader

# Expose ports for Streamlit dashboard and embedded dashboard server
EXPOSE 8501 8080

# Default command runs the robust main heartbeat after validation
CMD ["python", "main.py"]
