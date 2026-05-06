"""
Query API endpoints for RAG queries.
"""

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address

from src import runtime_settings as rt
from src.config import settings
from src.conversational_rag import ConversationalRAG
from src.logging_config import get_logger
from src.metrics import get_metrics
from src.validation import (
    ValidationError,
    validate_model_name,
    validate_query,
    validate_temperature,
    validate_top_k,
)
from src.vector_db import VectorDatabase, get_vector_db

router = APIRouter()
logger = get_logger()

# Initialize limiter for this router
limiter = Limiter(key_func=get_remote_address)

# Session-based ConversationalRAG instances
_sessions: dict[str, dict[str, Any]] = {}
MAX_SESSIONS = 50
SESSION_TTL = 3600 * 4  # 4 hours


def _cleanup_sessions() -> None:
    """Remove expired sessions."""
    now = time.time()
    expired = [sid for sid, s in _sessions.items() if now - s["last_used"] > SESSION_TTL]
    for sid in expired:
        del _sessions[sid]
        logger.info(f"Expired session: {sid}")


def get_rag(session_id: str = "default") -> ConversationalRAG:
    """Get or create a ConversationalRAG instance for the given session."""
    _cleanup_sessions()

    if session_id in _sessions:
        _sessions[session_id]["last_used"] = time.time()
        return _sessions[session_id]["rag"]

    try:
        vector_db = get_vector_db()
        stats = vector_db.get_collection_stats()

        if stats["total_chunks"] == 0:
            raise HTTPException(
                status_code=400,
                detail="Vector database is empty. Please ingest documents first."
            )

        # Enforce max sessions
        if len(_sessions) >= MAX_SESSIONS:
            oldest = min(_sessions, key=lambda k: _sessions[k]["last_used"])
            del _sessions[oldest]
            logger.info(f"Evicted oldest session: {oldest}")

        # Apply runtime overrides from the Settings tab so model/temperature
        # changes take effect immediately on the next session.
        rag = ConversationalRAG(
            vector_db=vector_db,
            model=rt.get("ollama_model"),
            temperature=rt.get("temperature"),
            max_tokens=rt.get("max_tokens"),
        )
        _sessions[session_id] = {"rag": rag, "last_used": time.time()}
        logger.info(f"Created session '{session_id}' with {stats['total_chunks']} chunks")
        return rag

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to initialize RAG: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to initialize RAG: {str(e)}")


class QueryRequest(BaseModel):
    """Request model for query endpoint."""
    question: str
    top_k: int = 5
    model: str | None = None
    temperature: float | None = None
    return_context: bool = False
    session_id: str = "default"


class QueryResponse(BaseModel):
    """Response model for query endpoint."""
    question: str
    answer: str
    sources: list[dict[str, Any]]
    context_chunks: list[str] | None = None
    model_used: str
    query_time: float


@router.post("/query", response_model=QueryResponse)
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def query_rag(request: Request, query_request: QueryRequest) -> QueryResponse:
    """
    Submit a query to the RAG system with conversation memory.

    Args:
        query_request: Query request with question, parameters, and session_id

    Returns:
        Query response with answer and sources
    """
    metrics = get_metrics()

    try:
        # Validate all inputs
        question = validate_query(query_request.question)
        top_k = validate_top_k(query_request.top_k, max_value=settings.top_k_results * 2)

        # Get session-specific RAG instance
        rag = get_rag(query_request.session_id)

        # Override model/temperature if specified (with validation)
        if query_request.model:
            rag.model = validate_model_name(query_request.model)
        if query_request.temperature is not None:
            rag.temperature = validate_temperature(query_request.temperature)

        # Execute query (ConversationalRAG automatically uses conversation memory)
        metrics.start_timer("api_query")
        response = rag.query(
            question=question,
            top_k=top_k,
            return_context=query_request.return_context
        )
        query_time = metrics.stop_timer("api_query")

        logger.info(f"Query processed in {query_time:.2f}s (session={query_request.session_id}): {question[:50]}...")

        return QueryResponse(
            question=response.question,
            answer=response.answer,
            sources=response.sources,
            context_chunks=response.context_chunks if query_request.return_context else None,
            model_used=response.model_used,
            query_time=query_time
        )

    except ValidationError as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        logger.error(f"Query error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models")
async def get_available_models() -> dict[str, Any]:
    """
    Get list of available Ollama models.

    Returns:
        Dictionary with available models
    """
    try:
        import requests
        response = requests.get(f"{settings.ollama_base_url}/api/tags", timeout=settings.api_request_timeout)
        response.raise_for_status()
        models = response.json().get("models", [])

        return {
            "success": True,
            "models": [m["name"] for m in models],
            "default": settings.ollama_model
        }

    except Exception as e:
        logger.error(f"Failed to fetch models: {e}")
        return {
            "success": False,
            "models": [settings.ollama_model],
            "default": settings.ollama_model,
            "error": "Could not connect to Ollama"
        }


class PullModelRequest(BaseModel):
    """Request model for pulling a new Ollama model."""
    model: str


@router.post("/models/pull")
async def pull_model(body: PullModelRequest) -> dict[str, Any]:
    """
    Pull a new model into the local Ollama instance. Blocks until done.

    Args:
        body: Request with model name (e.g. "llama3.2:latest")

    Returns:
        Status message indicating success or failure.
    """
    try:
        model_name = validate_model_name(body.model)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        import requests
        # Stream the pull so the connection stays alive on slow networks.
        with requests.post(
            f"{settings.ollama_base_url}/api/pull",
            json={"name": model_name, "stream": True},
            stream=True,
            timeout=900,  # 15 min ceiling for large models
        ) as resp:
            resp.raise_for_status()
            last_status = ""
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    import json as _json
                    payload = _json.loads(line)
                    last_status = payload.get("status", last_status)
                    if payload.get("error"):
                        raise HTTPException(status_code=502, detail=payload["error"])
                except ValueError:
                    continue
        logger.info(f"Pulled model {model_name}: {last_status}")
        return {"success": True, "model": model_name, "status": last_status or "complete"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to pull model {model_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to pull model: {e}")


@router.post("/reset")
async def reset_rag() -> dict[str, Any]:
    """
    Reset all RAG sessions (force reload).

    Returns:
        Status message
    """
    global _sessions
    count = len(_sessions)
    _sessions = {}
    logger.info(f"All RAG sessions reset ({count} cleared)")

    return {"success": True, "message": f"All RAG sessions reset ({count} cleared)"}


@router.post("/conversation/clear")
async def clear_conversation(session_id: str = "default") -> dict[str, Any]:
    """
    Clear conversation history for a session while keeping the RAG instance.

    Args:
        session_id: Session to clear

    Returns:
        Status message
    """
    if session_id in _sessions:
        _sessions[session_id]["rag"].clear_conversation()
        logger.info(f"Conversation cleared for session: {session_id}")
        return {"success": True, "message": "Conversation history cleared"}
    else:
        return {"success": True, "message": "No active session to clear"}


@router.get("/conversation/history")
async def get_conversation_history(session_id: str = "default") -> dict[str, Any]:
    """
    Get conversation history for a session.

    Args:
        session_id: Session to query

    Returns:
        Conversation history
    """
    if session_id in _sessions:
        history = _sessions[session_id]["rag"].get_conversation_history()
        return {
            "success": True,
            "session_id": session_id,
            "turns": len(history),
            "history": history
        }
    else:
        return {
            "success": True,
            "session_id": session_id,
            "turns": 0,
            "history": []
        }
