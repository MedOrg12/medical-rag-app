from __future__ import annotations

import time
from pathlib import Path

from medical_rag.chunking import chunk_pages
from medical_rag.config import Settings
from medical_rag.documents import load_documents
from medical_rag.embeddings import EmbeddingModel, make_embedding_model
from medical_rag.ingestion import (
    IngestionOptions,
    ManifestStore,
    discover_source_files,
    load_extracted_documents,
)
from medical_rag.llm import SAFETY_NOTICE, Generator, make_generator
from medical_rag.relevance import expand_query_for_retrieval, filter_results_for_question
from medical_rag.types import Chunk, Citation, IngestionReport, RagAnswer, SearchResult
from medical_rag.vector_store import VectorStore


class StrokeRAG:
    def __init__(
        self,
        settings: Settings | None = None,
        embedding_model: EmbeddingModel | None = None,
        generator: Generator | None = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.embedding_model = embedding_model or make_embedding_model(self.settings)
        self.generator = generator or make_generator(self.settings)
        self._store: VectorStore | None = None

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

        store = VectorStore.build(
            path=self.settings.index_path,
            chunks=chunks,
            embedding_model=self.embedding_model,
        )
        store.save()
        self._store = store

        return IngestionReport(
            source_path=str(source),
            documents=len({page.source_id for page in pages}),
            pages=len(pages),
            chunks=len(chunks),
            index_path=str(self.settings.index_path),
            embedding_model=self.embedding_model.name,
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
        files = discover_source_files(source)
        timings["discovery_seconds"] = round(time.perf_counter() - started, 4)

        if not files:
            raise ValueError(f"No supported source files were found under {source}")

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

        if not changed_files and not deleted_paths and self.settings.index_path.exists():
            store = VectorStore.load(self.settings.index_path)
            total_seconds = round(time.perf_counter() - started, 4)
            timings["total_seconds"] = total_seconds
            return IngestionReport(
                source_path=str(source),
                documents=len(unique_files),
                pages=0,
                chunks=len(store.chunks),
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
                pdf_workers=pdf_workers or self.settings.pdf_workers,
            ),
        )
        timings["extraction_seconds"] = round(time.perf_counter() - extraction_start, 4)

        if not documents:
            raise ValueError(f"No supported text was extracted from {source}")

        chunk_start = time.perf_counter()
        chunks_by_path: dict[str, list[Chunk]] = {}
        chunks: list[Chunk] = []
        for document in documents:
            document_chunks = chunk_pages(
                document.pages,
                chunk_size_chars=self.settings.chunk_size_chars,
                chunk_overlap_chars=self.settings.chunk_overlap_chars,
            )
            for chunk in document_chunks:
                chunk.metadata.update(
                    {
                        "source_hash": document.source.sha256,
                        "source_size": document.source.size,
                        "source_mtime_ns": document.source.mtime_ns,
                        "parser_version": "pymupdf-sorted-text-v1",
                        "chunk_size_chars": self.settings.chunk_size_chars,
                        "chunk_overlap_chars": self.settings.chunk_overlap_chars,
                    }
                )
            chunks_by_path[str(document.source.path)] = document_chunks
            chunks.extend(document_chunks)
        timings["chunking_seconds"] = round(time.perf_counter() - chunk_start, 4)

        if not chunks:
            raise ValueError(f"No chunks could be created from {source}")

        embedding_start = time.perf_counter()
        store = VectorStore.build(
            path=self.settings.index_path,
            chunks=chunks,
            embedding_model=self.embedding_model,
        )
        timings["embedding_seconds"] = round(time.perf_counter() - embedding_start, 4)

        save_start = time.perf_counter()
        store.save()
        timings["index_write_seconds"] = round(time.perf_counter() - save_start, 4)
        timings["total_seconds"] = round(time.perf_counter() - started, 4)
        self._store = store

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
            skipped_unchanged=False,
            manifest_path=str(self.settings.manifest_path),
            extraction_cache_dir=str(self.settings.extraction_cache_dir),
            timings=timings,
        )

    def ask(
        self,
        question: str,
        top_k: int | None = None,
        filters: dict[str, str] | None = None,
    ) -> RagAnswer:
        question = question.strip()
        if not question:
            raise ValueError("Question cannot be empty")

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
        results = filter_results_for_question(question, results)[:limit]
        answer = self.generator.generate(question, results)
        citations = [_citation(result, citation_id) for citation_id, result in enumerate(results, 1)]

        return RagAnswer(
            question=question,
            answer=answer,
            citations=citations,
            retrieval_model=self.embedding_model.name,
            generation_model=self.generator.model_name,
            safety_notice=SAFETY_NOTICE,
        )

    def sources(self) -> list[dict[str, object]]:
        return self._load_store().source_summaries()

    def index_exists(self) -> bool:
        return self.settings.index_path.exists()

    def _load_store(self) -> VectorStore:
        if self._store is not None:
            return self._store
        if not self.settings.index_path.exists():
            raise FileNotFoundError(
                f"Vector index not found at {self.settings.index_path}. Run ingestion first."
            )
        self._store = VectorStore.load(self.settings.index_path)
        return self._store


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
