#!/bin/sh
set -eu

echo "Starting Stroke Medical RAG"

mkdir -p "$(dirname "${RAG_INDEX_PATH:-/app/.rag/index.json}")" "${RAG_CORPUS_DIR:-/app/pdfs}"
chmod -R 777 "$(dirname "${RAG_INDEX_PATH:-/app/.rag/index.json}")" "${RAG_CORPUS_DIR:-/app/pdfs}" 2>/dev/null || true

if [ "${RAG_EMBEDDING_BACKEND:-hash}" = "ollama" ] || [ "${RAG_GENERATION_BACKEND:-extractive}" = "ollama" ]; then
    OLLAMA_URL="${RAG_OLLAMA_BASE_URL:-${OLLAMA_BASE_URL:-http://ollama:11434}}"
    echo "Waiting briefly for Ollama at ${OLLAMA_URL}"
    retries=30
    count=0
    until curl -sf "${OLLAMA_URL}/" >/dev/null 2>&1; do
        count=$((count + 1))
        if [ "$count" -ge "$retries" ]; then
            echo "Ollama is not reachable. The app will still start; extractive fallback may be used for generation."
            break
        fi
        sleep 2
    done
fi

if [ "${RAG_AUTO_INGEST_ON_STARTUP:-true}" = "true" ]; then
    if [ ! -f "${RAG_INDEX_PATH:-/app/.rag/index.json}" ] || [ "${RAG_FORCE_REINGEST:-false}" = "true" ]; then
        echo "Building vector index from ${RAG_CORPUS_DIR:-/app/pdfs}"
        FORCE_ARG=""
        if [ "${RAG_FORCE_REINGEST:-false}" = "true" ]; then
            FORCE_ARG="--force"
        fi
        python3 -m medical_rag.cli ingest \
            --source "${RAG_CORPUS_DIR:-/app/pdfs}" \
            --pdf-workers "${RAG_PDF_WORKERS:-1}" \
            --embed-batch-size "${RAG_EMBED_BATCH_SIZE:-64}" \
            ${FORCE_ARG} || \
            echo "Initial ingestion failed. The server will start so ingestion can be retried from the UI or API."
    else
        echo "Vector index already exists at ${RAG_INDEX_PATH:-/app/.rag/index.json}"
    fi
fi

exec uvicorn medical_rag.server:app --host 0.0.0.0 --port 8000
