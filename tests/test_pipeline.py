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


def test_diet_question_retrieves_diet_evidence_not_generic_prevention(tmp_path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "systems.txt").write_text(
        "A stroke system should support education about stroke awareness, risk factors, "
        "primary and secondary prevention, and recovery.",
        encoding="utf-8",
    )
    (corpus / "diet.txt").write_text(
        "After stroke, eating a dietary pattern rich in fruits and vegetables and lower in "
        "salt and saturated fat can support secondary prevention.",
        encoding="utf-8",
    )
    settings = Settings(
        root_dir=tmp_path,
        corpus_dir=corpus,
        index_path=tmp_path / ".rag" / "index.json",
        chunk_size_chars=350,
        chunk_overlap_chars=40,
    )
    rag = StrokeRAG(settings)

    rag.ingest()
    response = rag.ask("What should I eat after a stroke?", top_k=1)

    assert response.citations[0].source == "diet.txt"
    assert "fruits and vegetables" in response.answer
    assert "stroke awareness" not in response.answer


def test_diet_question_refuses_when_no_diet_evidence_is_indexed(tmp_path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "systems.txt").write_text(
        "A stroke system should support education about stroke awareness, risk factors, "
        "primary and secondary prevention, and recovery.",
        encoding="utf-8",
    )
    settings = Settings(
        root_dir=tmp_path,
        corpus_dir=corpus,
        index_path=tmp_path / ".rag" / "index.json",
        chunk_size_chars=350,
        chunk_overlap_chars=40,
    )
    rag = StrokeRAG(settings)

    rag.ingest()
    response = rag.ask("What should I eat after a stroke?", top_k=3)

    assert response.citations == []
    assert "could not find a relevant indexed passage" in response.answer


def test_diet_question_synthesizes_dysphagia_evidence(tmp_path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "rehab_guideline.txt").write_text(
        "Dysphagia Screening, Management, and Nutritional Support. Dysphagia is common "
        "after stroke, affecting 42% to 67% of patients within 3 days after stroke. "
        "Tube feeds via nasogastric route are reasonable for the first 2 to 3 weeks "
        "after stroke unless there is a strong reason to opt for gastrostomy placement.",
        encoding="utf-8",
    )
    settings = Settings(
        root_dir=tmp_path,
        corpus_dir=corpus,
        index_path=tmp_path / ".rag" / "index.json",
        chunk_size_chars=500,
        chunk_overlap_chars=40,
    )
    rag = StrokeRAG(settings)

    rag.ingest()
    response = rag.ask("What should I eat after a stroke?", top_k=3)

    assert "swallowing safety" in response.answer
    assert "nasogastric tube feeding" in response.answer
    assert "detailed normal-food meal plan" in response.answer
    assert "The most relevant indexed passages say" not in response.answer
