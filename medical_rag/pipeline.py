from __future__ import annotations

import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from functools import partial
from pathlib import Path

from medical_rag.chunking import chunk_pages
from medical_rag.config import Settings
from medical_rag.documents import load_documents
from medical_rag.embeddings import EmbeddingModel, make_embedding_model
from medical_rag.ingestion import (
    ExtractedDocument,
    IngestionOptions,
    ManifestStore,
    discover_source_files,
    load_extracted_documents,
)
from medical_rag.llm import SAFETY_NOTICE, Generator, make_generator
from medical_rag.relevance import expand_query_for_retrieval, filter_results_for_question
from medical_rag.reranker import Reranker, make_reranker
from medical_rag.types import Chunk, Citation, IngestionReport, RagAnswer, SearchResult
from medical_rag.vector_store import (
    IngestStats,
    VectorStoreBackend,
    ingest_vector_store,
    load_vector_store,
    vector_store_exists,
)


class StrokeRAG:
    def __init__(
        self,
        settings: Settings | None = None,
        embedding_model: EmbeddingModel | None = None,
        generator: Generator | None = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        if embedding_model is not None:
            self.embedding_model = embedding_model
            self._fallback_embedding = False
        else:
            self.embedding_model, self._fallback_embedding = make_embedding_model(self.settings)
        self.generator = generator or make_generator(self.settings)
        self._reranker: Reranker = make_reranker(self.settings)
        self._store: VectorStoreBackend | None = None

    def ingest(
        self,
        source_path: Path | None = None,
        force: bool = False,
        resume: bool = True,
        failed_only: bool = False,
        ocr_scanned: bool = False,
        pdf_workers: int | None = None,
    ) -> IngestionReport:
        source = (source_path or self.settings.corpus_dir).expanduser().resolve()
        if self.settings.manifest_path is not None and self.settings.extraction_cache_dir is not None:
            return self._ingest_incremental(
                source=source,
                force=force,
                resume=resume,
                failed_only=failed_only,
                ocr_scanned=ocr_scanned,
                pdf_workers=pdf_workers,
            )

        pages = load_documents(source)
        if not pages:
            raise ValueError(f"No supported text was found under {source}")

        chunks = chunk_pages(
            pages,
            chunk_size_chars=self.settings.chunk_size_chars,
            chunk_overlap_chars=self.settings.chunk_overlap_chars,
        )
        if not chunks:
            raise ValueError(f"No chunks could be created from {source}")

        store, stats = ingest_vector_store(self.settings, chunks, self.embedding_model)
        self._store = store

        return IngestionReport(
            source_path=str(source),
            documents=len({page.source_id for page in pages}),
            pages=len(pages),
            chunks=len(chunks),
            index_path=str(self.settings.index_path),
            embedding_model=self.embedding_model.name,
            chunks_embedded=stats.chunks_embedded,
            chunks_reused=stats.chunks_reused,
            timings={
                "reuse_lookup_seconds": round(stats.lookup_seconds, 4),
                "embedding_seconds": round(stats.embedding_seconds, 4),
                "index_write_seconds": round(stats.write_seconds, 4),
            },
            vector_store=_vector_store_stats(stats),
        )

    def _ingest_incremental(
        self,
        source: Path,
        force: bool,
        resume: bool,
        failed_only: bool,
        ocr_scanned: bool,
        pdf_workers: int | None,
    ) -> IngestionReport:
        assert self.settings.manifest_path is not None
        assert self.settings.extraction_cache_dir is not None

        timings: dict[str, float] = {}
        started = time.perf_counter()
        workers = pdf_workers or self.settings.pdf_workers
        files = discover_source_files(source, workers=workers)
        timings["discovery_seconds"] = round(time.perf_counter() - started, 4)

        if not files:
            raise ValueError(f"No supported source files were found under {source}")

        manifest_start = time.perf_counter()
        manifest = ManifestStore(self.settings.manifest_path)
        current_paths = {str(file.path) for file in files}
        deleted_paths = manifest.deleted_paths(current_paths)
        manifest.mark_deleted(deleted_paths)

        for file in files:
            if file.duplicate_of:
                manifest.mark_duplicate(file)

        unique_files = [file for file in files if not file.duplicate_of]
        changed_files = manifest.changed_files(
            unique_files,
            chunk_size_chars=self.settings.chunk_size_chars,
            chunk_overlap_chars=self.settings.chunk_overlap_chars,
            embedding_model=self.embedding_model.name,
            force=force or not resume,
            failed_only=failed_only,
        )
        # Manifest time before extraction; the updates after indexing are added below.
        manifest_seconds = time.perf_counter() - manifest_start

        # A requested collection rebuild must reach the vector store even when no file changed.
        rebuild_requested = (
            self.settings.vector_store_backend == "qdrant" and self.settings.qdrant_recreate_collection
        )
        if (
            not changed_files
            and not deleted_paths
            and not rebuild_requested
            and vector_store_exists(self.settings)
        ):
            store = load_vector_store(self.settings)
            timings["manifest_seconds"] = round(manifest_seconds, 4)
            total_seconds = round(time.perf_counter() - started, 4)
            timings["total_seconds"] = total_seconds
            return IngestionReport(
                source_path=str(source),
                documents=len(unique_files),
                pages=0,
                chunks=store.chunk_count(),
                index_path=str(self.settings.index_path),
                embedding_model=self.embedding_model.name,
                files_discovered=len(files),
                files_changed=0,
                files_processed=0,
                files_from_cache=0,
                files_failed=0,
                duplicate_files=len(files) - len(unique_files),
                deleted_files=len(deleted_paths),
                skipped_unchanged=True,
                manifest_path=str(self.settings.manifest_path),
                extraction_cache_dir=str(self.settings.extraction_cache_dir),
                timings=timings,
            )

        extraction_start = time.perf_counter()
        documents, failures = load_extracted_documents(
            unique_files,
            cache_dir=self.settings.extraction_cache_dir,
            manifest=manifest,
            options=IngestionOptions(
                force=force or not resume,
                resume=resume,
                failed_only=failed_only,
                ocr_scanned=ocr_scanned,
                pdf_workers=workers,
            ),
        )
        timings["extraction_seconds"] = round(time.perf_counter() - extraction_start, 4)

        if not documents:
            raise ValueError(f"No supported text was extracted from {source}")

        chunk_start = time.perf_counter()
        chunks_by_path: dict[str, list[Chunk]] = {}
        chunks: list[Chunk] = []
        chunked = _chunk_documents(
            documents,
            chunk_size_chars=self.settings.chunk_size_chars,
            chunk_overlap_chars=self.settings.chunk_overlap_chars,
            workers=workers,
        )
        for document, document_chunks in zip(documents, chunked, strict=True):
            chunks_by_path[str(document.source.path)] = document_chunks
            chunks.extend(document_chunks)
        timings["chunking_seconds"] = round(time.perf_counter() - chunk_start, 4)

        if not chunks:
            raise ValueError(f"No chunks could be created from {source}")

        store, stats = ingest_vector_store(self.settings, chunks, self.embedding_model)
        timings["reuse_lookup_seconds"] = round(stats.lookup_seconds, 4)
        timings["embedding_seconds"] = round(stats.embedding_seconds, 4)
        timings["index_write_seconds"] = round(stats.write_seconds, 4)
        self._store = store

        manifest_start = time.perf_counter()
        documents_by_path = {str(document.source.path): document for document in documents}
        for file in unique_files:
            if str(file.path) in failures:
                continue
            document = documents_by_path.get(str(file.path))
            if document is None:
                continue
            manifest.mark_indexed(
                file=file,
                pages=len(document.pages),
                chunks=len(chunks_by_path.get(str(file.path), [])),
                chunk_size_chars=self.settings.chunk_size_chars,
                chunk_overlap_chars=self.settings.chunk_overlap_chars,
                embedding_model=self.embedding_model.name,
                scanned_pages=document.scanned_pages,
            )
        manifest_seconds += time.perf_counter() - manifest_start
        timings["manifest_seconds"] = round(manifest_seconds, 4)
        timings["total_seconds"] = round(time.perf_counter() - started, 4)

        return IngestionReport(
            source_path=str(source),
            documents=len(documents),
            pages=sum(len(document.pages) for document in documents),
            chunks=len(chunks),
            index_path=str(self.settings.index_path),
            embedding_model=self.embedding_model.name,
            files_discovered=len(files),
            files_changed=len(changed_files),
            files_processed=len([document for document in documents if not document.from_cache]),
            files_from_cache=len([document for document in documents if document.from_cache]),
            files_failed=len(failures),
            duplicate_files=len(files) - len(unique_files),
            deleted_files=len(deleted_paths),
            scanned_pages=sum(document.scanned_pages for document in documents),
            chunks_embedded=stats.chunks_embedded,
            chunks_reused=stats.chunks_reused,
            skipped_unchanged=False,
            manifest_path=str(self.settings.manifest_path),
            extraction_cache_dir=str(self.settings.extraction_cache_dir),
            timings=timings,
            vector_store=_vector_store_stats(stats),
        )

    def ask(
        self,
        question: str,
        top_k: int | None = None,
        filters: dict[str, str] | None = None,
        answer_mode: str | None = None,
    ) -> RagAnswer:
        question = question.strip()
        if not question:
            raise ValueError("Question cannot be empty")
        mode = _normalize_answer_mode(answer_mode or self.settings.answer_mode)

        store = self._load_store()
        limit = top_k or self.settings.top_k
        if limit <= 0:
            raise ValueError("top_k must be greater than zero")

        candidate_limit = min(max(limit * 4, limit), 50)
        results = store.search(
            query=expand_query_for_retrieval(question),
            embedding_model=self.embedding_model,
            top_k=candidate_limit,
            filters=filters,
        )
        results = filter_results_for_question(question, results)
        results = [r for r in results if r.score >= self.settings.min_relevance_score]
        results = self._reranker.rerank(question, results)[:limit]

        answer = self.generator.generate(question, results, answer_mode=mode)
        citations = [_citation(result, citation_id) for citation_id, result in enumerate(results, 1)]

        return RagAnswer(
            question=question,
            answer=answer,
            citations=citations,
            retrieval_model=self.embedding_model.name,
            generation_model=self.generator.model_name,
            answer_mode=mode,
            safety_notice=SAFETY_NOTICE,
            retrieval_mode=store.retrieval_mode,
            fallback_embedding=self._fallback_embedding,
        )

    def sources(self) -> list[dict[str, object]]:
        return self._load_store().source_summaries()

    def index_exists(self) -> bool:
        return vector_store_exists(self.settings)

    def fallback_embedding_used(self) -> bool:
        return self._fallback_embedding

    def _load_store(self) -> VectorStoreBackend:
        if self._store is not None:
            return self._store
        if not vector_store_exists(self.settings):
            if self.settings.vector_store_backend == "qdrant":
                location = (
                    f"Qdrant collection {self.settings.qdrant_collection!r} not found at "
                    f"{self.settings.qdrant_url}"
                )
            else:
                location = f"Vector index not found at {self.settings.index_path}"
            raise FileNotFoundError(f"{location}. Run ingestion first.")
        self._store = load_vector_store(self.settings)
        return self._store


def _chunk_documents(
    documents: list[ExtractedDocument],
    chunk_size_chars: int,
    chunk_overlap_chars: int,
    workers: int,
) -> list[list[Chunk]]:
    """Chunk each document, in document order. Chunk ids depend only on their own document,
    so chunking documents in parallel processes gives exactly the sequential result."""
    chunk = partial(
        _chunk_document, chunk_size_chars=chunk_size_chars, chunk_overlap_chars=chunk_overlap_chars
    )
    if workers <= 1 or len(documents) < 2:
        return [chunk(document) for document in documents]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(chunk, documents, chunksize=max(1, len(documents) // (workers * 4))))


def _chunk_document(
    document: ExtractedDocument, chunk_size_chars: int, chunk_overlap_chars: int
) -> list[Chunk]:
    chunks = chunk_pages(
        document.pages,
        chunk_size_chars=chunk_size_chars,
        chunk_overlap_chars=chunk_overlap_chars,
    )
    for chunk in chunks:
        chunk.metadata.update(
            {
                "source_hash": document.source.sha256,
                "source_size": document.source.size,
                "source_mtime_ns": document.source.mtime_ns,
                "parser_version": "pymupdf-sorted-text-v1",
                "chunk_size_chars": chunk_size_chars,
                "chunk_overlap_chars": chunk_overlap_chars,
            }
        )
    return chunks


def _vector_store_stats(stats: IngestStats) -> dict[str, float | int]:
    return {
        key: round(value, 4) if isinstance(value, float) else value
        for key, value in asdict(stats).items()
    }


def _citation(result: SearchResult, citation_id: int) -> Citation:
    metadata = result.chunk.metadata
    return Citation(
        id=citation_id,
        source=str(metadata.get("source_id", "unknown")),
        page=metadata.get("page"),
        chunk_id=result.chunk.id,
        score=round(result.score, 6),
        excerpt=_excerpt(result.chunk.text, 320),
    )


def _excerpt(text: str, max_chars: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rsplit(" ", 1)[0] + "..."


def _normalize_answer_mode(answer_mode: str) -> str:
    mode = answer_mode.strip().lower()
    if mode not in {"patient", "clinician"}:
        raise ValueError("answer_mode must be either 'patient' or 'clinician'")
    return mode
