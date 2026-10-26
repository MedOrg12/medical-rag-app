#!/bin/bash
#SBATCH --job-name=rag-ingest-bench
#SBATCH --gpus-per-node=h100:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=04:00:00

# One benchmark job, submitted by scripts/bench_ingest.py; not meant to be run by hand.
# Runs the ingest script of the commit under test (from its git worktree) against a fresh
# collection, and around it: waits for Qdrant to be idle, snapshots Qdrant telemetry before
# and after, then deletes the collection so its background indexing cannot slow the next job.

set -euo pipefail

: "${BENCH_ENV_FILE:?BENCH_ENV_FILE must point at the env file of the job}"
# shellcheck disable=SC1090
source "$BENCH_ENV_FILE"
: "${BENCH_TOOL:?}" "${BENCH_WORKTREE:?}" "${BENCH_JOB_DIR:?}" "${RAG_QDRANT_COLLECTION:?}"

mkdir -p "$BENCH_JOB_DIR"
cd "$BENCH_JOB_DIR"

# Per-job local ports, so this job's tunnels cannot collide with another job on the node.
PORT_BASE=$(( 20000 + ${SLURM_JOB_ID:-$$} % 20000 ))
export RAG_QDRANT_LOCAL_PORT="$PORT_BASE"
export RAG_QDRANT_GRPC_LOCAL_PORT=$(( PORT_BASE + 1 ))
BENCH_QDRANT_PORT=$(( PORT_BASE + 2 ))

BENCH_TUNNEL_PID=""
cleanup() {
  if [ -n "$BENCH_TUNNEL_PID" ] && kill -0 "$BENCH_TUNNEL_PID" 2>/dev/null; then
    kill "$BENCH_TUNNEL_PID"
    wait "$BENCH_TUNNEL_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

if [ "${RAG_QDRANT_SSH_TUNNEL:-true}" = "true" ]; then
  SSH_TARGET="${RAG_QDRANT_SSH_HOST:-134.87.8.87}"
  if [ -n "${RAG_QDRANT_SSH_USER:-}" ]; then
    SSH_TARGET="${RAG_QDRANT_SSH_USER}@${SSH_TARGET}"
  fi
  ssh -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -N \
    -L "127.0.0.1:${BENCH_QDRANT_PORT}:${RAG_QDRANT_REMOTE_HOST:-127.0.0.1}:${RAG_QDRANT_REMOTE_PORT:-6333}" \
    "$SSH_TARGET" 2>"$BENCH_JOB_DIR/bench-ssh.err" &
  BENCH_TUNNEL_PID="$!"
  sleep 3
  kill -0 "$BENCH_TUNNEL_PID" 2>/dev/null || { cat "$BENCH_JOB_DIR/bench-ssh.err" >&2; exit 2; }
  BENCH_QDRANT_URL="http://127.0.0.1:${BENCH_QDRANT_PORT}"
else
  BENCH_QDRANT_URL="${RAG_QDRANT_URL:?Set RAG_QDRANT_URL when RAG_QDRANT_SSH_TUNNEL=false}"
fi

qdrant_tool() {
  python3 "$BENCH_TOOL" "$1" --url "$BENCH_QDRANT_URL" --collection "$RAG_QDRANT_COLLECTION" "${@:2}"
}

qdrant_tool _wait-idle --timeout "${BENCH_IDLE_TIMEOUT:-1800}" --out qdrant-idle.json || true
qdrant_tool _snapshot --out qdrant-before.json || true

INGEST=(bash "$BENCH_WORKTREE/scripts/slurm_ingest_qdrant.sbatch")
if [ "${BENCH_PYSPY:-false}" = "true" ]; then
  PYSPY="$(command -v py-spy || echo "${VENV_DIR:-}/bin/py-spy")"
  INGEST=("$PYSPY" record --subprocesses --idle --rate "${BENCH_PYSPY_RATE:-20}" --format speedscope \
    -o "$BENCH_JOB_DIR/profile.speedscope.json" -- "${INGEST[@]}")
fi

started=$(date +%s.%N)
set +e
PROJECT_DIR="$BENCH_WORKTREE" "${INGEST[@]}" >ingest.out 2>ingest.err
status=$?
set -e
finished=$(date +%s.%N)
python3 -c "import json,sys; json.dump({'exit_code': int(sys.argv[1]), 'wall_seconds': float(sys.argv[3]) - float(sys.argv[2])}, open('job.json', 'w'))" \
  "$status" "$started" "$finished"

qdrant_tool _snapshot --out qdrant-after.json || true
if [ "${BENCH_KEEP_COLLECTION:-false}" != "true" ]; then
  qdrant_tool _delete-collection || true
fi
if [ "${BENCH_KEEP_SCRATCH:-false}" != "true" ]; then
  rm -rf "$RAG_SCRATCH_DIR"
fi

echo "ingest exit code: $status; output in $BENCH_JOB_DIR/ingest.out and ingest.err"
tail -n 5 ingest.err || true
exit "$status"
