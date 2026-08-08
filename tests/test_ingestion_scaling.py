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
        embedding_cache_path=tmp_path / ".rag" / "embedding_cache.json",
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
