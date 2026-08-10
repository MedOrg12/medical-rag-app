# Changelog

All notable changes to this project are documented here.

This project follows Semantic Versioning for the application release number:

- `MAJOR`: incompatible API, index, or deployment changes.
- `MINOR`: new features or meaningful behavior improvements.
- `PATCH`: bug fixes, documentation updates, and compatible maintenance.

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

[0.1.0]: https://github.com/MoCode98/medical-rag-app/releases/tag/v0.1.0
