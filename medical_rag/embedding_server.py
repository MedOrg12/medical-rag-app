from __future__ import annotations

import sys
import threading
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from medical_rag.config import Settings
from medical_rag.embeddings import (
    EmbeddingModel,
    SentenceTransformersEmbeddingModel,
)


class EmbedRequest(BaseModel):
    texts: list[str]
    model_name: str | None = None


def create_app(settings: Settings | None = None, model: EmbeddingModel | None = None) -> FastAPI:
    app_settings = settings or Settings.from_env()
    embedding_model = model or SentenceTransformersEmbeddingModel(
        model_name=app_settings.sentence_transformers_model,
        device=app_settings.sentence_transformers_device,
        batch_size=app_settings.sentence_transformers_batch_size,
    )
    inference_semaphore = threading.Semaphore(1)
    dimensions: int | None = None
    device = "unknown"

    def _warm_model() -> None:
        nonlocal dimensions, device
        if dimensions is not None:
            return
        vectors = embedding_model.embed(["warmup"])
        if not vectors:
            raise RuntimeError("Embedding model warmup returned no vectors")
        dimensions = len(vectors[0])
        loaded_model = getattr(embedding_model, "_model", None)
        loaded_device = getattr(loaded_model, "device", None)
        if loaded_device is None:
            loaded_device = getattr(embedding_model, "device", None)
        device = str(loaded_device) if loaded_device is not None else "unknown"

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        _warm_model()
        yield

    app = FastAPI(title="Medical RAG Embedding Service", lifespan=lifespan)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail and "message" in detail:
            error = detail
        else:
            error = {"code": "http_error", "message": str(detail)}
        return JSONResponse(status_code=exc.status_code, content={"error": error})

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": str(exc),
                }
            },
        )

    def _raise_error(status_code: int, code: str, message: str) -> None:
        raise HTTPException(status_code=status_code, detail={"code": code, "message": message})

    def _log_embed_request(text_count: int, latency_ms: float) -> None:
        print(
            f"embedding request texts={text_count} latency_ms={latency_ms:.1f}",
            file=sys.stderr,
        )

    # Plain (non-async) handlers run in FastAPI's threadpool, so model inference never
    # blocks the event loop; the semaphore keeps inference itself single-file.
    @app.get("/health")
    def health() -> dict[str, Any]:
        _warm_model()
        return {
            "status": "ok",
            "model_name": embedding_model.name,
            "device": device,
            "dimensions": dimensions,
            "max_batch_size": app_settings.embedding_service_max_batch_size,
        }

    @app.post("/embed")
    def embed(
        request: EmbedRequest, authorization: str | None = Header(default=None)
    ) -> dict[str, Any]:
        if app_settings.embedding_service_token is not None:
            expected = f"Bearer {app_settings.embedding_service_token}"
            if authorization != expected:
                _raise_error(401, "unauthorized", "Missing or invalid bearer token")

        model_name = embedding_model.name
        if request.model_name is not None and request.model_name != model_name:
            _raise_error(
                409,
                "model_mismatch",
                f"Requested model {request.model_name!r}, but service uses {model_name!r}",
            )
        if len(request.texts) > app_settings.embedding_service_max_batch_size:
            _raise_error(
                413,
                "batch_too_large",
                "Embedding request exceeds "
                f"max batch size {app_settings.embedding_service_max_batch_size}",
            )
        if any(len(text) > app_settings.embedding_service_max_text_chars for text in request.texts):
            _raise_error(
                413,
                "text_too_large",
                "Embedding request contains text longer than "
                f"{app_settings.embedding_service_max_text_chars} characters",
            )

        _warm_model()
        assert dimensions is not None
        started = time.perf_counter()
        if not request.texts:
            _log_embed_request(0, (time.perf_counter() - started) * 1000)
            return {"model_name": model_name, "dimensions": dimensions, "embeddings": []}

        with inference_semaphore:
            embeddings = embedding_model.embed(request.texts)
        latency_ms = (time.perf_counter() - started) * 1000
        _log_embed_request(len(request.texts), latency_ms)
        return {"model_name": model_name, "dimensions": dimensions, "embeddings": embeddings}

    return app


app = create_app()
