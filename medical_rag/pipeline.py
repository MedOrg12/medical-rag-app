from __future__ import annotations

from pathlib import Path

from medical_rag.chunking import chunk_pages
from medical_rag.config import Settings
from medical_rag.documents import load_documents
from medical_rag.embeddings import EmbeddingModel, make_embedding_model
from medical_rag.llm import SAFETY_NOTICE, Generator, make_generator
from medical_rag.relevance import expand_query_for_retrieval, filter_results_for_question
from medical_rag.types import Citation, IngestionReport, RagAnswer, SearchResult
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

    def ingest(self, source_path: Path | None = None) -> IngestionReport:
        source = (source_path or self.settings.corpus_dir).expanduser().resolve()
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
        results = filter_results_for_question(question, results)[:limit]
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


def _normalize_answer_mode(answer_mode: str) -> str:
    mode = answer_mode.strip().lower()
    if mode not in {"patient", "clinician"}:
        raise ValueError("answer_mode must be either 'patient' or 'clinician'")
    return mode
