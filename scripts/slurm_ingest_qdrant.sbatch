#!/bin/bash
#SBATCH --job-name=stroke-rag-ingest
#SBATCH --partition=gpu
#SBATCH --gres=a100:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#SBATCH --output=logs/slurm-ingest-%j.out
#SBATCH --error=logs/slurm-ingest-%j.err

set -euo pipefail

# Submit with environment overrides rather than editing this template, for example:
# sbatch --export=ALL,RAG_CORPUS_DIR=/shared/stroke/pdfs,RAG_OLLAMA_BASE_URL=http://ollama.internal:11434 scripts/slurm_ingest_qdrant.sbatch

PROJECT_DIR="${PROJECT_DIR:-$SLURM_SUBMIT_DIR}"
VENV_DIR="${VENV_DIR:-$PROJECT_DIR/.venv}"
RAG_CORPUS_DIR="${RAG_CORPUS_DIR:-$PROJECT_DIR/pdfs}"
RAG_SCRATCH_DIR="${RAG_SCRATCH_DIR:-${SLURM_TMPDIR:-$PROJECT_DIR/.rag-slurm}}"

cd "$PROJECT_DIR"
mkdir -p logs "$RAG_SCRATCH_DIR"

if [ -f "$VENV_DIR/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
fi

QDRANT_TUNNEL_PID=""
cleanup() {
  if [ -n "$QDRANT_TUNNEL_PID" ] && kill -0 "$QDRANT_TUNNEL_PID" 2>/dev/null; then
    kill "$QDRANT_TUNNEL_PID"
    wait "$QDRANT_TUNNEL_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

if [ "${RAG_QDRANT_SSH_TUNNEL:-true}" = "true" ]; then
  RAG_QDRANT_SSH_HOST="${RAG_QDRANT_SSH_HOST:-134.87.8.87}"
  RAG_QDRANT_SSH_TARGET="${RAG_QDRANT_SSH_HOST}"
  if [ -n "${RAG_QDRANT_SSH_USER:-}" ]; then
    RAG_QDRANT_SSH_TARGET="${RAG_QDRANT_SSH_USER}@${RAG_QDRANT_SSH_HOST}"
  fi
  RAG_QDRANT_LOCAL_PORT="${RAG_QDRANT_LOCAL_PORT:-6333}"
  RAG_QDRANT_REMOTE_HOST="${RAG_QDRANT_REMOTE_HOST:-127.0.0.1}"
  RAG_QDRANT_REMOTE_PORT="${RAG_QDRANT_REMOTE_PORT:-6333}"

  ssh \
    -o BatchMode=yes \
    -o ExitOnForwardFailure=yes \
    -N \
    -L "127.0.0.1:${RAG_QDRANT_LOCAL_PORT}:${RAG_QDRANT_REMOTE_HOST}:${RAG_QDRANT_REMOTE_PORT}" \
    "$RAG_QDRANT_SSH_TARGET" &
  QDRANT_TUNNEL_PID="$!"
  sleep 3

  export RAG_QDRANT_URL="${RAG_QDRANT_URL:-http://127.0.0.1:${RAG_QDRANT_LOCAL_PORT}}"
fi

export RAG_VECTOR_STORE="${RAG_VECTOR_STORE:-qdrant}"
export RAG_QDRANT_URL="${RAG_QDRANT_URL:?Set RAG_QDRANT_URL to the shared Qdrant endpoint}"
export RAG_QDRANT_COLLECTION="${RAG_QDRANT_COLLECTION:-stroke_chunks}"
export RAG_QDRANT_DENSE_VECTOR_NAME="${RAG_QDRANT_DENSE_VECTOR_NAME:-dense}"
export RAG_QDRANT_SPARSE_VECTOR_NAME="${RAG_QDRANT_SPARSE_VECTOR_NAME:-sparse}"
export RAG_QDRANT_BATCH_SIZE="${RAG_QDRANT_BATCH_SIZE:-128}"
export RAG_QDRANT_RECREATE_COLLECTION="${RAG_QDRANT_RECREATE_COLLECTION:-true}"

export RAG_CORPUS_DIR
export RAG_MANIFEST_PATH="${RAG_MANIFEST_PATH:-$RAG_SCRATCH_DIR/manifest.sqlite}"
export RAG_EXTRACTION_CACHE_DIR="${RAG_EXTRACTION_CACHE_DIR:-$RAG_SCRATCH_DIR/extracted}"
export RAG_EMBEDDING_CACHE_PATH="${RAG_EMBEDDING_CACHE_PATH:-$RAG_SCRATCH_DIR/embedding_cache.json}"

export RAG_EMBEDDING_BACKEND="${RAG_EMBEDDING_BACKEND:-ollama}"
export RAG_OLLAMA_BASE_URL="${RAG_OLLAMA_BASE_URL:?Set RAG_OLLAMA_BASE_URL to the embedding service reachable from the compute node}"
export RAG_OLLAMA_EMBEDDING_MODEL="${RAG_OLLAMA_EMBEDDING_MODEL:-nomic-embed-text}"
export RAG_PDF_WORKERS="${RAG_PDF_WORKERS:-${SLURM_CPUS_PER_TASK:-1}}"
export RAG_EMBED_BATCH_SIZE="${RAG_EMBED_BATCH_SIZE:-64}"

python -m medical_rag.cli ingest \
  --source "$RAG_CORPUS_DIR" \
  --force \
  --pdf-workers "$RAG_PDF_WORKERS" \
  --embed-batch-size "$RAG_EMBED_BATCH_SIZE"
