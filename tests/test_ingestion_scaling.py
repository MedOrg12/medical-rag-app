from medical_rag.config import Settings
from medical_rag.pipeline import StrokeRAG


def _settings(tmp_path, corpus):
    return Settings(
        root_dir=tmp_path,
        corpus_dir=corpus,
        index_path=tmp_path / ".rag" / "index.json",
        chunk_size_chars=300,
        chunk_overlap_chars=40,
        manifest_path=tmp_path / ".rag" / "manifest.sqlite",
        extraction_cache_dir=tmp_path / ".rag" / "extracted",
    )


def test_ingest_skips_unchanged_corpus_after_first_index(tmp_path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "stroke.txt").write_text(
        "Stroke symptoms can include face drooping, arm weakness, and speech difficulty.",
        encoding="utf-8",
    )
    rag = StrokeRAG(_settings(tmp_path, corpus))

    first = rag.ingest()
    second = rag.ingest()

    assert first.skipped_unchanged is False
    assert "manifest_seconds" in first.timings
    assert first.timings["total_seconds"] >= first.timings["manifest_seconds"]
    assert second.skipped_unchanged is True
    assert second.files_changed == 0
    assert second.chunks == first.chunks
    assert (tmp_path / ".rag" / "manifest.sqlite").exists()
    assert any((tmp_path / ".rag" / "extracted").iterdir())


def test_ingest_deduplicates_identical_files(tmp_path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    content = "Dysphagia is common after stroke and requires swallowing screening."
    (corpus / "a.txt").write_text(content, encoding="utf-8")
    (corpus / "b.txt").write_text(content, encoding="utf-8")
    rag = StrokeRAG(_settings(tmp_path, corpus))

    report = rag.ingest()

    assert report.files_discovered == 2
    assert report.duplicate_files == 1
    assert report.documents == 1


def test_requested_qdrant_rebuild_runs_even_when_nothing_changed(monkeypatch, tmp_path) -> None:
    import dataclasses

    import medical_rag.pipeline as pipeline
    from medical_rag.vector_store import IngestStats

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "stroke.txt").write_text("Stroke symptoms include arm weakness.", encoding="utf-8")
    ingested: list[int] = []

    class _Store:
        def chunk_count(self) -> int:
            return 1

    def fake_ingest(settings, chunks, embedding_model):
        ingested.append(len(chunks))
        return _Store(), IngestStats(chunks_total=len(chunks), chunks_embedded=len(chunks))

    monkeypatch.setattr(pipeline, "ingest_vector_store", fake_ingest)
    monkeypatch.setattr(pipeline, "vector_store_exists", lambda settings: True)
    monkeypatch.setattr(pipeline, "load_vector_store", lambda settings: _Store())
    settings = dataclasses.replace(_settings(tmp_path, corpus), vector_store_backend="qdrant")

    StrokeRAG(settings).ingest()
    unchanged = StrokeRAG(settings).ingest()
    rebuild = StrokeRAG(dataclasses.replace(settings, qdrant_recreate_collection=True)).ingest()

    assert unchanged.skipped_unchanged is True
    assert rebuild.skipped_unchanged is False
    assert rebuild.files_from_cache == 1, "a rebuild without --force reuses extracted text"
    assert ingested == [1, 1]
