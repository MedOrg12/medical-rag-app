"""
Ingestion API endpoints for document upload and processing.
"""

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.chunker import IntelligentChunker
from src.config import settings
from src.file_utils import check_directory_writable, check_disk_space
from src.ingestion_progress import IngestionProgress
from src.logging_config import get_logger
from src.metrics import get_metrics
from src.pdf_parser import PDFParser
from src.validation import ValidationError, validate_filename
from src.vector_db import VectorDatabase, get_vector_db, reset_vector_db_cache

router = APIRouter()
logger = get_logger()

# Global state for tracking ingestion
ingestion_status = {"is_running": False, "progress": 0, "message": "", "files_processed": []}


@router.post("/upload")
async def upload_pdfs(files: list[UploadFile] = File(...)) -> dict[str, Any]:
    """
    Upload PDF files to the pdf folder.

    Args:
        files: List of uploaded PDF files

    Returns:
        Dictionary with upload status and file list
    """
    try:
        pdf_dir = Path(settings.pdf_folder)
        pdf_dir.mkdir(parents=True, exist_ok=True)

        uploaded_files = []
        failed_files = []

        for file in files:
            try:
                # Validate filename for security
                validated_filename = validate_filename(
                    file.filename,
                    allowed_extensions=settings.allowed_file_extensions
                )
            except ValidationError as e:
                failed_files.append({"file": file.filename, "error": str(e)})
                continue

            # Check file size
            content = await file.read()
            max_size_bytes = settings.max_upload_file_size_mb * 1024 * 1024
            if len(content) > max_size_bytes:
                failed_files.append({
                    "file": validated_filename,
                    "error": f"File size exceeds {settings.max_upload_file_size_mb}MB"
                })
                continue

            # Save file with validated filename
            file_path = pdf_dir / validated_filename
            with open(file_path, "wb") as f:
                f.write(content)

            uploaded_files.append(validated_filename)
            logger.info(f"Uploaded: {validated_filename}")

        return {
            "success": True,
            "uploaded": uploaded_files,
            "failed": failed_files,
            "total": len(uploaded_files),
        }

    except Exception as e:
        logger.error(f"Upload error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest")
async def start_ingestion(reset: bool = False) -> dict[str, Any]:
    """
    Start the ingestion pipeline (non-blocking).

    Args:
        reset: Whether to reset the vector database

    Returns:
        Status message
    """
    global ingestion_status

    if ingestion_status["is_running"]:
        return {"success": False, "error": "Ingestion already running"}

    # Reset status
    ingestion_status = {"is_running": True, "progress": 0, "message": "Starting ingestion...", "files_processed": []}

    # Start ingestion in background (will be handled by WebSocket)
    return {"success": True, "message": "Ingestion started. Connect to WebSocket for progress updates."}


@router.get("/status")
async def get_ingestion_status() -> dict[str, Any]:
    """
    Get current ingestion status.

    Returns:
        Current ingestion status
    """
    return ingestion_status


@router.websocket("/stream")
async def websocket_ingestion(websocket: WebSocket):
    """
    WebSocket endpoint for real-time ingestion progress updates.
    """
    global ingestion_status

    await websocket.accept()
    logger.info("WebSocket connection established")

    try:
        # Wait for start signal
        data = await websocket.receive_text()
        params = json.loads(data)
        reset = params.get("reset", False)

        # Start ingestion
        ingestion_status["is_running"] = True
        await websocket.send_json({"type": "status", "message": "Ingestion started", "progress": 0})

        # Run ingestion with progress updates
        try:
            await run_ingestion_pipeline(websocket, reset)
            ingestion_status["is_running"] = False
            await websocket.send_json({"type": "complete", "message": "Ingestion complete", "progress": 100})

        except Exception as e:
            logger.error(f"Ingestion error: {e}", exc_info=True)
            ingestion_status["is_running"] = False
            await websocket.send_json({"type": "error", "message": str(e), "progress": 0})

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
        ingestion_status["is_running"] = False
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        ingestion_status["is_running"] = False


