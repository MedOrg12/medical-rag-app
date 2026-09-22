# Slurm Qdrant Ingestion

Use `scripts/slurm_ingest_qdrant.sbatch` to run corpus ingestion as an offline Slurm job. The job reads PDFs from shared storage, writes parser and embedding caches to a scratch directory, and upserts chunks into a shared Qdrant collection.

## Prerequisites

- A shared checkout of this repository on the cluster.
- A Python virtual environment with `pip install -r requirements.txt`.
- The PDF corpus on storage visible from the compute node.
- SSH access from the compute node to `134.87.8.87`; the batch job opens a local tunnel to Qdrant by default.
- An embedding service reachable from the compute node. The template is set up for Ollama embeddings by default.

## Submit

```bash
cd /shared/projects/medical-rag-app

sbatch \
  --export=ALL,PROJECT_DIR=/shared/projects/medical-rag-app,RAG_CORPUS_DIR=/shared/data/stroke-pdfs,RAG_OLLAMA_BASE_URL=http://ollama.internal:11434 \
  scripts/slurm_ingest_qdrant.sbatch
```

Set `RAG_QDRANT_API_KEY` in the submit environment if the Qdrant service requires one.
Set `RAG_QDRANT_SSH_USER` if the SSH username for `134.87.8.87` differs from the Slurm job user.

## Useful Overrides

- `PROJECT_DIR`: repository checkout path. Defaults to `SLURM_SUBMIT_DIR`.
- `VENV_DIR`: Python virtual environment path. Defaults to `$PROJECT_DIR/.venv`.
- `RAG_CORPUS_DIR`: PDF/text corpus path.
- `RAG_SCRATCH_DIR`: job cache directory for manifest, extracted text, and embedding cache.
- `RAG_QDRANT_URL`: shared Qdrant endpoint.
- `RAG_QDRANT_SSH_TUNNEL`: open the Qdrant SSH tunnel. Defaults to `true`.
- `RAG_QDRANT_SSH_HOST`: SSH host for the tunnel. Defaults to `134.87.8.87`.
- `RAG_QDRANT_SSH_USER`: optional SSH user for the tunnel.
- `RAG_QDRANT_LOCAL_PORT`: local forwarded Qdrant port. Defaults to `6333`.
- `RAG_QDRANT_REMOTE_HOST`: host visible from the SSH server. Defaults to `127.0.0.1`.
- `RAG_QDRANT_REMOTE_PORT`: remote Qdrant port. Defaults to `6333`.
- `RAG_QDRANT_COLLECTION`: target collection. Defaults to `stroke_chunks`.
- `RAG_QDRANT_RECREATE_COLLECTION`: `true` rebuilds the collection for a clean ingestion run.
- `RAG_OLLAMA_BASE_URL`: embedding service endpoint.
- `RAG_PDF_WORKERS`: PDF extraction workers. Defaults to `SLURM_CPUS_PER_TASK`.
- `RAG_EMBED_BATCH_SIZE`: embedding batch size.

## After Ingestion

Point the API service at the same collection:

```bash
export RAG_VECTOR_STORE=qdrant
export RAG_QDRANT_URL=http://qdrant.internal:6333
export RAG_QDRANT_COLLECTION=stroke_chunks
export RAG_EMBEDDING_BACKEND=ollama
export RAG_OLLAMA_BASE_URL=http://ollama.internal:11434
export RAG_OLLAMA_EMBEDDING_MODEL=nomic-embed-text
```

Then start the app and run the eval suite against the live server.

If the web app still appears to use the old JSON index, check `/health`. It should report
`"vector_store_backend": "qdrant"` and the expected `qdrant_collection`. If it reports
`json`, restart the app with `RAG_VECTOR_STORE=qdrant` and point `RAG_QDRANT_URL` at the
same Qdrant service used by the Slurm job.
