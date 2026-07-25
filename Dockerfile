FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY medical_rag/ ./medical_rag/
COPY static/ ./static/
COPY app.py README.md .env.example ./
COPY pdfs/ ./pdfs/

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/.rag /app/pdfs \
    && chown -R app:app /app/.rag

COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

ENV PYTHONUNBUFFERED=1 \
    RAG_CORPUS_DIR=/app/pdfs \
    RAG_INDEX_PATH=/app/.rag/index.json \
    RAG_EMBEDDING_BACKEND=hash \
    RAG_GENERATION_BACKEND=extractive

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/ready || exit 1

USER app
ENTRYPOINT ["/app/docker-entrypoint.sh"]
