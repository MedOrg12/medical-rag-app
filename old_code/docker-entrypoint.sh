#!/bin/bash
set -e

echo "=========================================="
echo "Medical RAG - Docker Container Starting"
echo "=========================================="

# Fix permissions on mounted volumes for Windows compatibility
chmod -R 777 /app/pdfs /app/logs /app/vector_db /app/data 2>/dev/null || true

# Wait for Ollama service to be ready
echo "Waiting for Ollama service..."
OLLAMA_URL="${OLLAMA_BASE_URL:-http://ollama:11434}"
MAX_RETRIES=60
RETRY_COUNT=0

until curl -sf "$OLLAMA_URL/" > /dev/null 2>&1 || wget -qO- "$OLLAMA_URL/" > /dev/null 2>&1; do
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
        echo "WARNING: Ollama not reachable after ${MAX_RETRIES} attempts. Starting app anyway..."
        break
    fi
    echo "  Waiting for Ollama... ($RETRY_COUNT/$MAX_RETRIES)"
    sleep 2
done

echo "Ollama service check complete"

# Pull required models (non-blocking - app will wait if needed)
echo "Pulling required models (this may take several minutes on first run)..."
EMBEDDING_MODEL="${OLLAMA_EMBEDDING_MODEL:-nomic-embed-text}"
LLM_MODEL="${OLLAMA_MODEL:-deepseek-r1:1.5b}"

for MODEL in "$EMBEDDING_MODEL" "$LLM_MODEL"; do
    # Skip the pull if the model is already present in the cached volume.
    if curl -sf "$OLLAMA_URL/api/tags" 2>/dev/null | grep -q "\"$MODEL\""; then
        echo "  $MODEL already present, skipping pull"
        continue
    fi
    echo "  Pulling $MODEL..."
    curl -sf -X POST "$OLLAMA_URL/api/pull" \
        -H "Content-Type: application/json" \
        -d "{\"name\":\"$MODEL\"}" \
        --max-time 600 \
        --no-buffer 2>/dev/null | while IFS= read -r line; do
            STATUS=$(echo "$line" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('status',''))" 2>/dev/null || true)
            if [ -n "$STATUS" ]; then
                printf "\r  %-60s" "$STATUS"
            fi
        done || echo "  WARNING: Could not pull $MODEL (may already exist)"
    echo ""
done

echo "Model setup complete"

# Check if PDFs directory has files
PDF_COUNT=$(find /app/pdfs -type f -name "*.pdf" 2>/dev/null | wc -l)
echo "Found $PDF_COUNT PDF file(s) in /app/pdfs"

# Graceful shutdown handler
shutdown_handler() {
    echo ""
    echo "Shutting down gracefully..."
    kill -SIGTERM "$PID" 2>/dev/null || true
    wait "$PID" 2>/dev/null || true
    echo "Shutdown complete"
    exit 0
}
trap shutdown_handler SIGTERM SIGINT

# Start the FastAPI application
echo "=========================================="
echo "Starting Medical RAG Application"
echo "Web interface: http://localhost:8000"
echo "=========================================="

python3 app.py &
PID=$!
wait "$PID"
