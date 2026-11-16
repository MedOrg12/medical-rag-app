import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from medical_rag.config import Settings
from medical_rag.curation import (
    CatalogConflictError,
    ConflictNote,
    DocumentMetadata,
    LibraryFilters,
    SourceCatalog,
    retrieval_scope,
    source_disagreements,
)
from medical_rag.embeddings import HashingEmbeddingModel
from medical_rag.llm import _user_prompt
from medical_rag.pipeline import StrokeRAG
from medical_rag.types import Chunk, SearchResult
from medical_rag.vector_store import VectorStore


@pytest.fixture
def settings(tmp_path):
    return Settings(root_dir=tmp_path, corpus_dir=tmp_path, index_path=tmp_path / "index.json", embedding_backend="hash", reranker_backend="none", source_catalog_path=tmp_path / "catalog.json")


def test_metadata_normalizes_tags_and_preserves_full_publication_date():
    metadata = DocumentMetadata(document_type="systematic_review", publication_date="2025-02-01", populations=["Adults", " adults "], topics=["Recovery"], jurisdiction="Canada", document_version="2.1")
    assert metadata.populations == ["adults"]
    assert metadata.topics == ["recovery"]
    assert metadata.publication_year == 2025
    assert metadata.status == "unreviewed"


@pytest.mark.parametrize("payload", [
    {"document_type": "automatically_verified"},
    {"publication_date": "2025-02-30"},
    {"publication_date": "2025-02-01", "publication_year": 2024},
    {"status": "withdrawn"},
    {"status": "superseded"},
    {"status": "current", "superseded_by": "other.pdf"},
    {"populations": [""]},
    {"source_path": "/private/document.pdf"},
])
def test_invalid_or_misleading_metadata_is_rejected(payload):
    with pytest.raises(ValueError):
        DocumentMetadata.model_validate(payload)


def test_catalog_optimistic_revision_and_atomic_save(tmp_path):
    path = tmp_path / "catalog.json"
    catalog = SourceCatalog(path)
    _, revision = catalog.snapshot()
    saved = catalog.save("guide.pdf", DocumentMetadata(document_type="guideline", status="current"), revision, {"guide.pdf"})
    assert saved["revision"] != revision
    assert SourceCatalog(path).snapshot()[0]["guide.pdf"].status == "current"
    with pytest.raises(CatalogConflictError):
        catalog.save("guide.pdf", DocumentMetadata(status="unreviewed"), revision, {"guide.pdf"})
    assert json.loads(path.read_text())["guide.pdf"]["status"] == "current"


def test_two_catalog_writers_cannot_overwrite_each_other(tmp_path):
    path = tmp_path / "catalog.json"
    first, second = SourceCatalog(path), SourceCatalog(path)
    revision = first.snapshot()[1]

    def save(catalog):
        try:
            catalog.save("guide.pdf", DocumentMetadata(status="current"), revision, {"guide.pdf"})
            return "saved"
        except CatalogConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(save, [first, second])) == ["conflict", "saved"]


def test_catalog_rejects_self_references_missing_sources_and_cycles(tmp_path):
    catalog = SourceCatalog(tmp_path / "catalog.json")
    revision = catalog.snapshot()[1]
    for replacement in ("a.pdf", "missing.pdf"):
        with pytest.raises(ValueError):
            catalog.save("a.pdf", DocumentMetadata(status="superseded", review_notes="New version", superseded_by=replacement), revision, {"a.pdf", "b.pdf"})
    with pytest.raises(KeyError):
        catalog.save("missing.pdf", DocumentMetadata(), revision, {"a.pdf"})
    saved = catalog.save("a.pdf", DocumentMetadata(status="superseded", review_notes="New version", superseded_by="b.pdf"), revision, {"a.pdf", "b.pdf"})
    with pytest.raises(ValueError, match="cycle"):
        catalog.save("b.pdf", DocumentMetadata(status="superseded", review_notes="New version", superseded_by="a.pdf"), saved["revision"], {"a.pdf", "b.pdf"})
    assert "b.pdf" not in catalog.snapshot()[0]


def test_retrieval_scope_uses_or_within_tags_and_and_between_fields():
    entries = {
        "canada.pdf": DocumentMetadata(document_type="guideline", populations=["adults"], topics=["recovery"], jurisdiction="Canada", status="current"),
        "child.pdf": DocumentMetadata(document_type="guideline", populations=["children"], status="current"),
        "old.pdf": DocumentMetadata(document_type="guideline", status="superseded", review_notes="Replaced"),
    }
    scope = LibraryFilters(document_types=["guideline", "trial"], populations=["Adults", "older adults"], topics=["recovery"], jurisdiction="canada", reviewed_only=True)
    assert retrieval_scope(entries, scope, None) == {"source_id": {"$in": ["canada.pdf"]}}
    assert retrieval_scope(entries, LibraryFilters(), None) == {"source_id": {"$nin": ["old.pdf"]}}
    assert retrieval_scope(entries, LibraryFilters(), {"source_id": "old.pdf"}) == {"source_id": {"$in": []}}
    assert retrieval_scope(entries, scope, {"source_id": "child.pdf", "section": "Recovery"}) == {"source_id": {"$in": []}, "section": "Recovery"}


