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


def test_parallel_chunking_matches_sequential(tmp_path) -> None:
    from medical_rag.ingestion import ExtractedDocument, SourceFile
    from medical_rag.pipeline import _chunk_documents
    from medical_rag.types import PageText

    documents = [
        ExtractedDocument(
            source=SourceFile(path=tmp_path / f"d{n}.pdf", sha256=f"{n:064d}", size=n, mtime_ns=n),
            pages=[
                PageText(
                    source_id=f"d{n}.pdf",
                    source_path=str(tmp_path / f"d{n}.pdf"),
                    title=f"Doc {n}",
                    page_number=page,
                    text=" ".join(f"Sentence {n}.{page}.{i} about stroke care." for i in range(40)),
                )
                for page in range(1, 4)
            ],
        )
        for n in range(6)
    ]

    sequential = _chunk_documents(documents, chunk_size_chars=300, chunk_overlap_chars=40, workers=1)
    parallel = _chunk_documents(documents, chunk_size_chars=300, chunk_overlap_chars=40, workers=3)

    assert parallel == sequential
    assert sum(len(chunks) for chunks in parallel) > len(documents)
