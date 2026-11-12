from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from medical_rag import __version__
from medical_rag.auth import Authenticator, Principal
from medical_rag.config import Settings
from medical_rag.embeddings import list_ollama_models, ollama_model_name_matches
from medical_rag.evaluation import evaluate_rag, load_eval_suite
from medical_rag.logging_config import configure_logging, describe_exception
from medical_rag.pipeline import StrokeRAG

logger = logging.getLogger(__name__)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
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


def create_app(
    settings: Settings | None = None, authenticator: Authenticator | None = None
) -> FastAPI:
    configure_logging()
    app_settings = settings or Settings.from_env()
    rag = StrokeRAG(app_settings)
    auth = authenticator or Authenticator(app_settings)
    if auth.disabled:
        logger.warning(
            "RAG_AUTH_DISABLED is set: the clinician view and the developer workbench are open "
            "to everyone"
        )
    elif problem := auth.configuration_problem():
        logger.warning(
            "Sign-in is not configured (%s); the clinician view and the developer workbench "
            "will refuse requests until it is",
            problem,
        )
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

    def require_admin(request: Request) -> Principal:
        return auth.require_admin(request)

    admin_only = [Depends(require_admin)]

    static_dir = app_settings.root_dir / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    def _run_background_ingestion(request: IngestRequest, source: Path | None) -> None:
        logger.info("Background ingestion started (source=%s, force=%s)", source, request.force)
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
            logger.info("Background ingestion finished")
        except Exception as exc:  # noqa: BLE001 - preserve failure for status endpoint.
            logger.exception("Background ingestion failed (source=%s)", source)
            with ingestion_lock:
                ingestion_status.update(
                    {
                        "running": False,
                        "finished_at": time.time(),
                        "last_error": str(exc),
                    }
                )

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        # Starlette's default 500 body is plain text, which the UI cannot parse as JSON. The
        # exception can carry anything, so it stays out of the response; Starlette re-raises
        # it after this handler, so uvicorn still prints the traceback. Log one line here
        # that ties the failure to the request.
        logger.error(
            "Unhandled error on %s %s: %s",
            request.method,
            request.url.path,
            describe_exception(exc),
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error; see the server log for details."},
        )

    @app.get("/", response_model=None)
    def root() -> Any:
        index_path = static_dir / "index.html"
        if index_path.exists():
            return FileResponse(index_path)
        return {"service": "Stroke Medical RAG", "docs": "/docs"}

    @app.get("/clinician", response_model=None, include_in_schema=False)
    def clinician_view() -> FileResponse:
        # The same page as the patient view; patient.js switches to clinician mode by path
        # and asks the user to sign in. The /ask endpoint enforces the sign-in.
        index_path = static_dir / "index.html"
        if not index_path.exists():
            raise HTTPException(status_code=404, detail="Clinician view is not available")
        return FileResponse(index_path)

    # The page itself holds no data, so it is served to everyone; dev.js asks for an admin
    # sign-in, and every API endpoint it calls checks for an admin.
    @app.get("/dev", response_model=None, include_in_schema=False)
    def developer_view() -> FileResponse:
        developer_path = static_dir / "dev.html"
        if not developer_path.exists():
            raise HTTPException(status_code=404, detail="Developer view is not available")
        return FileResponse(developer_path)

    @app.get("/auth/config")
    def auth_config() -> dict[str, Any]:
        return auth.client_config()

    @app.get("/auth/me")
    def auth_me(request: Request) -> dict[str, Any]:
        principal = auth.principal(request)
        if principal is None:
            return {"signed_in": False, "admin": False}
        return {"signed_in": True, "admin": auth.user_is_admin(principal.user_id)}

    @app.get("/status")
    def patient_status() -> dict[str, bool]:
        return {"ready": rag.index_exists()}

    @app.get("/health", dependencies=admin_only)
    def health() -> dict[str, Any]:
        # Polled by container healthchecks and the UI; an absent Ollama is not worth a warning
        # each time, and the startup auto-fallback already logged the reason once.
        ollama_models = list_ollama_models(app_settings.ollama_base_url, log_level=logging.DEBUG)
        ollama_embedding_model_available = any(
            ollama_model_name_matches(app_settings.ollama_embedding_model, model)
            for model in ollama_models
        )
        # The remote backend resolves its model name from the embedding service, so this can
        # fail when that service is down. Health must report that rather than return a 500.
        try:
            active_embedding_model: str | None = rag.embedding_model.name
            embedding_model_error: str | None = None
        except Exception as exc:  # noqa: BLE001 - surface any backend failure in health
            logger.warning(
                "Health check: embedding backend unavailable: %s", describe_exception(exc)
            )
            active_embedding_model = None
            embedding_model_error = str(exc)
        # Likewise, the Qdrant backend has to ask the server whether the collection exists.
        try:
            index_exists: bool | None = rag.index_exists()
            vector_store_error: str | None = None
        except Exception as exc:  # noqa: BLE001 - surface any backend failure in health
            logger.warning("Health check: vector store unavailable: %s", describe_exception(exc))
            index_exists = None
            vector_store_error = str(exc)
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
            "api_max_output_tokens": app_settings.api_max_output_tokens,
            "api_reasoning_effort": app_settings.api_reasoning_effort,
            "api_max_retries": app_settings.api_max_retries,
            "request_timeout_seconds": app_settings.request_timeout_seconds,
        }

    @app.get("/ready")
    def ready(response: Response) -> dict[str, Any]:
        # Container healthchecks and deploy tooling treat any non-2xx as not ready. A vector
        # store that cannot be reached is reported as not ready rather than as a 500.
        try:
            index_exists: bool | None = rag.index_exists()
        except Exception as exc:  # noqa: BLE001 - any backend failure means the app is not ready
            logger.warning("Readiness check: vector store unavailable: %s", describe_exception(exc))
            index_exists = None
        if not index_exists:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "ok" if index_exists else "not_ready", "index_exists": index_exists}

    @app.post("/ingest", dependencies=admin_only)
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
            logger.warning(
                "Ingestion request failed (source=%s): %s", source, describe_exception(exc)
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/ingest/status", dependencies=admin_only)
    def ingest_status() -> dict[str, Any]:
        with ingestion_lock:
            return dict(ingestion_status)

    @app.post("/ask")
    def ask(request: AskRequest, http_request: Request) -> dict[str, Any]:
        # The patient view is public; clinician answers need a signed-in user. Check the mode
        # the pipeline will actually use, since RAG_ANSWER_MODE can default it to clinician.
        mode = (request.answer_mode or app_settings.answer_mode).strip().lower()
        if mode != "patient":
            auth.require_user(http_request)
        try:
            return rag.ask(
                question=request.question,
                top_k=request.top_k,
                filters=request.filters,
                answer_mode=request.answer_mode,
            ).to_dict()
        except FileNotFoundError as exc:
            logger.warning("Ask request rejected: index not available: %s", describe_exception(exc))
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (RuntimeError, ValueError) as exc:
            logger.warning(
                "Ask request failed (mode=%s, top_k=%s): %s",
                request.answer_mode,
                request.top_k,
                describe_exception(exc),
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/sources", dependencies=admin_only)
    def sources() -> list[dict[str, object]]:
        try:
            return rag.sources()
        except FileNotFoundError as exc:
            logger.warning(
                "Sources request rejected: index not available: %s", describe_exception(exc)
            )
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - qdrant-client raises several transport types
            logger.warning(
                "Sources request failed: could not read the vector store: %s",
                describe_exception(exc),
            )
            raise HTTPException(
                status_code=503, detail=f"Could not read sources from the vector store: {exc}"
            ) from exc

    @app.get("/eval/questions", dependencies=admin_only)
    def eval_questions() -> dict[str, Any]:
        version, questions = load_eval_suite()
        return {
            "version": version,
            "questions": [question.to_dict() for question in questions],
        }

    @app.post("/eval/run", dependencies=admin_only)
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
            logger.warning("Eval run rejected: index not available: %s", describe_exception(exc))
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (RuntimeError, ValueError) as exc:
            logger.warning("Eval run failed: %s", describe_exception(exc))
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app


app = create_app()


def _generation_model_name(settings: Settings) -> str:
    if settings.generation_backend == "ollama":
        return settings.ollama_generation_model
    if settings.generation_backend == "api":
        return f"api:{settings.api_generation_model}"
    return "extractive"
