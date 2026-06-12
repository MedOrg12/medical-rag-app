from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from medical_rag.config import Settings
    from medical_rag.types import SearchResult

_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_+-]*|\d+(?:\.\d+)?")


def _terms(text: str) -> set[str]:
    return {m.group(0).lower() for m in _TOKEN_RE.finditer(text)}


class Reranker(ABC):
    @abstractmethod
    def rerank(self, question: str, results: list[SearchResult]) -> list[SearchResult]:
        raise NotImplementedError


@dataclass
class LexicalReranker(Reranker):
    """Keyword overlap + phrase bonus + original vector score combined reranker."""

    def rerank(self, question: str, results: list[SearchResult]) -> list[SearchResult]:
        if not results:
            return results

        q_terms = _terms(question)
        q_lower = question.lower()

        scored: list[tuple[float, SearchResult]] = []
        for result in results:
            chunk_terms = _terms(result.chunk.text)
            keyword_score = (
                len(q_terms & chunk_terms) / len(q_terms) if q_terms else 0.0
            )
            phrase_bonus = 0.2 if q_lower in result.chunk.text.lower() else 0.0
            combined = keyword_score * 0.4 + phrase_bonus + result.score * 0.4
            scored.append((combined, result))

        scored.sort(key=lambda x: x[0], reverse=True)
        from medical_rag.types import SearchResult as SR  # local import to avoid circular

        return [
            SR(chunk=r.chunk, score=r.score, rank=new_rank)
            for new_rank, (_, r) in enumerate(scored, start=1)
        ]


class PassthroughReranker(Reranker):
    """No-op reranker — returns results unchanged."""

    def rerank(self, question: str, results: list[SearchResult]) -> list[SearchResult]:
        return results


def make_reranker(settings: Settings) -> Reranker:
    if settings.reranker_backend == "lexical":
        return LexicalReranker()
    return PassthroughReranker()
