#!/usr/bin/env python3
"""
Medical Research RAG - Web UI Application

FastAPI server that provides a web interface for the RAG pipeline.
Includes document ingestion, query interface, and metrics dashboard.

Usage:
    # Standard mode (development):
    python app.py

    # Desktop mode (production/bundled):
    python app.py --desktop

Then open http://localhost:8000 in your browser.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from api import ingest, metrics, query
from src.config import settings
from src.logging_config import get_logger, setup_logging
from src.user_data import get_user_data_manager


def is_running_in_docker() -> bool:
    """
    Detect if the application is running inside a Docker container.

    Returns:
        True if running in Docker, False otherwise
    """
    # Check for .dockerenv file (created by Docker)
    if os.path.exists('/.dockerenv'):
        return True

    # Check for DOCKER_CONTAINER environment variable
    if os.getenv('DOCKER_CONTAINER', '').lower() in ('true', '1', 'yes'):
        return True

    # Check cgroup for docker
    try:
        with open('/proc/1/cgroup', 'rt') as f:
            return 'docker' in f.read()
    except Exception:
        pass

    return False


# Mode flags
IS_DESKTOP_MODE = False
IS_DOCKER_MODE = is_running_in_docker()

# Global state for auto-ingestion
auto_ingestion_status = {
    "running": False,
    "complete": False,
    "files_found": 0,
    "files_processed": 0,
    "message": "Initializing...",
}

# Setup logging
setup_logging(log_level="INFO", log_file=Path(settings.log_file), log_to_console=True)
logger = get_logger()

# Log running mode
if IS_DOCKER_MODE:
    logger.info("Running in Docker container mode")
    logger.info(f"Using Docker paths: {os.getenv('PDF_FOLDER', '/app/pdfs')}, {os.getenv('VECTOR_DB_PATH', '/app/vector_db')}")

# Initialize rate limiter
limiter = Limiter(
    key_func=get_remote_address,
    enabled=settings.rate_limit_enabled,
    default_limits=[f"{settings.rate_limit_per_minute}/minute"]
)

# Create FastAPI app
app = FastAPI(
    title="Medical Research RAG",
    description="Retrieval-Augmented Generation system for medical research documents",
    version="1.0.0",
)

# Add rate limiter to app state
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS middleware - restricted to localhost for security
# For desktop/local deployment, only allow localhost origins
ALLOWED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost",
    "http://127.0.0.1",
]

# Allow Docker internal network if running in container
if IS_DOCKER_MODE:
    ALLOWED_ORIGINS.extend([
        "http://medical-rag:8000",
        "http://rag-app:8000",
    ])

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)

# Mount API routers
app.include_router(ingest.router, prefix="/api/ingest", tags=["Ingestion"])
app.include_router(query.router, prefix="/api/query", tags=["Query"])
app.include_router(metrics.router, prefix="/api/metrics", tags=["Metrics"])

# Serve static files
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)

# Root endpoint serves the UI
@app.get("/")
async def root():
    """Serve the main UI."""
    index_path = static_dir / "index.html"
    if index_path.exists():
        # no-store so iterating on static/index.html during development
        # never gets masked by a stale browser cache.
        return FileResponse(
            index_path,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "Pragma": "no-cache",
            },
        )
    else:
        return {
            "message": "Medical Research RAG API",
            "status": "running",
            "docs": "/docs",
            "ui": "UI file not found. Please create static/index.html"
        }


# Health check
@app.get("/health")
async def health():
    """API health check. Returns 503 while auto-ingestion is still running."""
    if auto_ingestion_status.get("running") and not auto_ingestion_status.get("complete"):
        return JSONResponse(
            status_code=503,
            content={"status": "starting", "service": "Medical Research RAG",
                     "message": auto_ingestion_status.get("message", "Ingesting...")}
        )
    return {"status": "healthy", "service": "Medical Research RAG"}


# Runtime settings (overrides for config defaults) — shared with api/query.py
from src import runtime_settings as _rt

@app.get("/api/settings")
async def get_settings():
    """Get current runtime settings with defaults from config."""
    from src.config import settings as cfg
    overrides = _rt.get_overrides()
    return {
        "success": True,
        "settings": {
            "ollama_model": overrides.get("ollama_model", cfg.ollama_model),
            "temperature": overrides.get("temperature", cfg.temperature),
            "top_k_results": overrides.get("top_k_results", cfg.top_k_results),
            "max_tokens": overrides.get("max_tokens", cfg.max_tokens),
            "chunk_size": overrides.get("chunk_size", cfg.chunk_size),
            "chunk_overlap": overrides.get("chunk_overlap", cfg.chunk_overlap),
            "ollama_base_url": overrides.get("ollama_base_url", cfg.ollama_base_url),
            "ollama_embedding_model": cfg.ollama_embedding_model,
            "max_query_length": overrides.get("max_query_length", cfg.max_query_length),
            "rate_limit_per_minute": cfg.rate_limit_per_minute,
        },
        "overrides": overrides
    }

@app.post("/api/settings")
async def update_settings(updates: dict):
    """Update runtime settings. Only whitelisted keys are accepted."""
    allowed = {
        "ollama_model": str,
        "temperature": float,
        "top_k_results": int,
        "max_tokens": int,
        "chunk_size": int,
        "chunk_overlap": int,
        "ollama_base_url": str,
        "max_query_length": int,
    }

    applied = {}
    errors = []
    model_changed = False

    for key, value in updates.items():
        if key not in allowed:
            continue
        try:
            cast_value = allowed[key](value)
            # Basic validation
            if key == "temperature" and not (0.0 <= cast_value <= 2.0):
                errors.append(f"temperature must be 0-2, got {cast_value}")
                continue
            if key == "top_k_results" and not (1 <= cast_value <= 20):
                errors.append(f"top_k_results must be 1-20, got {cast_value}")
                continue
            if key == "max_tokens" and not (256 <= cast_value <= 8192):
                errors.append(f"max_tokens must be 256-8192, got {cast_value}")
                continue
            if key == "chunk_size" and not (100 <= cast_value <= 2048):
                errors.append(f"chunk_size must be 100-2048, got {cast_value}")
                continue
            if key == "chunk_overlap" and not (0 <= cast_value <= 500):
                errors.append(f"chunk_overlap must be 0-500, got {cast_value}")
                continue

            previous = _rt.get(key)
            _rt.set_override(key, cast_value)
            applied[key] = cast_value
            if key == "ollama_model" and previous != cast_value:
                model_changed = True
        except (ValueError, TypeError) as e:
            errors.append(f"Invalid value for {key}: {e}")

    # If the model was changed, drop all live RAG sessions so the next query
    # rebuilds them with the new model. Without this, the override sits in
    # the dict but existing sessions keep using the old model forever.
    if model_changed:
        try:
            from api.query import _sessions as _query_sessions
            cleared = len(_query_sessions)
            _query_sessions.clear()
            logger.info(f"Model changed — cleared {cleared} RAG session(s)")
        except Exception as e:
            logger.warning(f"Could not clear RAG sessions after model change: {e}")

    return {
        "success": len(errors) == 0,
        "applied": applied,
        "errors": errors,
        "model_changed": model_changed,
    }

@app.post("/api/settings/reset")
async def reset_settings():
    """Reset all runtime settings to config defaults."""
    _rt.clear_overrides()
    try:
        from api.query import _sessions as _query_sessions
        _query_sessions.clear()
    except Exception:
        pass
    return {"success": True, "message": "All settings reset to defaults"}


# Backup/Restore endpoints
@app.get("/api/backup/download")
async def download_backup():
    """Create and download a zip backup of the vector database and ingestion progress."""
    import shutil
    import tempfile
    from src.config import settings as cfg

    db_path = Path(cfg.vector_db_path)
    progress_file = Path("data/ingestion_progress.json")

    if not db_path.exists():
        return JSONResponse(status_code=404, content={"error": "Vector database not found"})

    try:
        # Create temp zip file
        tmp_dir = tempfile.mkdtemp()
        zip_base = os.path.join(tmp_dir, "medical_rag_backup")
        backup_staging = Path(tmp_dir) / "backup_content"
        backup_staging.mkdir()

        # Copy vector_db directory
        shutil.copytree(db_path, backup_staging / "vector_db")

        # Copy ingestion progress if it exists
        if progress_file.exists():
            (backup_staging / "data").mkdir(exist_ok=True)
            shutil.copy2(progress_file, backup_staging / "data" / "ingestion_progress.json")

        # Create zip
        zip_path = shutil.make_archive(zip_base, 'zip', backup_staging)

        return FileResponse(
            zip_path,
            media_type="application/zip",
            filename="medical_rag_backup.zip",
            background=None  # Don't delete before sending
        )

    except Exception as e:
        logger.error(f"Backup failed: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/backup/restore")
async def restore_backup(file: UploadFile = File(...)):
    """Restore vector database and ingestion progress from a zip backup."""
    import shutil
    import tempfile
    import zipfile
    from src.config import settings as cfg

    if not file.filename.endswith('.zip'):
        return JSONResponse(status_code=400, content={"error": "File must be a .zip archive"})

    try:
        # Save uploaded file to temp location
        tmp_dir = tempfile.mkdtemp()
        zip_path = os.path.join(tmp_dir, "restore.zip")
        with open(zip_path, "wb") as f:
            content = await file.read()
            f.write(content)

        # Validate zip contents
        with zipfile.ZipFile(zip_path, 'r') as zf:
            names = zf.namelist()
            has_vector_db = any(n.startswith("vector_db/") for n in names)
            if not has_vector_db:
                shutil.rmtree(tmp_dir)
                return JSONResponse(status_code=400, content={
                    "error": "Invalid backup: missing vector_db/ directory"
                })

        # Extract to temp staging
        extract_dir = os.path.join(tmp_dir, "extracted")
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(extract_dir)

        # Replace vector_db
        db_path = Path(cfg.vector_db_path)
        if db_path.exists():
            shutil.rmtree(db_path)
        shutil.copytree(os.path.join(extract_dir, "vector_db"), db_path)

        # Replace ingestion progress if present in backup
        progress_src = os.path.join(extract_dir, "data", "ingestion_progress.json")
        if os.path.exists(progress_src):
            Path("data").mkdir(exist_ok=True)
            shutil.copy2(progress_src, "data/ingestion_progress.json")

        # Reset RAG sessions so they pick up the new DB
        from api.query import _sessions
        _sessions.clear()

        # Cleanup temp files
        shutil.rmtree(tmp_dir)

        logger.info("Database restored from backup successfully")
        return {"success": True, "message": "Database restored successfully. Please refresh the page."}

    except Exception as e:
        logger.error(f"Restore failed: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# Auto-ingestion status endpoint
@app.get("/api/auto-ingest/status")
async def get_auto_ingest_status():
    """Get status of background auto-ingestion with detailed file information."""
    # Get progress tracking information
    from src.ingestion_progress import IngestionProgress
    progress = IngestionProgress()
    progress_status = progress.get_status()

    # Combine with current auto-ingestion status
    status = auto_ingestion_status.copy()
    status["processed_files"] = progress_status.get("processed_files", [])
    status["failed_files"] = progress_status.get("failed_files", [])
    status["total_processed"] = progress_status.get("total_processed", 0)
    status["total_failed"] = progress_status.get("total_failed", 0)

    return status


async def run_auto_ingestion():
    """Background task to auto-ingest PDFs from pdfs/ folder."""
    global auto_ingestion_status

    try:
        from src.pdf_parser import PDFParser
        from src.chunker import IntelligentChunker
        from src.vector_db import VectorDatabase
        from src.ingestion_progress import IngestionProgress

        # Ensure pdfs directory exists
        if IS_DESKTOP_MODE:
            # Desktop mode: use user data directory
            user_data = get_user_data_manager()
            pdf_dir = user_data.get_pdfs_dir()
            logger.info(f"Auto-ingestion: Using PDF directory: {pdf_dir}")
        else:
            # Development mode: use local pdfs/ folder
            pdf_dir = Path("pdfs")
            pdf_dir.mkdir(exist_ok=True)
            logger.info(f"Auto-ingestion: Using PDF directory: {pdf_dir.absolute()}")

        # Get all PDF files
        pdf_files = list(pdf_dir.glob("*.pdf"))
        logger.info(f"Auto-ingestion: Found {len(pdf_files)} PDF files in {pdf_dir}")

        if not pdf_files:
            auto_ingestion_status.update({
                "running": False,
                "complete": True,
                "files_found": 0,
                "files_processed": 0,
                "message": "No PDFs found in pdfs/ folder. Drop PDFs there to auto-ingest on next startup.",
            })
            logger.info("Auto-ingestion: No PDFs found in pdfs/ folder")
            return

        # Check which files are already processed
        progress = IngestionProgress()
        progress_status = progress.get_status()
        processed_files = set(progress_status.get("processed_files", []))

        # Filter out already processed files
        new_files = [f for f in pdf_files if f.name not in processed_files]

        if not new_files:
            auto_ingestion_status.update({
                "running": False,
                "complete": True,
                "files_found": len(pdf_files),
                "files_processed": 0,
                "message": f"All {len(pdf_files)} PDFs already ingested. Ready to query.",
            })
            logger.info(f"Auto-ingestion: All {len(pdf_files)} PDFs already processed")
            return

        # Start ingestion
        auto_ingestion_status.update({
            "running": True,
            "complete": False,
            "files_found": len(new_files),
            "files_processed": 0,
            "message": f"Auto-ingesting {len(new_files)} new PDF(s)...",
        })

        logger.info(f"Auto-ingestion: Starting ingestion of {len(new_files)} new PDF(s)")

        # Initialize components
        pdf_parser = PDFParser()
        text_chunker = IntelligentChunker()
        vector_db = VectorDatabase()

        # Process each new file
        for idx, pdf_path in enumerate(new_files, 1):
            try:
                logger.info(f"Auto-ingestion: Processing {pdf_path.name} ({idx}/{len(new_files)})")

                auto_ingestion_status["message"] = f"Processing {pdf_path.name} ({idx}/{len(new_files)})..."

                # Parse PDF (pass Path object, not string)
                document = await asyncio.get_event_loop().run_in_executor(
                    None, pdf_parser.parse_pdf, pdf_path
                )

                # Chunk text
                chunks = text_chunker.chunk_document(document)

                # Add to vector database
                await asyncio.get_event_loop().run_in_executor(
                    None, vector_db.add_chunks, chunks
                )

                # Mark as processed
                progress.mark_processed(pdf_path.name)

                auto_ingestion_status["files_processed"] = idx

                logger.info(f"Auto-ingestion: Successfully processed {pdf_path.name} ({len(chunks)} chunks)")

            except Exception as e:
                logger.error(f"Auto-ingestion: Failed to process {pdf_path.name}: {e}")
                progress.mark_failed(pdf_path.name, str(e))

        # Complete
        auto_ingestion_status.update({
            "running": False,
            "complete": True,
            "message": f"Auto-ingestion complete. Processed {auto_ingestion_status['files_processed']} of {len(new_files)} new PDF(s).",
        })

        logger.info(f"Auto-ingestion: Complete. Processed {auto_ingestion_status['files_processed']}/{len(new_files)} files")

    except Exception as e:
        logger.error(f"Auto-ingestion failed: {e}", exc_info=True)
        auto_ingestion_status.update({
            "running": False,
            "complete": True,
            "message": f"Auto-ingestion error: {str(e)}",
        })


@app.on_event("startup")
async def startup_event():
    """Run auto-ingestion on startup."""
    if IS_DESKTOP_MODE:
        # Desktop mode: wait for ingestion to complete before opening browser
        logger.info("Starting auto-ingestion (will open browser when complete)...")
        await run_auto_ingestion()

        # Ingestion complete - open browser after short delay
        import webbrowser
        await asyncio.sleep(2)  # Wait for server to be ready
        logger.info("Opening browser to: http://localhost:8000")
        webbrowser.open("http://localhost:8000")
    else:
        # Server mode: run in background
        logger.info("Starting background auto-ingestion task...")
        asyncio.create_task(run_auto_ingestion())


def main():
    """Start the web server."""
    logger.info("=" * 80)
    logger.info("Medical Research RAG - Web UI")
    logger.info("=" * 80)
    logger.info("")
    logger.info("Starting server...")
    logger.info("  • UI:  http://localhost:8000")
    logger.info("  • API: http://localhost:8000/docs")
    logger.info("")
    logger.info("Press CTRL+C to stop")
    logger.info("=" * 80)

    # Run server
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
        access_log=True,
    )


def run_desktop():
    """Run in desktop mode with launcher checks."""
    global IS_DESKTOP_MODE
    IS_DESKTOP_MODE = True

    # Import desktop launcher
    from src.desktop_launcher import DesktopLauncher

    # Initialize launcher
    launcher = DesktopLauncher()

    # Check prerequisites (Ollama, models, etc.)
    if not launcher.check_prerequisites():
        logger.error("Prerequisites not met. Exiting.")
        sys.exit(1)

    # Copy bundled PDFs to user data directory (first run)
    copied = launcher.copy_bundled_pdfs()
    if copied > 0:
        print(f"\n✓ Copied {copied} bundled PDF(s) to user data directory\n")

    # Show storage info
    info = launcher.user_data.get_storage_info()
    logger.info(f"User data directory: {info['base_directory']}")

    # Launch server
    logger.info("=" * 80)
    logger.info("Medical Research RAG - Desktop Application")
    logger.info("=" * 80)
    logger.info("")
    logger.info("Starting server...")
    logger.info("  • UI:  http://localhost:8000")
    logger.info("  • API: http://localhost:8000/docs")
    logger.info("")
    logger.info("Browser will open automatically after PDF ingestion completes...")
    logger.info("Press CTRL+C to stop")
    logger.info("=" * 80)

    # Run server (browser will open in startup_event after ingestion)
    uvicorn.run(
        app,
        host="127.0.0.1",  # Desktop mode: only localhost
        port=8000,
        log_level="info",
        access_log=False,  # Less verbose for desktop
    )


if __name__ == "__main__":
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Medical Research RAG Application")
    parser.add_argument(
        "--desktop",
        action="store_true",
        help="Run in desktop mode with Ollama checks and auto-browser"
    )
    args = parser.parse_args()

    try:
        # Docker mode is auto-detected and runs like main() with Docker paths
        if IS_DOCKER_MODE:
            logger.info("Starting in Docker container mode...")
            main()
        elif args.desktop:
            run_desktop()
        else:
            main()
    except KeyboardInterrupt:
        logger.info("\n\nServer stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"\nServer failed: {e}", exc_info=True)
        sys.exit(1)
