from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from medical_rag.config import Settings
from medical_rag.pipeline import StrokeRAG


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    top_k: int | None = Field(default=None, ge=1, le=20)
    filters: dict[str, str] | None = None


class IngestRequest(BaseModel):
    source_path: str | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings.from_env()
    rag = StrokeRAG(app_settings)
    app = FastAPI(
        title="Stroke Medical RAG",
        description="Stroke-focused retrieval-augmented generation API.",
        version="0.1.0",
    )

    static_dir = app_settings.root_dir / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", response_model=None)
    def root() -> Any:
        index_path = static_dir / "index.html"
        if index_path.exists():
            return FileResponse(index_path)
        return {"service": "Stroke Medical RAG", "docs": "/docs"}

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "index_exists": rag.index_exists(),
            "index_path": str(app_settings.index_path),
            "corpus_dir": str(app_settings.corpus_dir),
            "embedding_backend": app_settings.embedding_backend,
            "generation_backend": app_settings.generation_backend,
        }

    @app.get("/ready")
    def ready(response: Response) -> dict[str, Any]:
        index_exists = rag.index_exists()
        if not index_exists:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "ok" if index_exists else "not_ready", "index_exists": index_exists}

    @app.post("/ingest")
    def ingest(request: IngestRequest) -> dict[str, Any]:
        try:
            source = Path(request.source_path).expanduser() if request.source_path else None
            return rag.ingest(source).to_dict()
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/ask")
    def ask(request: AskRequest) -> dict[str, Any]:
        try:
            return rag.ask(
                question=request.question,
                top_k=request.top_k,
                filters=request.filters,
            ).to_dict()
        except FileNotFoundError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/sources")
    def sources() -> list[dict[str, object]]:
        try:
            return rag.sources()
        except FileNotFoundError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return app


app = create_app()
