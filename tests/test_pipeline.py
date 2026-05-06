from medical_rag.config import Settings
from medical_rag.pipeline import StrokeRAG


def test_pipeline_ingests_text_and_answers(tmp_path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "stroke_notes.txt").write_text(
        "Stroke symptoms can include face drooping, arm weakness, and speech difficulty. "
        "Rapid emergency evaluation is important.",
        encoding="utf-8",
    )
    settings = Settings(
        root_dir=tmp_path,
        corpus_dir=corpus,
        index_path=tmp_path / ".rag" / "index.json",
        chunk_size_chars=300,
        chunk_overlap_chars=40,
    )
    rag = StrokeRAG(settings)

    report = rag.ingest()
    response = rag.ask("What are stroke symptoms?", top_k=1)

    assert report.chunks == 1
    assert "face drooping" in response.answer
    assert response.citations[0].source == "stroke_notes.txt"
