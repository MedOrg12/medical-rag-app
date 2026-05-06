"""
Metrics API endpoints for system statistics and monitoring.
"""

from typing import Any

from fastapi import APIRouter, HTTPException

from src.config import settings
from src.ingestion_progress import IngestionProgress
from src.logging_config import get_logger
from src.metrics import get_metrics
from src.vector_db import VectorDatabase, get_vector_db

router = APIRouter()
logger = get_logger()


@router.get("/stats")
async def get_all_stats() -> dict[str, Any]:
    """
    Get all system statistics.

    Returns:
        Dictionary with database, cache, and ingestion stats
    """
    try:
        # Database stats
        vector_db = get_vector_db()
        db_stats = vector_db.get_collection_stats()

        # Ingestion progress
        progress = IngestionProgress()
        progress_status = progress.get_status()

        # Embedding cache stats (read directly from cache, no need to init OllamaEmbeddings)
        cache_stats = None
        try:
            from src.embedding_cache import EmbeddingCache
            cache = EmbeddingCache()
            cache_stats = cache.get_stats()
        except Exception:
            pass

        # Metrics
        metrics = get_metrics()
        all_metrics = metrics.get_all_metrics()

        return {
            "success": True,
            "database": {
                "total_chunks": db_stats.get("total_chunks", 0),
                "collection_name": db_stats.get("collection_name", ""),
                "db_path": db_stats.get("db_path", ""),
                "sample_files": db_stats.get("sample_files", [])
            },
            "ingestion": {
                "total_processed": progress_status.get("total_processed", 0),
                "total_failed": progress_status.get("total_failed", 0),
                "failed_files": progress_status.get("failed_files", [])
            },
            "cache": cache_stats if cache_stats else {
                "hits": 0,
                "misses": 0,
                "hit_rate_percent": 0.0,
                "total_requests": 0
            },
            "metrics": all_metrics
        }

    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/database")
async def get_database_stats() -> dict[str, Any]:
    """
    Get database-specific statistics.

    Returns:
        Database statistics
    """
    try:
        vector_db = get_vector_db()
        stats = vector_db.get_collection_stats()

        return {
            "success": True,
            "stats": stats
        }

    except Exception as e:
        logger.error(f"Failed to get database stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/library")
async def get_document_library() -> dict[str, Any]:
    """
    Get all ingested documents with chunk counts.

    Returns:
        Full document library with per-file chunk statistics
    """
    try:
        vector_db = get_vector_db()
        files = vector_db.get_all_files_with_counts()
        total_chunks = sum(f["chunks"] for f in files)

        return {
            "success": True,
            "total_files": len(files),
            "total_chunks": total_chunks,
            "files": files
        }

    except Exception as e:
        logger.error(f"Failed to get document library: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/chunk/{chunk_id}")
async def delete_chunk(chunk_id: str) -> dict[str, Any]:
    """
    Delete a single chunk from the vector database by ID.
    """
    try:
        vector_db = get_vector_db()
        deleted = vector_db.delete_chunk(chunk_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Chunk {chunk_id} not found")
        return {"success": True, "chunk_id": chunk_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete chunk {chunk_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/library/{filename:path}")
async def get_document_chunks(filename: str) -> dict[str, Any]:
    """
    Get all chunks for a specific document.

    Args:
        filename: Source filename to retrieve chunks for

    Returns:
        All chunks with content and metadata
    """
    try:
        vector_db = get_vector_db()
        chunks = vector_db.get_chunks_for_file(filename)

        return {
            "success": True,
            "filename": filename,
            "total_chunks": len(chunks),
            "chunks": chunks
        }

    except Exception as e:
        logger.error(f"Failed to get chunks for {filename}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cache")
async def get_cache_stats() -> dict[str, Any]:
    """
    Get embedding cache statistics.

    Returns:
        Cache statistics
    """
    try:
        from src.embedding_cache import EmbeddingCache
        cache = EmbeddingCache()
        cache_stats = cache.get_stats()
        cache_size = cache.get_cache_size()

        return {
            "success": True,
            "stats": cache_stats,
            "size": cache_size
        }

    except Exception as e:
        logger.error(f"Failed to get cache stats: {e}")
        return {
            "success": False,
            "error": str(e),
            "stats": {
                "hits": 0,
                "misses": 0,
                "hit_rate_percent": 0.0,
                "total_requests": 0
            }
        }


@router.get("/health")
async def health_check() -> dict[str, Any]:
    """
    Health check endpoint.

    Returns:
        System health status
    """
    try:
        # Check database
        vector_db = get_vector_db()
        db_stats = vector_db.get_collection_stats()
        db_healthy = db_stats.get("total_chunks", 0) > 0

        # Check Ollama
        ollama_healthy = False
        try:
            import requests
            response = requests.get(f"{settings.ollama_base_url}/api/tags", timeout=settings.api_request_timeout)
            ollama_healthy = response.status_code == 200
        except Exception:
            pass

        return {
            "success": True,
            "status": "healthy" if (db_healthy and ollama_healthy) else "degraded",
            "components": {
                "database": "healthy" if db_healthy else "empty",
                "ollama": "healthy" if ollama_healthy else "unreachable",
                "api": "healthy"
            },
            "database_chunks": db_stats.get("total_chunks", 0)
        }

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "success": False,
            "status": "unhealthy",
            "error": str(e)
        }
