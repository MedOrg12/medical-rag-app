# Medical RAG Application - Docker Image
# Base image: Python 3.12 slim for smaller image size
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies required for Python packages
# - gcc, g++, make: For building native extensions
# - curl: For health checks and Ollama communication
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements-prod.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements-prod.txt

# Copy application code
COPY src/ ./src/
COPY api/ ./api/
COPY static/ ./static/
COPY app.py .
COPY requirements-prod.txt .

# Copy env file (use .env.example as default, or .env if provided)
COPY .env* ./
RUN if [ -f .env.example ] && [ ! -f .env ]; then cp .env.example .env; fi

# Copy PDFs (optional - can also be mounted as volume)
COPY pdfs/ ./pdfs/

# Create directories for data persistence with proper permissions
# Permissions set to 777 for Windows volume mount compatibility
RUN mkdir -p /app/vector_db /app/logs /app/data && \
    chmod -R 777 /app/vector_db /app/logs /app/data /app/pdfs

# Copy and set executable permission for entrypoint script
COPY docker-entrypoint.sh /app/
RUN chmod +x /app/docker-entrypoint.sh

# Expose port for web interface
EXPOSE 8000

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    DOCKER_CONTAINER=true \
    OLLAMA_BASE_URL=http://ollama:11434

# Health check to ensure application is running
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

# Use entrypoint script for initialization
ENTRYPOINT ["/app/docker-entrypoint.sh"]
