#!/bin/bash
#SBATCH --job-name=stroke-rag-ingest
#SBATCH --gpus-per-node=h100:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#SBATCH --output=logs/slurm-ingest-%j.out
#SBATCH --error=logs/slurm-ingest-%j.err

set -euo pipefail

# Submit with environment overrides rather than editing this template, for example:
# sbatch --export=ALL,RAG_CORPUS_DIR=/shared/stroke/pdfs scripts/slurm_ingest_qdrant.sbatch

PROJECT_DIR="${PROJECT_DIR:-$SLURM_SUBMIT_DIR}"
VENV_DIR="${VENV_DIR:-$PROJECT_DIR/.venv}"
RAG_CORPUS_DIR="${RAG_CORPUS_DIR:-$PROJECT_DIR/pdfs}"
RAG_SCRATCH_DIR="${RAG_SCRATCH_DIR:-${SLURM_TMPDIR:-$PROJECT_DIR/.rag-slurm}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

cd "$PROJECT_DIR"
mkdir -p logs "$RAG_SCRATCH_DIR"

if [ "${RAG_BOOTSTRAP_PYTHON_DEPS:-true}" = "true" ]; then
  if [ ! -f "$VENV_DIR/bin/activate" ]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
  fi
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt -r requirements-hpc.txt
fi

