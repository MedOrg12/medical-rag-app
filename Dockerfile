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

RUN mkdir -p /app/.rag /app/pdfs && chmod -R 777 /app/.rag /app/pdfs

COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

ENV PYTHONUNBUFFERED=1 \
    RAG_CORPUS_DIR=/app/pdfs \
    RAG_INDEX_PATH=/app/.rag/index.json \
    RAG_MANIFEST_PATH=/app/.rag/manifest.sqlite \
    RAG_EXTRACTION_CACHE_DIR=/app/.rag/extracted \
    RAG_EMBEDDING_CACHE_PATH=/app/.rag/embedding_cache.json \
    RAG_PDF_WORKERS=1 \
    RAG_EMBED_BATCH_SIZE=64 \
    RAG_EMBEDDING_BACKEND=hash \
    RAG_GENERATION_BACKEND=extractive

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
