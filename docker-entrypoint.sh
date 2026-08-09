#!/bin/sh
set -eu

echo "Starting Stroke Medical RAG"

RAG_DATA_DIR="$(dirname "${RAG_INDEX_PATH:-/app/.rag/index.json}")"
RAG_CORPUS="${RAG_CORPUS_DIR:-/app/pdfs}"

mkdir -p "${RAG_DATA_DIR}" "${RAG_CORPUS}"
chmod -R u+rwX "${RAG_DATA_DIR}" 2>/dev/null || true

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
    SHOULD_INGEST="false"
    FORCE_ARG=""

    if [ ! -f "${RAG_INDEX_PATH:-/app/.rag/index.json}" ]; then
        SHOULD_INGEST="true"
    elif [ "${RAG_FORCE_REINGEST:-false}" = "true" ]; then
        SHOULD_INGEST="true"
        FORCE_ARG="--force"
    else
        CURRENT_EMBEDDING_MODEL="$(python3 - <<'PY'
from medical_rag.config import Settings
from medical_rag.embeddings import make_embedding_model

model, _ = make_embedding_model(Settings.from_env())
print(model.name)
PY
)"
        INDEX_EMBEDDING_MODEL="$(python3 - <<'PY'
import os
import re
from pathlib import Path

path = Path(os.environ.get("RAG_INDEX_PATH", "/app/.rag/index.json"))
if not path.exists():
    print("")
    raise SystemExit

with path.open("r", encoding="utf-8") as index_file:
    prefix = index_file.read(65536)

match = re.search(r'"embedding_model"\s*:\s*"([^"]+)"', prefix)
print(match.group(1) if match else "")
PY
)"

        if [ -n "${INDEX_EMBEDDING_MODEL}" ] && [ "${INDEX_EMBEDDING_MODEL}" != "${CURRENT_EMBEDDING_MODEL}" ]; then
            echo "Embedding model changed from ${INDEX_EMBEDDING_MODEL} to ${CURRENT_EMBEDDING_MODEL}; rebuilding vector index"
            SHOULD_INGEST="true"
        else
            echo "Vector index already exists at ${RAG_INDEX_PATH:-/app/.rag/index.json}"
        fi
    fi

    if [ "${SHOULD_INGEST}" = "true" ]; then
        echo "Building vector index from ${RAG_CORPUS_DIR:-/app/pdfs}"
        python3 -m medical_rag.cli ingest \
            --source "${RAG_CORPUS_DIR:-/app/pdfs}" \
            --pdf-workers "${RAG_PDF_WORKERS:-1}" \
            --embed-batch-size "${RAG_EMBED_BATCH_SIZE:-64}" \
            ${FORCE_ARG} || \
            echo "Initial ingestion failed. The server will start so ingestion can be retried from the UI or API."
    fi
fi

exec uvicorn medical_rag.server:app --host 0.0.0.0 --port 8000
