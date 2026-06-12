from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return float(value)


def _first_env(*names: str, default: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and value != "":
            return value
    return default


def _env_int_compat(default: int, *names: str) -> int:
    for name in names:
        value = os.getenv(name)
        if value is not None and value != "":
            return int(value)
    return default


def _env_float_compat(default: float, *names: str) -> float:
    for name in names:
        value = os.getenv(name)
        if value is not None and value != "":
            return float(value)
    return default


def _resolve_path(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return root / path


def _index_path_from_env(root: Path) -> Path:
    configured = os.getenv("RAG_INDEX_PATH")
    if configured:
        return _resolve_path(root, configured)

    legacy_vector_path = os.getenv("VECTOR_DB_PATH")
    if legacy_vector_path:
        path = _resolve_path(root, legacy_vector_path)
        if path.suffix:
            return path
        return path / "index.json"

    return _resolve_path(root, ".rag/index.json")


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    corpus_dir: Path
    index_path: Path
    chunk_size_chars: int = 1400
    chunk_overlap_chars: int = 220
    top_k: int = 5
    embedding_backend: str = "auto"
    hash_embedding_dimensions: int = 768
    ollama_base_url: str = "http://localhost:11434"
    ollama_embedding_model: str = "nomic-embed-text"
    generation_backend: str = "extractive"
    ollama_generation_model: str = "llama3.1"
    answer_mode: str = "patient"
    temperature: float = 0.1
    request_timeout_seconds: float = 20.0
    embedding_cache_path: Path | None = None
    manifest_path: Path | None = None
    extraction_cache_dir: Path | None = None
    pdf_workers: int = 1
    embedding_batch_size: int = 64
    min_relevance_score: float = 0.0
    reranker_backend: str = "lexical"
    hybrid_alpha: float = 0.5

    @classmethod
    def from_env(cls, root_dir: Path | None = None) -> "Settings":
        root = (root_dir or Path.cwd()).resolve()
        corpus_dir = _resolve_path(root, _first_env("RAG_CORPUS_DIR", "PDF_FOLDER", default="pdfs"))
        index_path = _index_path_from_env(root)

        return cls(
            root_dir=root,
            corpus_dir=corpus_dir,
            index_path=index_path,
            chunk_size_chars=_env_int_compat(1400, "RAG_CHUNK_SIZE_CHARS", "CHUNK_SIZE"),
            chunk_overlap_chars=_env_int_compat(220, "RAG_CHUNK_OVERLAP_CHARS", "CHUNK_OVERLAP"),
            top_k=_env_int_compat(5, "RAG_TOP_K", "TOP_K"),
            embedding_backend=os.getenv("RAG_EMBEDDING_BACKEND", "auto").lower(),
            hash_embedding_dimensions=_env_int("RAG_HASH_EMBEDDING_DIMENSIONS", 768),
            ollama_base_url=_first_env(
                "RAG_OLLAMA_BASE_URL", "OLLAMA_BASE_URL", default="http://localhost:11434"
            ),
            ollama_embedding_model=_first_env(
                "RAG_OLLAMA_EMBEDDING_MODEL",
                "OLLAMA_EMBEDDING_MODEL",
                default="nomic-embed-text",
            ),
            generation_backend=os.getenv("RAG_GENERATION_BACKEND", "extractive").lower(),
            ollama_generation_model=_first_env(
                "RAG_OLLAMA_GENERATION_MODEL", "OLLAMA_MODEL", default="llama3.1"
            ),
            answer_mode=os.getenv("RAG_ANSWER_MODE", "patient").lower(),
            temperature=_env_float_compat(0.1, "RAG_TEMPERATURE", "TEMPERATURE"),
            request_timeout_seconds=_env_float("RAG_REQUEST_TIMEOUT_SECONDS", 20.0),
            embedding_cache_path=_resolve_path(
                root, os.getenv("RAG_EMBEDDING_CACHE_PATH", ".rag/embedding_cache.json")
            ) if os.getenv("RAG_EMBEDDING_CACHE_PATH", ".rag/embedding_cache.json") else None,
            manifest_path=_resolve_path(
                root, os.getenv("RAG_MANIFEST_PATH", ".rag/manifest.sqlite")
            ) if os.getenv("RAG_MANIFEST_PATH", ".rag/manifest.sqlite") else None,
            extraction_cache_dir=_resolve_path(
                root, os.getenv("RAG_EXTRACTION_CACHE_DIR", ".rag/extracted")
            ) if os.getenv("RAG_EXTRACTION_CACHE_DIR", ".rag/extracted") else None,
            pdf_workers=_env_int("RAG_PDF_WORKERS", 1),
            embedding_batch_size=_env_int("RAG_EMBED_BATCH_SIZE", 64),
            min_relevance_score=_env_float("RAG_MIN_RELEVANCE_SCORE", 0.0),
            reranker_backend=os.getenv("RAG_RERANKER_BACKEND", "lexical").lower(),
            hybrid_alpha=_env_float("RAG_HYBRID_ALPHA", 0.5),
        )

    def with_paths(
        self, corpus_dir: Path | None = None, index_path: Path | None = None
    ) -> "Settings":
        return Settings(
            root_dir=self.root_dir,
            corpus_dir=corpus_dir or self.corpus_dir,
            index_path=index_path or self.index_path,
            chunk_size_chars=self.chunk_size_chars,
            chunk_overlap_chars=self.chunk_overlap_chars,
            top_k=self.top_k,
            embedding_backend=self.embedding_backend,
            hash_embedding_dimensions=self.hash_embedding_dimensions,
            ollama_base_url=self.ollama_base_url,
            ollama_embedding_model=self.ollama_embedding_model,
            generation_backend=self.generation_backend,
            ollama_generation_model=self.ollama_generation_model,
            answer_mode=self.answer_mode,
            temperature=self.temperature,
            request_timeout_seconds=self.request_timeout_seconds,
            embedding_cache_path=self.embedding_cache_path,
            manifest_path=self.manifest_path,
            extraction_cache_dir=self.extraction_cache_dir,
            pdf_workers=self.pdf_workers,
            embedding_batch_size=self.embedding_batch_size,
            min_relevance_score=self.min_relevance_score,
            reranker_backend=self.reranker_backend,
            hybrid_alpha=self.hybrid_alpha,
        )

    def with_ingestion_options(
        self,
        pdf_workers: int | None = None,
        embedding_batch_size: int | None = None,
    ) -> "Settings":
        return Settings(
            root_dir=self.root_dir,
            corpus_dir=self.corpus_dir,
            index_path=self.index_path,
            chunk_size_chars=self.chunk_size_chars,
            chunk_overlap_chars=self.chunk_overlap_chars,
            top_k=self.top_k,
            embedding_backend=self.embedding_backend,
            hash_embedding_dimensions=self.hash_embedding_dimensions,
            ollama_base_url=self.ollama_base_url,
            ollama_embedding_model=self.ollama_embedding_model,
            generation_backend=self.generation_backend,
            ollama_generation_model=self.ollama_generation_model,
            temperature=self.temperature,
            request_timeout_seconds=self.request_timeout_seconds,
            embedding_cache_path=self.embedding_cache_path,
            manifest_path=self.manifest_path,
            extraction_cache_dir=self.extraction_cache_dir,
            pdf_workers=pdf_workers or self.pdf_workers,
            embedding_batch_size=embedding_batch_size or self.embedding_batch_size,
            min_relevance_score=self.min_relevance_score,
            reranker_backend=self.reranker_backend,
            hybrid_alpha=self.hybrid_alpha,
        )
