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
        chunks = list(chunks)
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


def test_parallel_discovery_matches_sequential_including_duplicate_choice(tmp_path) -> None:
    from medical_rag.ingestion import discover_source_files

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for index in range(12):
        (corpus / f"doc{index:02d}.txt").write_text(f"Stroke note {index % 5}.", encoding="utf-8")

    sequential = discover_source_files(corpus, workers=1)
    parallel = discover_source_files(corpus, workers=4)

    assert parallel == sequential
    assert [file.duplicate_of for file in parallel if file.duplicate_of][:1] == [str(corpus / "doc00.txt")]


def test_streamed_extraction_matches_sequential_and_keeps_document_order(tmp_path) -> None:
    from medical_rag.ingestion import (
        IngestionOptions,
        discover_source_files,
        iter_chunked_documents,
    )

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for n in range(10):
        text = " ".join(f"Sentence {n}.{i} about stroke care and rehabilitation." for i in range(60))
        (corpus / f"doc{n:02d}.txt").write_text(text, encoding="utf-8")
    files = discover_source_files(corpus)

    def run(workers: int, cache: str) -> list:
        return list(
            iter_chunked_documents(
                files,
                cache_dir=tmp_path / cache,
                options=IngestionOptions(pdf_workers=workers),
                chunk_size_chars=300,
                chunk_overlap_chars=40,
            )
        )

    sequential = run(1, "seq")
    parallel = run(3, "par")

    assert [d.source for d in parallel] == files
    assert [d.chunks for d in parallel] == [d.chunks for d in sequential]
    assert all(d.error is None and len(d.chunks) > 1 for d in parallel)
    assert all(d.from_cache for d in run(3, "par")), "a second pass reads the extraction cache"


def test_streamed_extraction_records_failures_and_continues(tmp_path) -> None:
    from medical_rag.ingestion import (
        IngestionOptions,
        discover_source_files,
        iter_chunked_documents,
    )

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "a.txt").write_text("Stroke symptoms include arm weakness.", encoding="utf-8")
    (corpus / "b.pdf").write_bytes(b"%PDF-1.4 not really a pdf")
    (corpus / "c.txt").write_text("Rapid treatment improves outcomes.", encoding="utf-8")

    documents = list(
        iter_chunked_documents(
            discover_source_files(corpus),
            cache_dir=tmp_path / "cache",
            options=IngestionOptions(pdf_workers=2),
            chunk_size_chars=300,
            chunk_overlap_chars=40,
        )
    )

    assert [d.source.path.name for d in documents] == ["a.txt", "b.pdf", "c.txt"]
    assert [d.error is not None for d in documents] == [False, True, False]


def test_manifest_batch_writes_drive_change_detection(tmp_path) -> None:
    from medical_rag.ingestion import ManifestStore, SourceFile

    manifest = ManifestStore(tmp_path / "manifest.sqlite")
    files = [SourceFile(path=tmp_path / f"d{n}.pdf", sha256=f"{n:064d}", size=n, mtime_ns=n) for n in range(3)]
    duplicate = SourceFile(path=tmp_path / "copy.pdf", sha256=files[0].sha256, size=0, mtime_ns=0, duplicate_of=str(files[0].path))
    settings = {"chunk_size_chars": 300, "chunk_overlap_chars": 40, "embedding_model": "m"}

    manifest.mark_indexed_many([(file, 2, 5, 0) for file in files], **settings)
    manifest.mark_duplicates([duplicate])
    edited = SourceFile(path=files[1].path, sha256=files[1].sha256, size=99, mtime_ns=files[1].mtime_ns)

    changed = manifest.changed_files([files[0], edited, files[2], duplicate], force=False, failed_only=False, **settings)

    assert changed == [edited]
    assert manifest.deleted_paths({str(file.path) for file in files}) == [str(duplicate.path)]


def test_ingest_never_reaches_the_vector_store_when_nothing_was_extracted(monkeypatch, tmp_path) -> None:
    import pytest

    import medical_rag.pipeline as pipeline

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "broken.pdf").write_bytes(b"%PDF-1.4 not really a pdf")
    monkeypatch.setattr(pipeline, "ingest_vector_store", lambda *args: pytest.fail("vector store touched"))

    with pytest.raises(ValueError, match="No supported text was extracted"):
        StrokeRAG(_settings(tmp_path, corpus)).ingest()