async def run_ingestion_pipeline(websocket: WebSocket, reset: bool = False):
    """
    Run the complete ingestion pipeline with progress updates.

    Args:
        websocket: WebSocket connection for progress updates
        reset: Whether to reset the database
    """
    metrics = get_metrics()
    metrics.start_timer("total_ingestion")

    # Step 1: Validate environment
    await websocket.send_json({"type": "log", "message": "Validating environment..."})
    pdf_dir = Path(settings.pdf_folder)
    check_directory_writable(Path(settings.data_folder), create_if_missing=True)
    check_disk_space(Path(settings.data_folder), required_mb=500)

    # Step 2: Get PDF files
    await websocket.send_json({"type": "log", "message": "Scanning PDF folder...", "progress": 10})
    pdf_parser = PDFParser()
    pdf_files = pdf_parser.get_pdf_files()

    if not pdf_files:
        raise Exception(f"No PDF files found in {settings.pdf_folder}")

    # Check ingestion progress
    progress = IngestionProgress()
    if reset:
        progress.clear()
        await websocket.send_json({"type": "log", "message": "Database reset requested"})

    remaining_files = progress.get_remaining_files(pdf_files)
    await websocket.send_json({
        "type": "log",
        "message": f"Found {len(pdf_files)} PDFs ({len(remaining_files)} to process)",
        "progress": 20
    })

    if not remaining_files:
        await websocket.send_json({"type": "log", "message": "All PDFs already processed"})
        return

    # Step 3: Parse PDFs
    await websocket.send_json({"type": "log", "message": "Parsing PDFs...", "progress": 30})
    documents = []
    total_files = len(remaining_files)

    for idx, pdf_file in enumerate(remaining_files):
        try:
            await websocket.send_json({
                "type": "log",
                "message": f"Processing: {pdf_file.name} ({idx + 1}/{total_files})"
            })

            # Run PDF parsing in executor to avoid blocking
            loop = asyncio.get_event_loop()
            doc = await loop.run_in_executor(None, pdf_parser.parse_pdf, pdf_file)

            if doc:
                documents.append(doc)
                progress.mark_processed(pdf_file.name)  # Use just filename, not full path
                await websocket.send_json({
                    "type": "log",
                    "message": f"✓ Completed: {pdf_file.name}",
                    "progress": 30 + int((idx + 1) / total_files * 20)
                })
            else:
                progress.mark_failed(pdf_file.name, "No content extracted")  # Use just filename
                await websocket.send_json({"type": "log", "message": f"⚠ No content: {pdf_file.name}"})

        except Exception as e:
            progress.mark_failed(pdf_file.name, str(e))  # Use just filename
            await websocket.send_json({"type": "log", "message": f"✗ Failed: {pdf_file.name} - {e}"})

    if not documents:
        raise Exception("Failed to parse any documents")

    await websocket.send_json({"type": "log", "message": f"Parsed {len(documents)} documents", "progress": 50})

    # Step 4: Chunk documents
    await websocket.send_json({"type": "log", "message": "Chunking documents...", "progress": 60})
    chunker = IntelligentChunker(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        min_chunk_size=settings.min_chunk_size,
    )

    loop = asyncio.get_event_loop()
    chunks = await loop.run_in_executor(None, chunker.chunk_documents, documents)

    if not chunks:
        raise Exception("Failed to create chunks")

    avg_chunk_size = sum(c.token_count for c in chunks) / len(chunks)
    await websocket.send_json({
        "type": "log",
        "message": f"Created {len(chunks)} chunks (avg: {avg_chunk_size:.1f} tokens)",
        "progress": 70
    })

    # Step 5: Store in vector database
    await websocket.send_json({"type": "log", "message": "Storing in vector database...", "progress": 80})
    vector_db = VectorDatabase(reset=reset)

    # Add chunks (this may take a while with embeddings)
    await loop.run_in_executor(None, vector_db.add_chunks, chunks)

    stats = vector_db.get_collection_stats()
    await websocket.send_json({
        "type": "log",
        "message": f"Database now contains {stats['total_chunks']} chunks",
        "progress": 95
    })

    # Get embedding cache stats
    try:
        from src.embeddings import OllamaEmbeddings
        embeddings = OllamaEmbeddings()
        if hasattr(embeddings, "cache") and embeddings.cache:
            cache_stats = embeddings.cache.get_stats()
            await websocket.send_json({
                "type": "log",
                "message": f"Cache hit rate: {cache_stats['hit_rate_percent']:.1f}%"
            })
    except Exception:
        pass

    metrics.stop_timer("total_ingestion")
    await websocket.send_json({"type": "log", "message": "Ingestion complete!", "progress": 100})


