# Slurm Qdrant Ingestion

Use `scripts/slurm_ingest_qdrant.sbatch` to run corpus ingestion as an offline Slurm job. The job reads PDFs from shared storage, writes parser and embedding caches to a scratch directory, and upserts chunks into a shared Qdrant collection.

## Prerequisites

- A shared checkout of this repository on the cluster.
- Python 3 on the compute node. By default the job creates or reuses `VENV_DIR`,
  then installs `requirements.txt` and `requirements-hpc.txt` inside the job.
- The PDF corpus on storage visible from the compute node.
- SSH access from the compute node to `134.87.8.87`; the batch job opens a local tunnel to Qdrant by default.
- The template requests one H100 and runs `sentence-transformers` embeddings on that GPU by default.
  Ollama is only used when `RAG_EMBEDDING_BACKEND=ollama`.

## Submit

Slurm writes the job's stdout/stderr into `logs/` and does not create that directory
itself, so create it once before the first submission.

```bash
cd /shared/projects/medical-rag-app
mkdir -p logs

sbatch \
  --export=ALL,PROJECT_DIR=/shared/projects/medical-rag-app,RAG_CORPUS_DIR=/shared/data/stroke-pdfs \
  scripts/slurm_ingest_qdrant.sbatch
```

Set `RAG_QDRANT_API_KEY` in the submit environment if the Qdrant service requires one.
Set `RAG_QDRANT_SSH_USER` if the SSH username for `134.87.8.87` differs from the Slurm job user.

The job validates SSH tunnels before ingestion starts. If a tunnel fails, the Slurm error log
prints the SSH target, forwarded port, and the relevant log path:

- `logs/qdrant-ssh-<jobid>.err`
- `logs/ollama-ssh-<jobid>.err`

## Useful Overrides

- `PROJECT_DIR`: repository checkout path. Defaults to `SLURM_SUBMIT_DIR`.
- `VENV_DIR`: Python virtual environment path. Defaults to `$PROJECT_DIR/.venv`.
- `PYTHON_BIN`: Python executable used to create `VENV_DIR`. Defaults to `python3`.
- `RAG_BOOTSTRAP_PYTHON_DEPS`: install Python dependencies inside the job. Defaults to `true`.
- `RAG_CORPUS_DIR`: PDF/text corpus path.
- `RAG_SCRATCH_DIR`: directory for the manifest and extracted-text cache. Defaults to
  `$PROJECT_DIR/.rag-slurm`. Keep it on shared storage rather than `SLURM_TMPDIR`, which is
  wiped when the job ends; without it every run re-parses the whole corpus.
- `RAG_INGEST_FORCE`: defaults to `false`, so PDFs whose extracted text is cached in
  `RAG_SCRATCH_DIR` are not re-parsed and a run over an unchanged corpus with an existing
  collection does nothing. Set `true` to re-parse everything. All documents still reach the
  vector store whenever anything changed, so stale-point cleanup is unaffected.
- `RAG_QDRANT_URL`: shared Qdrant endpoint.
- `RAG_QDRANT_SSH_TUNNEL`: open the Qdrant SSH tunnel. Defaults to `true`.
- `RAG_QDRANT_SSH_HOST`: SSH host for the tunnel. Defaults to `134.87.8.87`.
- `RAG_QDRANT_SSH_USER`: optional SSH user for the tunnel.
- `RAG_QDRANT_LOCAL_PORT`: local forwarded Qdrant port. Defaults to `6333`.
- `RAG_QDRANT_REMOTE_HOST`: host visible from the SSH server. Defaults to `127.0.0.1`.
- `RAG_QDRANT_REMOTE_PORT`: remote Qdrant port. Defaults to `6333`.
- `RAG_QDRANT_COLLECTION`: target collection. Defaults to `stroke_chunks`.
- `RAG_QDRANT_RECREATE_COLLECTION`: defaults to `false`, so the job upserts into the existing
  collection and deletes stale points. Set `true` to drop and rebuild it; this is required when
  switching to an embedding model with a different dimension. The job refuses to write into a
  collection whose vector size or name does not match.
- There is no separate embedding cache. Before embedding each batch the job asks Qdrant which
  points already hold a vector for the identical text and model, and only embeds the rest, so
  re-running over an unchanged corpus does no GPU work. The ingestion report shows
  `chunks_embedded` and `chunks_reused`.
