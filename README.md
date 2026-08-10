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

## Versioning

The current application version is `0.1.0`. See `CHANGELOG.md` for release notes and
`docs/RELEASE_PROCESS.md` for the release checklist.

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

To run with Ollama generation using the Ollama app already running on your Mac:

```bash
open -a Ollama
curl http://localhost:11434/api/tags

RAG_GENERATION_BACKEND=ollama \
RAG_EMBEDDING_BACKEND=hash \
RAG_OLLAMA_BASE_URL=http://host.docker.internal:11434 \
docker compose up -d --build medical-rag
```

Inside Docker, `localhost` means the app container, not your Mac. Use
`http://host.docker.internal:11434` when the Ollama desktop app is running on the host.

To run Ollama as a Docker Compose service instead:

```bash
docker compose --profile ollama up -d ollama
docker exec -it stroke-medical-rag-ollama ollama pull llama3.1

RAG_GENERATION_BACKEND=ollama \
RAG_EMBEDDING_BACKEND=hash \
RAG_OLLAMA_BASE_URL=http://ollama:11434 \
docker compose --profile ollama up -d --build medical-rag
```

For semantic Ollama embeddings, also pull the embedding model and rebuild the index:

```bash
docker exec -it stroke-medical-rag-ollama ollama pull nomic-embed-text

RAG_GENERATION_BACKEND=ollama \
RAG_EMBEDDING_BACKEND=ollama \
RAG_OLLAMA_BASE_URL=http://ollama:11434 \
RAG_FORCE_REINGEST=true \
docker compose --profile ollama up -d --build medical-rag
```

The default Docker path still works without Ollama by using local hashing retrieval and extractive answers.

## Large Corpus Ingestion

The ingestion pipeline is designed to handle larger corpora without reprocessing every PDF on every run. It keeps a SQLite manifest, an extracted-text cache, and an embedding cache under `.rag/`.

```bash
python -m medical_rag.cli ingest --source pdfs
```

Useful flags:

```bash
python -m medical_rag.cli ingest --source pdfs --pdf-workers 4
python -m medical_rag.cli ingest --source pdfs --failed-only
python -m medical_rag.cli ingest --source pdfs --force
python -m medical_rag.cli ingest --source pdfs --no-resume
```

What this does:

- Skips the whole run quickly when the corpus and index are unchanged.
- Tracks file status in `.rag/manifest.sqlite`.
- Caches extracted text in `.rag/extracted/`.
- Caches embeddings in `.rag/embedding_cache.json`.
- Deduplicates identical files by SHA-256.
- Records failed files so they can be retried with `--failed-only`.
- Detects scanned PDF pages and records them without running slow OCR by default.
- Reports per-stage timings in the ingestion response.

The API also supports background ingestion:

```bash
curl -X POST http://127.0.0.1:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{"source_path":"pdfs","background":true,"pdf_workers":4}'

curl http://127.0.0.1:8000/ingest/status
```

Tuning knobs:

- `RAG_PDF_WORKERS`: parallel PDF extraction workers. Start with `2` to `4`.
- `RAG_EMBED_BATCH_SIZE`: embedding batch size for cache misses. Start with `64`.
- `RAG_MANIFEST_PATH`: manifest SQLite path.
- `RAG_EXTRACTION_CACHE_DIR`: extracted text cache directory.
- `RAG_EMBEDDING_CACHE_PATH`: embedding cache path.

Keep embedding workers conservative with local Ollama. PDF parsing can be parallelized, but local model embedding usually benefits more from batching than from high concurrency.

## API

```bash
curl -X POST http://127.0.0.1:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{"source_path":"pdfs"}'

curl -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"What does the indexed literature say about stroke rehabilitation?"}'
```

## Ollama Generation

Default retrieval uses the built-in hashing vectorizer and default answers are extractive. Extractive mode cites retrieved passages, but it does not behave like a full chatbot. Use Ollama generation for synthesized responses grounded in the retrieved PDF chunks.

Install Ollama for macOS from the official download page:

https://docs.ollama.com/macos

After installing, start Ollama:

```bash
open -a Ollama
```

Verify that the local Ollama server is running:

```bash
curl http://localhost:11434/api/tags
ollama list
```

Pull the generation model:

```bash
ollama pull llama3.1
```

Then run the app with Ollama generation enabled:

```bash
export RAG_GENERATION_BACKEND=ollama
export RAG_OLLAMA_BASE_URL=http://localhost:11434
export RAG_OLLAMA_GENERATION_MODEL=llama3.1
python app.py
```

You can also use the CLI in Ollama mode:

```bash
export RAG_GENERATION_BACKEND=ollama
export RAG_OLLAMA_BASE_URL=http://localhost:11434
export RAG_OLLAMA_GENERATION_MODEL=llama3.1
python -m medical_rag.cli ask "What does SPAN-100 estimate?"
```

If you see `Generation backend was unavailable, so this answer uses extractive retrieval`, the app tried Ollama and fell back because generation failed. Check that `curl http://localhost:11434/api/tags` works, that `ollama list` includes `llama3.1:latest`, and that the app was restarted after setting the environment variables. The fallback message includes a `Backend error:` line with the exact failure.

To use Ollama embeddings, set `RAG_EMBEDDING_BACKEND=ollama` and re-run ingestion so the index matches the embedding model.

## Answer Modes

The app supports two answer styles:

- `patient`: plain language, practical, and concise. This is the default.
- `clinician`: more technical and guideline-aware, with clinical caveats when the retrieved passages support them.

The browser UI has a Patient/Clinician dropdown for each question. The API accepts `answer_mode`:

```bash
curl -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"What is dysphagia after stroke?","answer_mode":"clinician"}'
```

The CLI supports the same setting:

```bash
python -m medical_rag.cli ask "What is dysphagia after stroke?" --mode clinician
```

Set a global default with:

```bash
export RAG_ANSWER_MODE=clinician
```

## Configuration

Environment variables:

- `RAG_CORPUS_DIR`: default `pdfs`
- `RAG_INDEX_PATH`: default `.rag/index.json`
- `RAG_CHUNK_SIZE_CHARS`: default `1400`
- `RAG_CHUNK_OVERLAP_CHARS`: default `220`
- `RAG_TOP_K`: default `5`
- `RAG_PDF_WORKERS`: default `1`
- `RAG_EMBED_BATCH_SIZE`: default `64`
- `RAG_MANIFEST_PATH`: default `.rag/manifest.sqlite`
- `RAG_EXTRACTION_CACHE_DIR`: default `.rag/extracted`
- `RAG_EMBEDDING_CACHE_PATH`: default `.rag/embedding_cache.json`
- `RAG_EMBEDDING_BACKEND`: `hash` or `ollama`
- `RAG_GENERATION_BACKEND`: `extractive` or `ollama`
- `RAG_ANSWER_MODE`: `patient` or `clinician`
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

## Corpus Coverage

Answer quality is directly tied to what has been indexed. The system can only cite evidence that exists in the `pdfs/` folder.

### Adding new PDFs

1. Copy PDF files into `pdfs/`
2. Delete the stale index:
   ```bash
   rm -f .rag/index.json .rag/embedding_cache.json
   ```
3. Restart and re-ingest via the UI or `POST /ingest`

### Diet & nutrition coverage

The default corpus covers stroke systems of care, clinical trials, rehabilitation, and prevention guidelines. It contains limited diet and nutrition content. To improve answers for questions like *"What should I eat after a stroke?"*, download the sources listed in `pdfs/SOURCES.md` and re-ingest.

### Coverage gaps

If the system gives vague or unhelpful answers on a topic, the most likely cause is that no relevant source has been indexed. Add a credible PDF on that topic and re-ingest.

### Source quality preferences

Prefer:
- Clinical practice guidelines (AHA/ASA, Stroke Foundation, SIGN, ESPEN)
- Peer-reviewed systematic reviews and meta-analyses
- Public health / hospital patient education materials from named institutions

Avoid:
- Blog posts, news articles, or commercial health websites
- Sources without named authorship or institutional affiliation

## Evaluation

The eval suite provides a repeatable way to check retrieval quality, citation relevance, and refusal correctness.

### Prerequisites

The server must be running and the index must be built before running evals:

```bash
source venv/bin/activate
python app.py &
# Click Ingest in the UI, or:
curl -s -X POST http://localhost:8000/ingest -H "Content-Type: application/json" -d '{}'
```

### Run the CLI runner

```bash
# Default: hits http://localhost:8000
python tests/run_eval.py

# Custom server URL or data file
python tests/run_eval.py --url http://localhost:8000 --data tests/eval_data.json
```

### Run via pytest

```bash
# Run eval tests (requires running server)
pytest tests/test_eval_suite.py -m eval -v

# Skip eval tests (CI without a running server)
pytest -m "not eval"
```

### Metrics

| Metric | Description | Pass threshold |
|--------|-------------|----------------|
| Retrieval hit rate | Fraction of in-scope questions where ≥1 citation source filename matches expected topic | ≥ 5/6 |
| Citation relevance | Fraction of citations whose excerpt contains an expected answer term | ≥ 0.60 |
| Refusal correctness | Out-of-scope questions where the system returns no confident citation | 1/1 |

### Adding new eval questions

Edit `tests/eval_data.json`. Each entry needs:
- `id` — unique string
- `question` — the question text
- `expected_source_hints` — keywords expected in citation source filenames
- `expected_answer_terms` — keywords expected in citation excerpts
- `should_refuse` — `true` for out-of-scope questions

## Switching Embedding Backends

The `RAG_EMBEDDING_BACKEND` setting controls how chunks are embedded:

| Value | Behaviour |
|-------|-----------|
| `auto` (default) | Probes Ollama at startup; uses `ollama` if available, falls back to `hash` |
| `ollama` | Always use Ollama semantic embeddings (requires Ollama running) |
| `hash` | Bag-of-words hashing — fast, no network, non-semantic |

**Important:** Changing the embedding backend invalidates the existing index. Delete both cache files before re-ingesting:

```bash
rm -f .rag/index.json .rag/embedding_cache.json
source venv/bin/activate
python app.py
# Then click Ingest in the UI or POST /ingest
```

The `RAG_HYBRID_ALPHA`, `RAG_MIN_RELEVANCE_SCORE`, and `RAG_RERANKER_BACKEND` settings control retrieval quality:

- `RAG_HYBRID_ALPHA=0.5` — blend weight for hybrid vector+BM25 search (RRF fusion)
- `RAG_MIN_RELEVANCE_SCORE=0.0` — filter out chunks below this score before generation
- `RAG_RERANKER_BACKEND=lexical` — post-retrieval reranker (`lexical` or `none`)