@router.delete("/file/{filename:path}")
async def delete_ingested_file(filename: str, delete_file: bool = False) -> dict[str, Any]:
    """
    Delete an ingested PDF file's chunks from the vector database and progress tracking.

    Args:
        filename: Name of the PDF file to remove
        delete_file: Whether to also delete the PDF file from disk

    Returns:
        Deletion result with chunk count
    """
    try:
        # Validate filename
        if not filename or ".." in filename or "/" in filename:
            raise HTTPException(status_code=400, detail="Invalid filename")

        logger.info(f"Deleting ingested file: {filename} (delete_file={delete_file})")

        # Remove chunks from vector database
        vector_db = get_vector_db()
        chunks_deleted = vector_db.delete_by_source_file(filename)

        # Remove from ingestion progress tracking
        progress = IngestionProgress()
        was_tracked = filename in progress.processed_files
        progress.processed_files.discard(filename)
        progress.failed_files.pop(filename, None)
        progress._save_progress()

        # Only delete the PDF file from disk if requested
        file_deleted = False
        if delete_file:
            pdf_path = Path("pdfs") / filename
            if pdf_path.exists():
                pdf_path.unlink()
                file_deleted = True
                logger.info(f"Deleted PDF file from disk: {pdf_path}")

        logger.info(
            f"File removal complete: {filename} "
            f"(chunks={chunks_deleted}, tracked={was_tracked}, file_deleted={file_deleted})"
        )

        return {
            "success": True,
            "filename": filename,
            "chunks_deleted": chunks_deleted,
            "was_tracked": was_tracked,
            "file_deleted": file_deleted,
            "message": f"Removed {filename}: {chunks_deleted} chunks deleted"
                       + (", PDF file deleted from disk" if file_deleted else "")
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete file {filename}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class BulkDeleteRequest(BaseModel):
    """Request model for bulk file deletion."""
    filenames: list[str]
    delete_files: bool = False


@router.post("/bulk-delete")
async def bulk_delete_files(request: BulkDeleteRequest) -> dict[str, Any]:
    """
    Delete multiple ingested files at once.

    Args:
        request: List of filenames and whether to delete PDFs from disk

    Returns:
        Summary of deletions
    """
    try:
        vector_db = get_vector_db()
        progress = IngestionProgress()

        total_chunks = 0
        files_deleted = 0
        results = []

        for filename in request.filenames:
            if not filename or ".." in filename or "/" in filename:
                results.append({"file": filename, "error": "Invalid filename"})
                continue

            chunks = vector_db.delete_by_source_file(filename)
            total_chunks += chunks

            progress.processed_files.discard(filename)
            progress.failed_files.pop(filename, None)

            file_deleted = False
            if request.delete_files:
                pdf_path = Path("pdfs") / filename
                if pdf_path.exists():
                    pdf_path.unlink()
                    file_deleted = True
                    files_deleted += 1

            results.append({"file": filename, "chunks": chunks, "file_deleted": file_deleted})

        progress._save_progress()

        logger.info(f"Bulk delete: {len(request.filenames)} files, {total_chunks} chunks removed")

        return {
            "success": True,
            "total_files": len(request.filenames),
            "total_chunks_deleted": total_chunks,
            "files_deleted_from_disk": files_deleted,
            "results": results
        }

    except Exception as e:
        logger.error(f"Bulk delete failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pdf/{filename:path}")
async def get_pdf(filename: str):
    """
    Stream a PDF file from the pdfs folder so the frontend can render it
    inline. Filename is validated to prevent path traversal.
    """
    try:
        safe_name = validate_filename(filename, allowed_extensions=[".pdf"])
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    pdf_path = Path(settings.pdf_folder) / safe_name
    if not pdf_path.exists() or not pdf_path.is_file():
        raise HTTPException(status_code=404, detail=f"PDF not found: {safe_name}")

    # `inline` so the browser renders it instead of downloading it
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{safe_name}"'},
    )


class RechunkRequest(BaseModel):
    """Optional per-request chunking overrides for /rechunk."""
    chunk_size: int | None = None
    chunk_overlap: int | None = None