if [ -f "$VENV_DIR/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
fi

QDRANT_TUNNEL_PID=""
OLLAMA_TUNNEL_PID=""
JOB_ID="${SLURM_JOB_ID:-manual}"
cleanup() {
  if [ -n "$QDRANT_TUNNEL_PID" ] && kill -0 "$QDRANT_TUNNEL_PID" 2>/dev/null; then
    kill "$QDRANT_TUNNEL_PID"
    wait "$QDRANT_TUNNEL_PID" 2>/dev/null || true
  fi
  if [ -n "$OLLAMA_TUNNEL_PID" ] && kill -0 "$OLLAMA_TUNNEL_PID" 2>/dev/null; then
    kill "$OLLAMA_TUNNEL_PID"
    wait "$OLLAMA_TUNNEL_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

fail() {
  echo "ERROR: $*" >&2
  exit 2
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command '$1' was not found on this compute node"
}

check_local_port() {
  local service_name="$1"
  local local_port="$2"
  python - "$service_name" "$local_port" <<'PY'
import socket
import sys

service_name = sys.argv[1]
local_port = int(sys.argv[2])
try:
    with socket.create_connection(("127.0.0.1", local_port), timeout=5):
        pass
except OSError as exc:
    print(f"{service_name} tunnel did not open local port 127.0.0.1:{local_port}: {exc}", file=sys.stderr)
    raise SystemExit(1)
PY
}

start_tunnel() {
  local service_name="$1"
  local local_port="$2"
  local remote_host="$3"
  local remote_port="$4"
  local pid_var="$5"
  local log_path="logs/${service_name}-ssh-${JOB_ID}.err"

  require_command ssh
  echo "Opening ${service_name} SSH tunnel: 127.0.0.1:${local_port} -> ${remote_host}:${remote_port} via ${RAG_QDRANT_SSH_TARGET}"

  ssh \
    -o BatchMode=yes \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -N \
    -L "127.0.0.1:${local_port}:${remote_host}:${remote_port}" \
    "$RAG_QDRANT_SSH_TARGET" \
    2>"$log_path" &

  local tunnel_pid="$!"
  printf -v "$pid_var" '%s' "$tunnel_pid"
  sleep 3

  if ! kill -0 "$tunnel_pid" 2>/dev/null; then
    echo "ERROR: ${service_name} SSH tunnel process exited before ingestion could start." >&2
    echo "SSH target: ${RAG_QDRANT_SSH_TARGET}" >&2
    echo "Forward: 127.0.0.1:${local_port} -> ${remote_host}:${remote_port}" >&2
    echo "SSH log: ${log_path}" >&2
    if [ -s "$log_path" ]; then
      echo "--- ${service_name} SSH stderr ---" >&2
      tail -n 40 "$log_path" >&2
      echo "--- end SSH stderr ---" >&2
    fi
    fail "Could not establish ${service_name} SSH tunnel"
  fi

  if ! check_local_port "$service_name" "$local_port"; then
    echo "SSH target: ${RAG_QDRANT_SSH_TARGET}" >&2
    echo "Forward: 127.0.0.1:${local_port} -> ${remote_host}:${remote_port}" >&2
    echo "SSH log: ${log_path}" >&2
    if [ -s "$log_path" ]; then
      echo "--- ${service_name} SSH stderr ---" >&2
      tail -n 40 "$log_path" >&2
      echo "--- end SSH stderr ---" >&2
    fi
    fail "${service_name} SSH tunnel started but local port validation failed"
  fi
}

RAG_QDRANT_SSH_HOST="${RAG_QDRANT_SSH_HOST:-134.87.8.87}"
RAG_QDRANT_SSH_TARGET="${RAG_QDRANT_SSH_HOST}"
if [ -n "${RAG_QDRANT_SSH_USER:-}" ]; then
  RAG_QDRANT_SSH_TARGET="${RAG_QDRANT_SSH_USER}@${RAG_QDRANT_SSH_HOST}"
fi

if [ "${RAG_QDRANT_SSH_TUNNEL:-true}" = "true" ]; then
  RAG_QDRANT_LOCAL_PORT="${RAG_QDRANT_LOCAL_PORT:-6333}"
  RAG_QDRANT_REMOTE_HOST="${RAG_QDRANT_REMOTE_HOST:-127.0.0.1}"
  RAG_QDRANT_REMOTE_PORT="${RAG_QDRANT_REMOTE_PORT:-6333}"

  start_tunnel "qdrant" "$RAG_QDRANT_LOCAL_PORT" "$RAG_QDRANT_REMOTE_HOST" "$RAG_QDRANT_REMOTE_PORT" QDRANT_TUNNEL_PID
  export RAG_QDRANT_URL="${RAG_QDRANT_URL:-http://127.0.0.1:${RAG_QDRANT_LOCAL_PORT}}"
fi

export RAG_VECTOR_STORE="${RAG_VECTOR_STORE:-qdrant}"
export RAG_QDRANT_URL="${RAG_QDRANT_URL:?Set RAG_QDRANT_URL to the shared Qdrant endpoint}"
export RAG_QDRANT_COLLECTION="${RAG_QDRANT_COLLECTION:-stroke_chunks}"
export RAG_QDRANT_DENSE_VECTOR_NAME="${RAG_QDRANT_DENSE_VECTOR_NAME:-dense}"
export RAG_QDRANT_SPARSE_VECTOR_NAME="${RAG_QDRANT_SPARSE_VECTOR_NAME:-sparse}"
export RAG_QDRANT_BATCH_SIZE="${RAG_QDRANT_BATCH_SIZE:-128}"
export RAG_QDRANT_RECREATE_COLLECTION="${RAG_QDRANT_RECREATE_COLLECTION:-false}"
# Collection create/delete on the shared Qdrant host can take well over the 5s client default.
export RAG_QDRANT_TIMEOUT_SECONDS="${RAG_QDRANT_TIMEOUT_SECONDS:-120}"

export RAG_CORPUS_DIR
export RAG_MANIFEST_PATH="${RAG_MANIFEST_PATH:-$RAG_SCRATCH_DIR/manifest.sqlite}"
export RAG_EXTRACTION_CACHE_DIR="${RAG_EXTRACTION_CACHE_DIR:-$RAG_SCRATCH_DIR/extracted}"
export RAG_EMBEDDING_CACHE_PATH="${RAG_EMBEDDING_CACHE_PATH:-$RAG_SCRATCH_DIR/embedding_cache.json}"

export HF_HOME="${HF_HOME:-$RAG_SCRATCH_DIR/huggingface}"
export TRANSFORMERS_CACHE="${TRANSFORMERS_CACHE:-$HF_HOME/transformers}"
export SENTENCE_TRANSFORMERS_HOME="${SENTENCE_TRANSFORMERS_HOME:-$HF_HOME/sentence-transformers}"
export RAG_EMBEDDING_BACKEND="${RAG_EMBEDDING_BACKEND:-sentence-transformers}"
export RAG_SENTENCE_TRANSFORMERS_MODEL="${RAG_SENTENCE_TRANSFORMERS_MODEL:-BAAI/bge-base-en-v1.5}"
export RAG_SENTENCE_TRANSFORMERS_DEVICE="${RAG_SENTENCE_TRANSFORMERS_DEVICE:-cuda}"
export RAG_SENTENCE_TRANSFORMERS_BATCH_SIZE="${RAG_SENTENCE_TRANSFORMERS_BATCH_SIZE:-64}"
if [ "$RAG_EMBEDDING_BACKEND" = "ollama" ] && [ -z "${RAG_OLLAMA_BASE_URL:-}" ]; then
  if [ "${RAG_OLLAMA_SSH_TUNNEL:-true}" = "true" ]; then
    RAG_OLLAMA_LOCAL_PORT="${RAG_OLLAMA_LOCAL_PORT:-11434}"
    RAG_OLLAMA_REMOTE_HOST="${RAG_OLLAMA_REMOTE_HOST:-127.0.0.1}"
    RAG_OLLAMA_REMOTE_PORT="${RAG_OLLAMA_REMOTE_PORT:-11434}"

    start_tunnel "ollama" "$RAG_OLLAMA_LOCAL_PORT" "$RAG_OLLAMA_REMOTE_HOST" "$RAG_OLLAMA_REMOTE_PORT" OLLAMA_TUNNEL_PID
    export RAG_OLLAMA_BASE_URL="http://127.0.0.1:${RAG_OLLAMA_LOCAL_PORT}"
  else
    echo "RAG_EMBEDDING_BACKEND=ollama requires RAG_OLLAMA_BASE_URL or RAG_OLLAMA_SSH_TUNNEL=true" >&2
    exit 2
  fi
fi
export RAG_OLLAMA_EMBEDDING_MODEL="${RAG_OLLAMA_EMBEDDING_MODEL:-nomic-embed-text}"
export RAG_PDF_WORKERS="${RAG_PDF_WORKERS:-${SLURM_CPUS_PER_TASK:-1}}"
export RAG_EMBED_BATCH_SIZE="${RAG_EMBED_BATCH_SIZE:-64}"

if [ "$RAG_EMBEDDING_BACKEND" = "sentence-transformers" ]; then
  echo "--- GPU visibility ---"
  command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || echo "nvidia-smi not found"
  echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-<unset>}"
  python - <<'PY'
import os
import time

import torch

print(f"torch {torch.__version__} cuda_build={torch.version.cuda} cuda_available={torch.cuda.is_available()} devices={torch.cuda.device_count()}")
if torch.cuda.is_available():
    print(f"device 0: {torch.cuda.get_device_name(0)} capability={torch.cuda.get_device_capability(0)}")
    print(f"torch arch list: {torch.cuda.get_arch_list()} TORCH_CUDA_ARCH_LIST={os.environ.get('TORCH_CUDA_ARCH_LIST', '<unset>')}")
    print(f"torch threads: {torch.get_num_threads()} OMP_NUM_THREADS={os.environ.get('OMP_NUM_THREADS', '<unset>')}")
    # Raw GPU throughput: an H100 should sustain well over 40 TFLOPS fp32 here.
    a = torch.randn(8192, 8192, device="cuda"); b = torch.randn(8192, 8192, device="cuda")
    torch.cuda.synchronize(); (a @ b); torch.cuda.synchronize()
    t = time.perf_counter()
    for _ in range(10):
        a @ b
    torch.cuda.synchronize()
    dt = time.perf_counter() - t
    print(f"matmul benchmark: 10 x 8192^2 fp32 in {dt:.3f}s = {10 * 2 * 8192**3 / dt / 1e12:.1f} TFLOPS")
    try:
        from sentence_transformers import SentenceTransformer

        model_name = os.environ.get("RAG_SENTENCE_TRANSFORMERS_MODEL", "BAAI/bge-base-en-v1.5")
        model = SentenceTransformer(model_name, device="cuda")
        tok = model.tokenizer
        print(f"tokenizer: {type(tok).__name__} is_fast={getattr(tok, 'is_fast', None)} dtype={next(model.parameters()).dtype}")
        texts = ["Stroke is a leading cause of disability. " * 30] * 64
        model.encode(texts, batch_size=64)
        for _ in range(3):
            t = time.perf_counter()
            model.encode(texts, batch_size=64, normalize_embeddings=True, convert_to_numpy=True)
            print(f"direct encode benchmark: 64 texts x ~330 tokens in {time.perf_counter() - t:.3f}s")
        t = time.perf_counter()
        tok(texts, padding=True, truncation=True, max_length=512, return_tensors="pt")
        print(f"tokenize only: 64 texts in {time.perf_counter() - t:.3f}s")
    except Exception as exc:  # diagnostics must never fail the job
        print(f"direct encode benchmark skipped: {exc!r}")
PY
  echo "RAG_SENTENCE_TRANSFORMERS_DEVICE=${RAG_SENTENCE_TRANSFORMERS_DEVICE}"
  echo "RAG_EMBED_BATCH_SIZE=${RAG_EMBED_BATCH_SIZE} RAG_SENTENCE_TRANSFORMERS_BATCH_SIZE=${RAG_SENTENCE_TRANSFORMERS_BATCH_SIZE} RAG_PDF_WORKERS=${RAG_PDF_WORKERS}"
  echo "HF_HOME=${HF_HOME}"
  echo "----------------------"
fi

python -m medical_rag.cli ingest \
  --source "$RAG_CORPUS_DIR" \
  --force \
  --pdf-workers "$RAG_PDF_WORKERS" \
  --embed-batch-size "$RAG_EMBED_BATCH_SIZE"
