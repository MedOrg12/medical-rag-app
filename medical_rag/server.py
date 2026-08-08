from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
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
    force: bool = False
    resume: bool = True
    failed_only: bool = False
    ocr_scanned: bool = False
    pdf_workers: int | None = Field(default=None, ge=1, le=32)
    background: bool = False


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings.from_env()
    rag = StrokeRAG(app_settings)
    ingestion_executor = ThreadPoolExecutor(max_workers=1)
    ingestion_lock = threading.Lock()
    ingestion_status: dict[str, Any] = {
        "running": False,
        "started_at": None,
        "finished_at": None,
        "last_report": None,
        "last_error": None,
    }
    app = FastAPI(
        title="Stroke Medical RAG",
        description="Stroke-focused retrieval-augmented generation API.",
        version="0.1.0",
    )

    static_dir = app_settings.root_dir / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    def _run_background_ingestion(request: IngestRequest, source: Path | None) -> None:
        try:
            report = rag.ingest(
                source,
                force=request.force,
                resume=request.resume,
                failed_only=request.failed_only,
                ocr_scanned=request.ocr_scanned,
                pdf_workers=request.pdf_workers,
            ).to_dict()
            with ingestion_lock:
                ingestion_status.update(
                    {
                        "running": False,
                        "finished_at": time.time(),
                        "last_report": report,
                        "last_error": None,
                    }
                )
        except Exception as exc:  # noqa: BLE001 - preserve failure for status endpoint.
            with ingestion_lock:
                ingestion_status.update(
                    {
                        "running": False,
                        "finished_at": time.time(),
                        "last_error": str(exc),
                    }
                )

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

    @app.post("/ingest")
    def ingest(request: IngestRequest) -> dict[str, Any]:
        source = Path(request.source_path).expanduser() if request.source_path else None
        if request.background:
            with ingestion_lock:
                if ingestion_status["running"]:
                    raise HTTPException(status_code=409, detail="Ingestion is already running")
                ingestion_status.update(
                    {
                        "running": True,
                        "started_at": time.time(),
                        "finished_at": None,
                        "last_report": None,
                        "last_error": None,
                    }
                )
            ingestion_executor.submit(_run_background_ingestion, request, source)
            return {"accepted": True, "status": "/ingest/status"}

        try:
            return rag.ingest(
                source,
                force=request.force,
                resume=request.resume,
                failed_only=request.failed_only,
                ocr_scanned=request.ocr_scanned,
                pdf_workers=request.pdf_workers,
            ).to_dict()
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/ingest/status")
    def ingest_status() -> dict[str, Any]:
        with ingestion_lock:
            return dict(ingestion_status)

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
