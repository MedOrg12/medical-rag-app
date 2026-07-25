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

## Production deployment

Production deployment uses an outbound-only image pull plus an authenticated HTTPS trigger:

1. GitHub Actions tests the application.
2. A successful push to `main` publishes an immutable image to GHCR.
3. The production job obtains a short-lived GitHub OIDC identity and sends the image digest to
   `POST /internal/deploy`.
4. An unprivileged admission service validates the identity and queues the request.
5. A separate systemd worker validates the identity again, verifies that the image's
   `org.opencontainers.image.revision` label matches the authorized commit, deploys it, checks
   `/ready`, and rolls back to the previous digest on failure.

No public SSH access or inbound deploy-agent port is required. Nginx exposes only the controlled
HTTPS routes; the API, deploy agent, and Docker application port bind to loopback.

Deployment files:

- `compose.production.yaml`
- `deploy/medical-rag-app.conf`
- `deploy/deploy-agent.env.example`
- `deploy/systemd/`
- `.github/workflows/ci-cd.yml`

### One-time VM setup

The examples assume the checked-out deployment source is `/opt/medical-rag/source` and production
state is under `/opt/medical-rag`. Run the administrative commands through the site's approved
privilege-elevation process.

```bash
useradd --system --home /nonexistent --shell /usr/sbin/nologin medical-rag-deploy
install -d -o root -g root -m 0755 /opt/medical-rag/source /opt/medical-rag/corpus
install -d -o root -g medical-rag-deploy -m 0750 /etc/medical-rag
install -d -o root -g medical-rag-deploy -m 0750 /etc/medical-rag/docker

python3 -m venv /opt/medical-rag/deploy-venv
/opt/medical-rag/deploy-venv/bin/pip install -r requirements-deploy.txt

install -o root -g medical-rag-deploy -m 0640 \
  deploy/deploy-agent.env.example /etc/medical-rag/deploy-agent.env
install -o root -g root -m 0644 compose.production.yaml /opt/medical-rag/compose.production.yaml
install -o root -g root -m 0644 deploy/systemd/*.service deploy/systemd/*.path \
  /etc/systemd/system/
install -o root -g root -m 0644 deploy/medical-rag-app.conf \
  /etc/nginx/conf.d/medical-rag-app.conf
```

Copy the `deploy_agent` package into `/opt/medical-rag/source`, then edit
`/etc/medical-rag/deploy-agent.env`. `DEPLOY_GITHUB_REPOSITORY_ID` must be the repository's numeric,
immutable GitHub ID. Update the temporary hostname, certificate paths, OIDC audience, and GitHub
`DEPLOY_URL` variable together when the domain changes.

Authenticate the VM to GHCR with a read-only package token using the worker's isolated Docker
configuration:

```bash
DOCKER_CONFIG=/etc/medical-rag/docker docker login ghcr.io
```

Validate and start the services:

```bash
nginx -t
systemctl daemon-reload
systemctl enable --now medical-rag-deploy-api.service
systemctl enable --now medical-rag-deploy-worker.path
systemctl reload nginx
```

In the GitHub `production` environment, configure:

- Variable `DEPLOY_URL`: `https://web1-rag.efeyzee.dev/internal/deploy`
- Variable `APPLICATION_URL`: the public application URL
- Deployment branch restriction: `main`
- A required reviewer, if supported by the repository plan

The supplied domain is intentionally treated as temporary. The permanent Nginx filename remains
`medical-rag-app.conf`.
