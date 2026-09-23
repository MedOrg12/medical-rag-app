# Changelog

All notable changes to this project are documented here.

This project follows Semantic Versioning for the application release number:

- `MAJOR`: incompatible API, index, or deployment changes.
- `MINOR`: new features or meaningful behavior improvements.
- `PATCH`: bug fixes, documentation updates, and compatible maintenance.

## [Unreleased]

### Added

- Browser evaluation dashboard for running the RAG eval suite from the UI.
- Redesigned frontend workbench with corpus controls, source search, chat history, citation evidence, health indicators, and integrated eval controls.
- Opt-in OpenAI-compatible API backends for generation and embeddings via `RAG_GENERATION_BACKEND=api` and `RAG_EMBEDDING_BACKEND=api`.
- `/eval/questions` and `/eval/run` API endpoints for evaluation metadata and execution.
- Package-level eval suite data under `medical_rag/eval_data.json`.
- Health metadata for active embedding model, Ollama/API availability, and embedding fallback state.
- Qdrant vector store backend (`RAG_VECTOR_STORE=qdrant`) with idempotent upserts into an existing collection, stale-point cleanup, and vector-config validation.
- Slurm ingestion job (`scripts/slurm_ingest_qdrant.sbatch`) that embeds on a GPU node with sentence-transformers and writes to Qdrant over an SSH tunnel, with GPU and timing diagnostics.
- Standalone GPU embedding service (`embedder` compose profile) and a `remote` embedding backend so the API host never loads torch.
- `RAG_QDRANT_TIMEOUT_SECONDS`, `QDRANT_DATA_DIR`, and `QDRANT_WAL_CAPACITY_MB` for slow-disk Qdrant hosts.

### Changed

- Docker and `.env.example` now default `RAG_EMBEDDING_BACKEND` to `auto`.
- Auto embeddings now use Ollama only when the configured embedding model is installed; otherwise they fall back to hash embeddings.
- Eval pass/fail now requires in-scope answers to include enough expected answer terms, rather than passing on citation matches alone.
- Corpus discovery now excludes `SOURCES.md` planning/checklist files so they do not appear as medical citations.
- Live pytest evals now require `RUN_LIVE_EVAL=1`, while eval data validation still runs normally.
- `RAG_QDRANT_RECREATE_COLLECTION` now defaults to `false`; ingestion writes into the existing collection.
- `/health` reports `active_embedding_model` as `null` with an `embedding_model_error` when the embedding service is unreachable, instead of failing.
- `RAG_AUTO_INGEST_ON_STARTUP` is configurable in compose for query-only hosts.

## [0.1.0] - 2026-08-10

Initial release of the refactored Stroke Medical RAG application.

### Added

- FastAPI backend with `/health`, `/ingest`, `/ingest/status`, `/ask`, and `/sources`.
- Minimal browser UI for ingestion, source inspection, patient/clinician answer modes, and questions.
- CLI entry points for corpus ingestion and asking questions.
- Stroke-focused RAG pipeline with page-aware chunking, stable chunk IDs, hybrid retrieval, lexical reranking, and citation metadata.
- Improved PDF parsing with block-aware extraction, column handling, header/footer cleanup, table text handling, and scanned-page detection.
- Incremental ingestion for larger PDF collections using a SQLite manifest, extracted-text cache, and embedding cache.
- Hash-based local embeddings for zero-service startup.
- Optional Ollama generation and Ollama embeddings.
- Patient and clinician answer modes.
- Docker and Docker Compose support, including optional Ollama service profile.
- Ingestion benchmark script and regression tests for chunking, parsing, ingestion, retrieval, generation fallback, and vector store behavior.

### Changed

- Archived previous unused implementation under `old_code/`.
- Docker startup reuses existing indexes when compatible and rebuilds when the embedding model changes.
- Docker Ollama configuration supports host Ollama through `host.docker.internal` or a Compose-managed Ollama service.

### Safety

- Answers include a literature-review and clinical-education safety notice.
- Generation prompts instruct the model to use retrieved passages only and to avoid unsupported clinical claims.

### Known Limitations

- The default hash embedding backend is convenient but weaker than semantic embeddings for nuanced medical questions.
- The JSON vector index works for the current baseline, but a real vector database will be needed for larger production corpora.
- OCR is not yet implemented for scanned PDFs; scanned pages are detected and reported.
- Medical answer quality is limited by the indexed PDF corpus.

[Unreleased]: https://github.com/MedOrg12/medical-rag-app/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/MedOrg12/medical-rag-app/releases/tag/v0.1.0