- Writes overlap embedding: each batch is upserted with `wait=False` on a background thread
  while the GPU embeds the next one, with at most two upserts outstanding. Every eighth upsert
  and the final one wait, which keeps Qdrant's backlog of acknowledged-but-unapplied writes
  bounded so no single wait has to drain the whole run. The job then checks that the collection's point count matches the corpus, so a
  write Qdrant acknowledged but failed to apply fails the job instead of leaving gaps.
- Once a run has written about half of Qdrant's indexing threshold (roughly 1,700 768-dim
  vectors at the default), HNSW indexing is paused on the collection and restored when the
  job ends (including on failure), so Qdrant builds the index once instead of repeatedly
  re-indexing segments on its disk. Smaller incremental runs leave the collection config
  alone, since Qdrant would not index that little new data during the load anyway. Searches still work meanwhile, and Qdrant builds the index
  in the background after the job exits. If the job is killed before it can restore
  indexing, the next ingest that writes anything restores it.
- Batches whose collection was created by this run skip the reuse lookup, since nothing in a
  new collection can be reused.
- `RAG_QDRANT_PREFER_GRPC`: send Qdrant traffic over gRPC instead of REST. Defaults to `false`.
  gRPC ships vectors as packed floats rather than JSON, which saves serialization work and
  bytes through the tunnel; its effect on the shared host has not been measured. It needs the Qdrant host to publish its gRPC port (`6334` in
  `docker-compose.yml`); when tunnelling, the job opens a second tunnel for it.
- `RAG_QDRANT_GRPC_LOCAL_PORT` / `RAG_QDRANT_GRPC_REMOTE_PORT`: gRPC tunnel ports. Both
  default to `6334`.
- `HF_HOME`: Hugging Face model cache. Defaults to `$PROJECT_DIR/.hf-cache` so the embedding
  model is downloaded once and reused by later jobs.
- `RAG_QDRANT_TIMEOUT_SECONDS`: Qdrant request timeout. Defaults to `120` because collection
  creation on the shared Qdrant host has been measured at 5-10 seconds, above the 5 second
  qdrant-client default.
- `RAG_EMBEDDING_BACKEND`: default `sentence-transformers`; use `remote` on API hosts that query through the embedding service.
- `RAG_SENTENCE_TRANSFORMERS_MODEL`: default `BAAI/bge-base-en-v1.5`.
- `RAG_SENTENCE_TRANSFORMERS_DEVICE`: default `cuda`.
- `RAG_SENTENCE_TRANSFORMERS_BATCH_SIZE`: default `64`.
- `RAG_OLLAMA_BASE_URL`: Ollama embedding service endpoint when `RAG_EMBEDDING_BACKEND=ollama`.
- `RAG_OLLAMA_SSH_TUNNEL`: open an Ollama SSH tunnel when using Ollama and `RAG_OLLAMA_BASE_URL` is unset. Defaults to `true`.
- `RAG_OLLAMA_LOCAL_PORT`: local forwarded Ollama port. Defaults to `11434`.
- `RAG_OLLAMA_REMOTE_HOST`: host visible from the SSH server. Defaults to `127.0.0.1`.
- `RAG_OLLAMA_REMOTE_PORT`: remote Ollama port. Defaults to `11434`.
- `RAG_PDF_WORKERS`: PDF extraction workers. Defaults to `SLURM_CPUS_PER_TASK`.
- `RAG_EMBED_BATCH_SIZE`: chunks per embedding call and per Qdrant reuse lookup. Defaults to
  `256` in the job. The GPU still encodes in `RAG_SENTENCE_TRANSFORMERS_BATCH_SIZE`
  mini-batches.
- `RAG_QDRANT_BATCH_SIZE`: points per upsert request. Defaults to `1024`; against the shared
  host, write time fell from 3,384 s to 1,096 s going from 128 to 1024 on a 274k-chunk corpus.
- `RAG_QDRANT_MAX_REQUEST_MB`: upserts are also split to stay under this size. Defaults to
  `32`, Qdrant's default `service.max_request_size_mb`, which caps REST request bodies (gRPC
  has no such limit). A 768-dim point is about 18 KB of JSON, so 2048 points (~35 MB) would
  be rejected; keep this at or below the server's setting.