@router.post("/rechunk/{filename:path}")
async def rechunk_file(filename: str, body: RechunkRequest | None = None) -> dict[str, Any]:
    """
    Re-chunk a single PDF in place: drop its existing chunks from the vector
    database, re-parse the PDF, re-chunk it (optionally with custom
    chunk_size / chunk_overlap), and re-embed. Useful for experimenting with
    different chunk sizes on a specific document without touching the rest.

    Args:
        filename: PDF filename (basename, must live in the pdfs folder)
        body: Optional chunk_size / chunk_overlap overrides for this run

    Returns:
        Summary of old vs. new chunk counts and the chunking parameters used.
    """
    try:
        # Validate filename
        try:
            safe_name = validate_filename(filename, allowed_extensions=[".pdf"])
        except ValidationError as e:
            raise HTTPException(status_code=400, detail=str(e))

        pdf_path = Path(settings.pdf_folder) / safe_name
        if not pdf_path.exists():
            raise HTTPException(status_code=404, detail=f"PDF not found: {safe_name}")

        # Resolve chunking params: explicit body > runtime settings > config
        from src import runtime_settings as rt
        override_size = body.chunk_size if body else None
        override_overlap = body.chunk_overlap if body else None
        chunk_size = override_size or rt.get("chunk_size") or settings.chunk_size
        chunk_overlap = override_overlap or rt.get("chunk_overlap") or settings.chunk_overlap

        if chunk_overlap >= chunk_size:
            raise HTTPException(
                status_code=400,
                detail=f"chunk_overlap ({chunk_overlap}) must be less than chunk_size ({chunk_size})",
            )

        logger.info(
            f"Rechunking {safe_name} with chunk_size={chunk_size}, chunk_overlap={chunk_overlap}"
        )

        vector_db = get_vector_db()

        # 1. Drop the existing chunks for this file
        old_chunks = vector_db.delete_by_source_file(safe_name)

        # 2. Re-parse the PDF
        parser = PDFParser()
        doc = parser.parse_pdf(pdf_path)
        if not doc:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to re-parse {safe_name}",
            )

        # 3. Re-chunk with the requested parameters
        chunker = IntelligentChunker(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        new_chunks = chunker.chunk_document(doc)

        if not new_chunks:
            raise HTTPException(
                status_code=500,
                detail=f"Re-chunking produced no chunks for {safe_name}",
            )

        # 4. Re-embed and write back to the vector DB
        vector_db.add_chunks(new_chunks)

        # 5. Make sure the file stays marked as processed
        progress = IngestionProgress()
        progress.processed_files.add(safe_name)
        progress.failed_files.pop(safe_name, None)
        progress._save_progress()

        logger.info(
            f"Rechunked {safe_name}: {old_chunks} → {len(new_chunks)} chunks"
        )

        return {
            "success": True,
            "filename": safe_name,
            "old_chunk_count": old_chunks,
            "new_chunk_count": len(new_chunks),
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "message": f"Rechunked {safe_name}: {old_chunks} → {len(new_chunks)} chunks",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to rechunk {filename}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class BulkReingestRequest(BaseModel):
    """Request model for bulk re-ingestion."""
    filenames: list[str]


@router.post("/bulk-reingest")
async def bulk_reingest_files(request: BulkReingestRequest) -> dict[str, Any]:
    """
    Mark files for re-ingestion by removing their chunks and progress tracking.
    Files will be re-ingested on next auto-ingestion cycle or server restart.

    Args:
        request: List of filenames to re-ingest

    Returns:
        Summary of files marked for re-ingestion
    """
    try:
        vector_db = get_vector_db()
        progress = IngestionProgress()

        total_chunks = 0

        for filename in request.filenames:
            if not filename or ".." in filename or "/" in filename:
                continue

            chunks = vector_db.delete_by_source_file(filename)
            total_chunks += chunks
            progress.processed_files.discard(filename)
            progress.failed_files.pop(filename, None)

        progress._save_progress()

        logger.info(f"Bulk re-ingest: {len(request.filenames)} files marked, {total_chunks} old chunks removed")

        return {
            "success": True,
            "total_files": len(request.filenames),
            "total_chunks_removed": total_chunks,
            "message": f"{len(request.filenames)} file(s) marked for re-ingestion. Restart the server or trigger ingestion to process them."
        }

    except Exception as e:
        logger.error(f"Bulk re-ingest failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
