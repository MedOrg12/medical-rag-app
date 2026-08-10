# Release Process

This document describes how to cut application releases for Stroke Medical RAG.

## Versioning

Use Semantic Versioning:

- `MAJOR`: incompatible API, index format, corpus contract, or deployment changes.
- `MINOR`: new features, retrieval/generation improvements, new supported workflows, or compatible schema additions.
- `PATCH`: compatible bug fixes, documentation changes, small UX fixes, and dependency maintenance.

The app version is declared in `pyproject.toml`:

```toml
[project]
version = "0.1.0"
```

Git tags must use the matching `v` prefix:

```bash
v0.1.0
v0.2.0
v0.2.1
```

## What To Version

Version these as part of the application release:

- Python source under `medical_rag/`
- Browser UI under `static/`
- Docker files
- Tests and benchmark scripts
- Documentation
- Small curated corpus metadata such as `pdfs/SOURCES.md`

Do not version generated runtime artifacts:

- `.rag/`
- `.rag_*/`
- `.rag_benchmark*/`
- Docker volumes
- virtual environments
- local logs
- local Ollama model data

For large corpora, prefer an external dataset/versioning system rather than committing thousands of PDFs directly to Git.

## Release Checklist

1. Confirm the worktree only contains intended release changes.

```bash
git status --short
```

2. Update `pyproject.toml`.

```toml
version = "x.y.z"
```

3. Update `CHANGELOG.md`.

Add a new section:

```markdown
## [x.y.z] - YYYY-MM-DD
```

4. Run local validation.

```bash
python3 -m pytest -m "not eval"
docker compose config
docker compose build medical-rag
```

Run the live eval suite only when the server is running with an ingested index:

```bash
python3 -m pytest -m eval
```

5. Commit the release changes.

```bash
git add pyproject.toml CHANGELOG.md docs/RELEASE_PROCESS.md medical_rag
git commit -m "chore: release vx.y.z"
```

6. Create an annotated tag.

```bash
git tag -a vx.y.z -m "Release vx.y.z"
```

7. Push the commit and tag.

```bash
git push origin main
git push origin vx.y.z
```

8. Create a GitHub Release from the tag.

Use the matching `CHANGELOG.md` section as the release notes.

## Rollback

If a release tag was created locally but not pushed:

```bash
git tag -d vx.y.z
```

If a tag was pushed and must be corrected, create a new patch release instead of rewriting published history.

## RAG Compatibility Notes

Some changes require re-ingestion even when the application version only changes by minor or patch:

- `PARSER_VERSION` changes in `medical_rag/ingestion.py`
- vector store `SCHEMA_VERSION` changes in `medical_rag/vector_store.py`
- chunk size or overlap changes
- embedding backend/model changes
- corpus source changes

The ingestion manifest and vector index already track parser, chunking, and embedding details. When those change, rebuild the index before evaluating answer quality.
