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
  while the GPU embeds the next one, with at most two upserts outstanding. The final upsert
  waits, and the job then checks that the collection's point count matches the corpus, so a
  write Qdrant acknowledged but failed to apply fails the job instead of leaving gaps.
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
- `RAG_EMBED_BATCH_SIZE`: embedding batch size.

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
