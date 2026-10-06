from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from medical_rag import __version__
from medical_rag.config import Settings
from medical_rag.embeddings import list_ollama_models, ollama_model_name_matches
from medical_rag.errors import user_error
from medical_rag.evaluation import evaluate_rag, load_eval_suite
from medical_rag.memory import ConversationStore, prompt_history
from medical_rag.pipeline import StrokeRAG

logger = logging.getLogger(__name__)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    top_k: int | None = Field(default=None, ge=1, le=20)
    filters: dict[str, str] | None = None
    answer_mode: Literal["patient", "clinician"] | None = None


class IngestRequest(BaseModel):
    source_path: str | None = None
    force: bool = False
    resume: bool = True
    failed_only: bool = False
    ocr_scanned: bool = False
    pdf_workers: int | None = Field(default=None, ge=1, le=32)
    background: bool = False


class EvalRunRequest(BaseModel):
    top_k: int | None = Field(default=None, ge=1, le=20)
    answer_mode: Literal["patient", "clinician"] | None = None
    question_ids: list[str] | None = None
    include_answers: bool = False


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings.from_env()
    rag = StrokeRAG(app_settings)
    memory = ConversationStore(app_settings.index_path.parent / "conversations.sqlite3")
    conversation_lock = threading.Lock()
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
        version=__version__,
    )

    @app.middleware("http")
    async def mask_unexpected_errors(request: Request, call_next: Any) -> Any:
        try:
            return await call_next(request)
        except Exception:
            logger.exception("Unexpected failure handling %s", request.url.path)
            return JSONResponse(status_code=500, content={
                "detail": "Something went wrong while processing your request. Please try again in a moment."
            })

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={
            "detail": "Please check your question and selected options, then try again."
        })

    def request_error(exc: Exception, status: int, operation: str = "request") -> HTTPException:
        logger.exception("MedicalRAG %s failed", operation)
        return HTTPException(status_code=status, detail=user_error(exc, operation))

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
        except Exception as exc:
            logger.exception("Background document ingestion failed")
            with ingestion_lock:
                ingestion_status.update(
                    {
                        "running": False,
                        "finished_at": time.time(),
                        "last_error": user_error(exc, "ingest"),
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
        ollama_models = list_ollama_models(app_settings.ollama_base_url)
        ollama_embedding_model_available = any(
            ollama_model_name_matches(app_settings.ollama_embedding_model, model)
            for model in ollama_models
        )
        # The remote backend resolves its model name from the embedding service, so this can
        # fail when that service is down. Health must report that rather than return a 500.
        try:
            active_embedding_model: str | None = rag.embedding_model.name
            embedding_model_error: str | None = None
        except Exception:  # noqa: BLE001 - surface any backend failure in health
            active_embedding_model = None
            logger.exception("Embedding health check failed")
            embedding_model_error = "The embedding service is unavailable. Please try again later."
        # Likewise, the Qdrant backend has to ask the server whether the collection exists.
        try:
            index_exists: bool | None = rag.index_exists()
            vector_store_error: str | None = None
        except Exception:  # noqa: BLE001 - surface any backend failure in health
            index_exists = None
            logger.exception("Vector store health check failed")
            vector_store_error = "The document library is unavailable. Please try again later."
        return {
            "status": "ok",
            "index_exists": index_exists,
            "vector_store_error": vector_store_error,
            "index_path": str(app_settings.index_path),
            "vector_store_backend": app_settings.vector_store_backend,
            "qdrant_url": app_settings.qdrant_url
            if app_settings.vector_store_backend == "qdrant"
            else None,
            "qdrant_collection": app_settings.qdrant_collection
            if app_settings.vector_store_backend == "qdrant"
            else None,
            "corpus_dir": str(app_settings.corpus_dir),
            "embedding_backend": app_settings.embedding_backend,
            "active_embedding_model": active_embedding_model,
            "embedding_model_error": embedding_model_error,
            "fallback_embedding": rag.fallback_embedding_used(),
            "generation_backend": app_settings.generation_backend,
            "generation_model": _generation_model_name(app_settings),
            "ollama_available": bool(ollama_models),
            "ollama_models": ollama_models,
            "ollama_embedding_model": app_settings.ollama_embedding_model,
            "ollama_embedding_model_available": ollama_embedding_model_available,
            "api_base_url": app_settings.api_base_url,
            "api_key_configured": bool(app_settings.api_key),
            "api_generation_model": app_settings.api_generation_model,
            "api_embedding_model": app_settings.api_embedding_model,
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
            raise request_error(exc, 400, "ingest") from exc

    @app.get("/ingest/status")
    def ingest_status() -> dict[str, Any]:
        with ingestion_lock:
            return dict(ingestion_status)

    @app.get("/conversations/{conversation_id}")
    def conversation(conversation_id: str) -> dict[str, Any]:
        return {"turns": memory.history(conversation_id)}

    @app.delete("/conversations/{conversation_id}")
    def clear_conversation(conversation_id: str) -> dict[str, bool]:
        with conversation_lock:
            memory.clear(conversation_id)
        return {"cleared": True}

    @app.post("/ask")
    def ask(request: AskRequest) -> dict[str, Any]:
        try:
            with conversation_lock:
                history = (prompt_history(memory.context(request.conversation_id))
                           if request.conversation_id else [])
                payload = rag.ask(
                    question=request.question,
                    top_k=request.top_k,
                    filters=request.filters,
                    answer_mode=request.answer_mode,
                    history=history,
                ).to_dict()
                if request.conversation_id:
                    memory.append(request.conversation_id, payload)
                    payload["conversation_id"] = request.conversation_id
                return payload
        except FileNotFoundError as exc:
            raise request_error(exc, 409) from exc
        except (RuntimeError, ValueError) as exc:
            raise request_error(exc, 400) from exc

    @app.get("/sources")
    def sources() -> list[dict[str, object]]:
        try:
            return rag.sources()
        except FileNotFoundError as exc:
            raise request_error(exc, 409) from exc

    @app.get("/eval/questions")
    def eval_questions() -> dict[str, Any]:
        version, questions = load_eval_suite()
        return {
            "version": version,
            "questions": [question.to_dict() for question in questions],
        }

    @app.post("/eval/run")
    def eval_run(request: EvalRunRequest) -> dict[str, Any]:
        try:
            return evaluate_rag(
                rag,
                top_k=request.top_k,
                answer_mode=request.answer_mode,
                question_ids=request.question_ids,
                include_answers=request.include_answers,
            ).to_dict()
        except FileNotFoundError as exc:
            raise request_error(exc, 409) from exc
        except (RuntimeError, ValueError) as exc:
            raise request_error(exc, 400) from exc

    return app


app = create_app()


def _generation_model_name(settings: Settings) -> str:
    if settings.generation_backend == "ollama":
        return settings.ollama_generation_model
    if settings.generation_backend == "api":
        return f"api:{settings.api_generation_model}"
    return "extractive"