The ingestion report's `vector_store` section splits the vector-store stage's wall time into
phases that add up exactly: `setup`, `lookup` (reuse checks), `embedding`, `point_build`,
`write_wait` (stuck behind the background writer) and `cleanup`. `upsert_busy_seconds` is how
long the writer thread spent in upsert calls, so comparing it with `write_wait_seconds` shows
how much write time overlapped embedding.

## Benchmarking

`scripts/bench_ingest.py` compares commits (or settings) on the cluster without copying job
ids around. Run it from the login node in the repository:

```bash
scripts/bench_ingest.py submit --commit old=9a54a78 --commit new=HEAD \
  --corpus ../stress-test-pdfs --repeats 2 \
  --sweep RAG_QDRANT_BATCH_SIZE=256,1024 \
  --env RAG_QDRANT_SSH_USER=fir_ssh_tunnel
scripts/bench_ingest.py report      # latest run; re-run as jobs finish
scripts/bench_ingest.py list
```

Each commit is checked out into `.bench/worktrees/`, and each job runs that commit's own
ingest script through `scripts/bench_ingest_job.sbatch`, which:

- uses a fresh collection and a fresh scratch directory, so no job reuses another's vectors or
  parsed text,
- waits until no Qdrant collection is being optimized before starting (up to
  `BENCH_IDLE_TIMEOUT`, default 1800 s; the report flags jobs that started while it was busy),
- snapshots Qdrant telemetry before and after, so the report shows server-side upsert time and
  bytes written for the collection, separately from time spent in the tunnel and client,
- deletes the collection afterwards so its background indexing cannot slow the next job.

Jobs run one at a time (`afterany` chain) and alternate commit order between repeats, so a
drift in the shared host's load affects both commits equally. `--dry-run` prints the plan;
`--sbatch-arg=--time=06:00:00` passes extra sbatch options; `--env BENCH_PYSPY=true` records a
py-spy profile per job as `profile.speedscope.json` (install `py-spy` into the venv first;
`BENCH_PYSPY_RATE` sets samples per second, default 20 to keep multi-hour profiles small; open
it at speedscope.app). Python reuses thread ids, so the upsert writer thread can show up under
the name of qdrant-client's earlier `_check_compatibility` thread; `--runner local` runs the jobs
on the current machine without Slurm. Note that commits before the upsert-size change use
`RAG_QDRANT_BATCH_SIZE` as their upsert size too, but report timings in less detail.

## After Ingestion

Point the API service at the same collection and a remote embedding service. Queries must
be embedded with the same model the job used, because search filters points by
`embedding_model`; a mismatch returns no results.

```bash
export RAG_VECTOR_STORE=qdrant
export RAG_QDRANT_URL=http://<qdrant-host>:6333
export RAG_QDRANT_COLLECTION=stroke_chunks
export RAG_EMBEDDING_BACKEND=remote
export RAG_EMBEDDING_SERVICE_URL=http://<gpu-host>:8100
export RAG_EMBEDDING_SERVICE_EXPECTED_MODEL=sentence-transformers:BAAI/bge-base-en-v1.5
export RAG_AUTO_INGEST_ON_STARTUP=false
```

Keep `RAG_AUTO_INGEST_ON_STARTUP=false` and avoid the `/ingest` endpoint on the API host.
Ingesting from the API host with a different embedding backend would overwrite the
Slurm-built points in place, since point ids derive from chunk content.

Then start the app and run the eval suite against the live server.

If the web app still appears to use the old JSON index, check `/health`. It should report
`"vector_store_backend": "qdrant"` and the expected `qdrant_collection`. If it reports
`json`, restart the app with `RAG_VECTOR_STORE=qdrant` and point `RAG_QDRANT_URL` at the
same Qdrant service used by the Slurm job.

## Job Duration Varies by Node

The embedding phase includes importing torch, transformers, and sentence-transformers from
the project virtual environment on the first model call. Those imports touch thousands of
files and can take anywhere from a few seconds to a few minutes depending on how warm the
network filesystem is on the assigned compute node. The `.err` log reports the import and
model load times separately from encoding. The GPU work itself for ~1,700 chunks is about
five seconds on an H100.
