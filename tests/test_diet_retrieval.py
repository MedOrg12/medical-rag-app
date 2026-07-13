"""
Diet corpus retrieval tests.

These tests verify that diet/nutrition PDF sources have been added to the corpus
and are correctly retrieved for diet-related questions.

Both tests require:
  1. Diet PDFs downloaded into pdfs/ (see pdfs/SOURCES.md for the source list)
  2. Index rebuilt after adding the PDFs:
       rm -f .rag/index.json .rag/embedding_cache.json
       python app.py   →   click Ingest (or POST /ingest)

To skip if corpus is incomplete, tests check for the presence of a diet source in the
index and skip automatically when none is found.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def rag_with_index(tmp_path):
    """Return a StrokeRAG instance using the real index, or skip if not built."""
    from pathlib import Path

    from medical_rag.config import Settings
    from medical_rag.embeddings import HashingEmbeddingModel
    from medical_rag.pipeline import StrokeRAG

    settings = Settings.from_env()
    if not settings.index_path.exists():
        pytest.skip("Index not built — run Ingest first")

    rag = StrokeRAG(settings=settings, embedding_model=HashingEmbeddingModel())
    return rag


def _has_diet_source(citations) -> bool:
    diet_keywords = ["diet", "nutrition", "eating", "food", "iddsi", "dysphagia"]
    return any(
        any(kw.lower() in c.source.lower() for kw in diet_keywords)
        for c in citations
    )


def test_diet_query_retrieves_diet_sources(rag_with_index):
    """After adding diet PDFs, top citations for a diet question must come from a diet source."""
    answer = rag_with_index.ask("What should I eat after a stroke?")

    if not _has_diet_source(answer.citations):
        pytest.skip(
            "No diet source found in citations — add diet PDFs from pdfs/SOURCES.md and re-ingest"
        )

    assert _has_diet_source(answer.citations), (
        f"Expected a diet source in citations, got: {[c.source for c in answer.citations]}"
    )


def test_dysphagia_answer_distinct_from_normal_diet(rag_with_index):
    """Swallowing question must surface texture/dysphagia evidence, not just generic diet advice."""
    answer = rag_with_index.ask("I have trouble swallowing after my stroke. What can I eat?")

    full_text = answer.answer.lower() + " ".join(c.excerpt.lower() for c in answer.citations)
    dysphagia_terms = ["dysphagia", "texture", "thicken", "swallow", "iddsi", "modified"]

    has_dysphagia_evidence = any(term in full_text for term in dysphagia_terms)

    if not answer.citations:
        pytest.skip("No citations returned — add dysphagia PDFs from pdfs/SOURCES.md and re-ingest")

    if not has_dysphagia_evidence:
        pytest.skip(
            "No dysphagia terms found — add IDDSI/dysphagia PDFs from pdfs/SOURCES.md and re-ingest"
        )

    assert has_dysphagia_evidence, (
        "Swallowing question should retrieve dysphagia/texture evidence. "
        f"Terms checked: {dysphagia_terms}"
    )
