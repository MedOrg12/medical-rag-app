import json
from dataclasses import replace
from unittest.mock import MagicMock

import pytest

from medical_rag.config import Settings
from medical_rag.pipeline import StrokeRAG
from medical_rag.types import PageText
from medical_rag.validation import AbstractValidator, ValidationDecision, extract_abstract

ABSTRACT = "We studied stroke rehabilitation and swallowing outcomes in adults. " * 5


def pages(text):
    return [PageText("study.pdf", "/study.pdf", "Study", 1, text)]


def settings(tmp_path):
    return Settings(
        root_dir=tmp_path,
        corpus_dir=tmp_path / "pdfs",
        index_path=tmp_path / "index.json",
        embedding_backend="hash",
        validation_enabled=True,
        api_key="test-key",
        validation_max_retries=0,
    )


def test_abstract_boundaries():
    assert (
        extract_abstract(pages("Title\nAbstract\n" + ABSTRACT + "\n1 Introduction\nBody"))
        == ABSTRACT.strip()
    )
    assert extract_abstract(pages("Title\nNo abstract")) is None
    assert len(extract_abstract(pages("Abstract\n" + "a" * 9000))) == 3000
    assert extract_abstract(pages("Summary: " + ABSTRACT)) == ABSTRACT.strip()


def test_structured_abstract():
    value = "Background\n" + ABSTRACT + "\nMethods\nTrial.\nResults\nBenefit."
    assert extract_abstract(pages("Abstract\n" + value + "\nKeywords: stroke")) == "\n".join(line.strip() for line in value.splitlines())


def test_api_request_and_cache(tmp_path, monkeypatch):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": json.dumps(
                            {"decision": "accept", "reason": "Relevant stroke study", "confidence": 0.9, "reason_code": "in_scope", "topics": ["stroke"]}
                        )
                    },
                }
            ]
        }
    ).encode()
    request = MagicMock(return_value=response)
    monkeypatch.setattr("urllib.request.urlopen", request)
    config = settings(tmp_path)
    validator = AbstractValidator(config)
    source = pages("Abstract\n" + ABSTRACT)
    assert validator.validate(source).decision == "accept"
    assert AbstractValidator(config).validate(source).decision == "accept"
    assert request.call_count == 1
    payload = json.loads(request.call_args.args[0].data)
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert payload["messages"][1]["content"] == json.dumps({"abstract": ABSTRACT.strip()})
    validator.validate(source, force=True)
    AbstractValidator(replace(config, validation_scope="Different scope")).validate(source)
    assert request.call_count == 3


def test_failures_are_excluded_and_retried(tmp_path, monkeypatch):
    request = MagicMock(side_effect=TimeoutError)
    monkeypatch.setattr("urllib.request.urlopen", request)
    validator = AbstractValidator(settings(tmp_path))
    for _ in range(2):
        assert validator.validate(pages("Abstract\n" + ABSTRACT)).action == "needs_review"
    assert request.call_count == 2
    assert validator.validate(pages("No abstract")).reason_code == "no_abstract_found"
    assert request.call_count == 2


def test_missing_key(tmp_path):
    result = AbstractValidator(replace(settings(tmp_path), api_key="")).validate(pages("Abstract\n" + ABSTRACT))
    assert result.action == "needs_review"
    assert result.reason_code == "provider_configuration"


@pytest.mark.parametrize("incremental", [False, True])
@pytest.mark.parametrize("backend", ["json", "qdrant"])
def test_ingestion_removes_rejected_pdf_and_reports_reason(tmp_path, monkeypatch, incremental, backend):
    import fitz

    config = replace(settings(tmp_path), vector_store_backend=backend)
    if backend == "qdrant":
        from tests.test_vector_store import _use_fake_qdrant

        _use_fake_qdrant(monkeypatch)
    config.corpus_dir.mkdir()
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(
        fitz.Rect(40, 40, 550, 700), "Abstract\n" + ABSTRACT + "\nIntroduction\nBody"
    )
    doc.save(config.corpus_dir / "study.pdf")
    doc.close()
    if incremental:
        config = replace(
            config,
            manifest_path=tmp_path / "manifest.sqlite",
            extraction_cache_dir=tmp_path / "extracted",
        )
    monkeypatch.setattr(
        AbstractValidator, "_request", lambda *_: ValidationDecision("accept", "Relevant")
    )
    rag = StrokeRAG(config)
    assert rag.ingest().documents == 1
    monkeypatch.setattr(
        AbstractValidator, "_request", lambda *_: ValidationDecision("reject", "Outside scope")
    )
    report = rag.ingest(force=True)
    assert report.documents == report.chunks == 0
    assert next(iter(report.validation_results.values()))["decision"] == "reject"
    assert rag.sources() == []
    assert StrokeRAG(config).sources() == []


def test_configuration_survives_clones(tmp_path, monkeypatch):
    monkeypatch.setenv("RAG_VALIDATE_PDFS", "true")
    monkeypatch.setenv("RAG_VALIDATION_SCOPE", "Stroke recovery")
    config = Settings.from_env(tmp_path).with_paths().with_ingestion_options(pdf_workers=2)
    assert config.validation_enabled
    assert config.validation_scope == "Stroke recovery"


@pytest.mark.parametrize(
    "choice",
    [
        {"finish_reason": "stop", "message": {"refusal": "Cannot classify", "content": None}},
        {"finish_reason": "length", "message": {"content": '{"decision":"accept","reason":"ok"}'}},
        {"finish_reason": "stop", "message": {"content": '{"decision":true,"reason":"ok"}'}},
        {"finish_reason": "stop", "message": {"content": "not json"}},
    ],
)
def test_invalid_api_results_never_accept(tmp_path, monkeypatch, choice):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps({"choices": [choice]}).encode()
    monkeypatch.setattr("urllib.request.urlopen", MagicMock(return_value=response))
    result = AbstractValidator(settings(tmp_path)).validate(pages("Abstract\n" + ABSTRACT))
    assert result.action == "needs_review"
    assert result.reason_code == "invalid_response"
