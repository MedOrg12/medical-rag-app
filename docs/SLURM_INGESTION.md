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

```bash
cd /shared/projects/medical-rag-app

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
- `RAG_SCRATCH_DIR`: job cache directory for manifest, extracted text, and embedding cache.
- `HF_HOME`: Hugging Face cache root. Defaults to `$RAG_SCRATCH_DIR/huggingface`.
- `RAG_QDRANT_URL`: shared Qdrant endpoint.
- `RAG_QDRANT_SSH_TUNNEL`: open the Qdrant SSH tunnel. Defaults to `true`.
- `RAG_QDRANT_SSH_HOST`: SSH host for the tunnel. Defaults to `134.87.8.87`.
- `RAG_QDRANT_SSH_USER`: optional SSH user for the tunnel.
- `RAG_QDRANT_LOCAL_PORT`: local forwarded Qdrant port. Defaults to `6333`.
- `RAG_QDRANT_REMOTE_HOST`: host visible from the SSH server. Defaults to `127.0.0.1`.
- `RAG_QDRANT_REMOTE_PORT`: remote Qdrant port. Defaults to `6333`.
- `RAG_QDRANT_COLLECTION`: target collection. Defaults to `stroke_chunks`.
- `RAG_QDRANT_RECREATE_COLLECTION`: `true` rebuilds the collection for a clean ingestion run.
- `RAG_QDRANT_TIMEOUT_SECONDS`: Qdrant request timeout. Defaults to `120` because collection
  creation on the shared Qdrant host has been measured at 5-10 seconds, above the 5 second
  qdrant-client default.
- `RAG_EMBEDDING_BACKEND`: default `sentence-transformers`; set `ollama` only to use a remote Ollama service.
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

Point the API service at the same collection:

```bash
export RAG_VECTOR_STORE=qdrant
export RAG_QDRANT_URL=http://qdrant.internal:6333
export RAG_QDRANT_COLLECTION=stroke_chunks
export RAG_EMBEDDING_BACKEND=sentence-transformers
export RAG_SENTENCE_TRANSFORMERS_MODEL=BAAI/bge-base-en-v1.5
```

Then start the app and run the eval suite against the live server.

If the web app still appears to use the old JSON index, check `/health`. It should report
`"vector_store_backend": "qdrant"` and the expected `qdrant_collection`. If it reports
`json`, restart the app with `RAG_VECTOR_STORE=qdrant` and point `RAG_QDRANT_URL` at the
same Qdrant service used by the Slurm job.