def test_pipeline_excludes_inactive_sources_before_candidate_limit_and_without_reembedding(settings):
    model = HashingEmbeddingModel(dimensions=8)
    chunks = [Chunk(f"old-{i}", "Education pilot recovery reminders " * 10, {"source_id": "old.pdf"}) for i in range(65)]
    chunks.append(Chunk("current", "Education pilot recovery reminders.", {"source_id": "current.pdf"}))
    store = VectorStore.build(settings.index_path, chunks, model)
    store.save()
    original_mtime = settings.index_path.stat().st_mtime_ns
    rag = StrokeRAG(settings, embedding_model=model)
    rag._store = store
    revision = rag.library()["revision"]
    rag.curate_source("old.pdf", DocumentMetadata(document_type="guideline", status="withdrawn", review_notes="Withdrawn by publisher"), revision)
    answer = rag.ask("Education pilot recovery reminders", top_k=1)
    assert answer.citations[0].source == "current.pdf"
    assert settings.index_path.stat().st_mtime_ns == original_mtime
    with pytest.raises(ValueError, match="clinician"):
        rag.ask("Education pilot", library_filters={"include_inactive": True})
    historical = rag.ask("Education pilot", answer_mode="clinician", top_k=1, filters={"source_id": "old.pdf"}, library_filters={"include_inactive": True})
    assert historical.citations[0].status == "withdrawn"


def test_empty_curated_scope_does_not_fall_back_to_unfiltered_search(settings, monkeypatch):
    model = HashingEmbeddingModel(dimensions=8)
    store = VectorStore.build(settings.index_path, [Chunk("a", "Education pilot", {"source_id": "a.pdf"})], model)
    rag = StrokeRAG(settings, embedding_model=model)
    rag._store = store
    monkeypatch.setattr(store, "search", lambda **kwargs: pytest.fail("Empty scope must not call retrieval"))
    answer = rag.ask("Education pilot", library_filters={"document_types": ["guideline"]})
    assert not answer.citations and not answer.retrieved_evidence
    assert "couldn't find" in answer.answer


def test_edits_apply_to_existing_index_and_facets(settings):
    model = HashingEmbeddingModel(dimensions=8)
    rag = StrokeRAG(settings, embedding_model=model)
    rag._store = VectorStore.build(settings.index_path, [Chunk("a", "Education pilot.", {"source_id": "a.pdf"})], model)
    rag.curate_source("a.pdf", DocumentMetadata(document_type="local_protocol", populations=["Adults"], jurisdiction="Ontario", status="current"), rag.library()["revision"])
    library = rag.library()
    assert library["facets"]["populations"] == ["adults"]
    assert library["documents"][0]["metadata"]["document_type"] == "local_protocol"
    answer = rag.ask("Education pilot", library_filters={"document_types": ["local_protocol"], "populations": ["adults"]})
    assert answer.citations[0].document_type == "local_protocol"
    assert answer.citations[0].jurisdiction == "Ontario"


def test_disagreements_remain_visible_from_either_source_and_missing_counterpart_is_explicit():
    note = ConflictNote(with_source="b.pdf", topic="Reminders", source_position="Pilot A used daily reminders.", other_position="Pilot B used weekly reminders.", context="Different pilot populations; frequency superiority was not measured.")
    entries = {"a.pdf": DocumentMetadata(title="Pilot A", conflicts=[note]), "b.pdf": DocumentMetadata(title="Pilot B")}
    first = SearchResult(Chunk("a", "Daily reminders.", {"source_id": "a.pdf"}), 1.0, 1)
    second = SearchResult(Chunk("b", "Weekly reminders.", {"source_id": "b.pdf"}), 1.0, 2)
    partial = source_disagreements([second], entries)[0]
    assert partial["source_citation_ids"] == [] and partial["other_citation_ids"] == [1]
    assert partial["both_sources_retrieved"] is False
    both = source_disagreements([first, second], entries)[0]
    assert both["both_sources_retrieved"] is True
    assert both["source_citation_ids"] == [1] and both["other_citation_ids"] == [2]
    assert both["provenance"] == "curator_recorded"
    enriched = replace(first, chunk=replace(first.chunk, metadata={**first.chunk.metadata, "curated_conflicts": [both]}))
    assert "Curator-recorded context (not source text)" in _user_prompt("Compare reminders", [enriched], "clinician")
