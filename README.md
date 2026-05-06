# Stroke Medical RAG

Clean stroke-focused retrieval-augmented generation system. The previous repository code has been archived under `old_code/`; the usable corpus remains in `pdfs/`.

## What Is Included

- PDF, Markdown, and text ingestion
- Page-aware chunking with stable chunk IDs
- Local deterministic vector retrieval with no external service required
- Optional Ollama embeddings and chat generation
- JSON vector index stored at `.rag/index.json`
- FastAPI API and a minimal browser UI
- CLI commands for ingesting and asking questions
- Focused tests for the core RAG path

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python -m medical_rag.cli ingest --source pdfs
python -m medical_rag.cli ask "What are common signs of stroke?"
python app.py
```

Open `http://127.0.0.1:8000` after starting the server.

## Docker

The Docker setup is active at the repository root and targets the refactored app.

```bash
docker compose up --build
```

The container mounts `./pdfs` into `/app/pdfs`, stores the generated vector index in a named volume, and auto-ingests on first startup. The app is available at `http://127.0.0.1:8000`.

To run with Ollama generation:

```bash
RAG_GENERATION_BACKEND=ollama docker compose --profile ollama up --build
```

The default Docker path still works without Ollama by using local hashing retrieval and extractive answers.

## API

```bash
curl -X POST http://127.0.0.1:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{"source_path":"pdfs"}'

curl -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"What does the indexed literature say about stroke rehabilitation?"}'
```

## Optional Ollama Mode

Default retrieval uses the built-in hashing vectorizer and default answers are extractive. To use Ollama for generation:

```bash
export RAG_GENERATION_BACKEND=ollama
export RAG_OLLAMA_GENERATION_MODEL=llama3.1
python -m medical_rag.cli ask "What does SPAN-100 estimate?"
```

To use Ollama embeddings, set `RAG_EMBEDDING_BACKEND=ollama` and re-run ingestion so the index matches the embedding model.

## Configuration

Environment variables:

- `RAG_CORPUS_DIR`: default `pdfs`
- `RAG_INDEX_PATH`: default `.rag/index.json`
- `RAG_CHUNK_SIZE_CHARS`: default `1400`
- `RAG_CHUNK_OVERLAP_CHARS`: default `220`
- `RAG_TOP_K`: default `5`
- `RAG_EMBEDDING_BACKEND`: `hash` or `ollama`
- `RAG_GENERATION_BACKEND`: `extractive` or `ollama`
- `RAG_OLLAMA_BASE_URL`: default `http://localhost:11434`
- `RAG_OLLAMA_EMBEDDING_MODEL`: default `nomic-embed-text`
- `RAG_OLLAMA_GENERATION_MODEL`: default `llama3.1`

Legacy Docker variables from the previous app are also accepted where they map cleanly:
`PDF_FOLDER`, `VECTOR_DB_PATH`, `CHUNK_SIZE`, `CHUNK_OVERLAP`, `TOP_K`, `OLLAMA_BASE_URL`,
`OLLAMA_MODEL`, and `OLLAMA_EMBEDDING_MODEL`.

## Frontend

The active UI is `static/index.html` and is wired to `/health`, `/ingest`, `/ask`, and `/sources`.
The previous UI has been preserved as `static/legacy-index.html` for reference, but it targets the old API surface and is not the active app.

## Medical Safety

This project is for literature retrieval, research support, and education. It should not be used as a standalone diagnostic, treatment, or emergency decision system. Possible acute stroke symptoms require emergency medical services.
