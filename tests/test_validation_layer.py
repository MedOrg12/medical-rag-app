import json
import threading
import time
import urllib.error
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from medical_rag.pipeline import StrokeRAG
from medical_rag.validation import (
    AbstractValidator,
    ValidationDecision,
    _parse_decision,
    extract_abstract_details,
    screen_pages,
)
from tests.test_validation import ABSTRACT, pages, settings


def decision(value="accept", confidence=.9):
    return ValidationDecision(value, "Based on the abstract", confidence,
                              {"accept": "in_scope", "reject": "out_of_scope", "uncertain": "insufficient_information"}[value], ["stroke"])


def pdf(config, name="study.pdf"):
    import fitz
    config.corpus_dir.mkdir(exist_ok=True)
    document = fitz.open()
    document.new_page().insert_textbox(fitz.Rect(40, 40, 550, 700), "Abstract\n" + ABSTRACT + "\nIntroduction\nBody")
    document.save(config.corpus_dir / name)
    document.close()


@pytest.mark.parametrize("value,confidence,action", [("accept", .9, "accept"), ("reject", .9, "reject"),
                                                     ("accept", .5, "needs_review"), ("reject", .5, "needs_review"),
                                                     ("uncertain", .99, "needs_review")])
def test_confidence_routes_and_audits(tmp_path, monkeypatch, value, confidence, action):
    monkeypatch.setattr(AbstractValidator, "_request", lambda *_: decision(value, confidence))
    validator = AbstractValidator(settings(tmp_path))
    result = validator.validate(pages("Abstract\n" + ABSTRACT))
    assert result.action == action
    assert result.confidence == confidence
    assert result.timestamp and result.file_hash and result.abstract_hash and result.criteria_version
    with validator.store.connect() as db:
        event = json.loads(db.execute("SELECT payload FROM audit_v2").fetchone()[0])
    assert event["action"] == action
    assert bool(validator.store.list_reviews()) == (action == "needs_review")


def test_missing_and_truncated_abstract_skip_provider(tmp_path, monkeypatch):
    request = MagicMock(side_effect=AssertionError("Provider must not be called"))
    monkeypatch.setattr(AbstractValidator, "_request", request)
    validator = AbstractValidator(settings(tmp_path))
    assert validator.validate(pages("No abstract")).reason_code == "no_abstract_found"
    result = validator.validate(pages("Summary\n" + "a" * 4000))
    assert result.truncated and result.reason_code == "abstract_truncated"
    assert result.action == "needs_review"
    assert request.call_count == 0
    extraction = extract_abstract_details(pages("Abstract\n" + ABSTRACT))
    assert extraction.method == "heading" and extraction.page == 1


@pytest.mark.parametrize("override", [{"confidence": True}, {"confidence": float('nan')},
                                      {"confidence": -1}, {"topics": ["a"] * 9},
                                      {"reason": "x" * 501}, {"extra": 1}, {"reason_code": "out_of_scope"}])
def test_schema_rejects_invalid_values(override):
    with pytest.raises((ValueError, TypeError)):
        _parse_decision(asdict(decision()) | override)


def test_malformed_retries_once_and_recovers(tmp_path, monkeypatch):
    request = MagicMock(side_effect=[ValueError("malformed"), decision()])
    monkeypatch.setattr(AbstractValidator, "_request", request)
    assert AbstractValidator(settings(tmp_path)).validate(pages("Abstract\n" + ABSTRACT)).action == "accept"
    assert request.call_count == 2


@pytest.mark.parametrize("status,expected,calls", [(429, "rate_limited", 3), (503, "provider_unavailable", 3),
                                                  (401, "provider_configuration", 1), (404, "provider_configuration", 1)])
def test_provider_retry_budget_and_failure_not_cached(tmp_path, monkeypatch, status, expected, calls):
    request = MagicMock(side_effect=urllib.error.HTTPError("https://provider", status, "secret", {"Retry-After": "2"}, None))
    sleep = MagicMock()
    monkeypatch.setattr(AbstractValidator, "_request", request)
    monkeypatch.setattr("medical_rag.validation.time.sleep", sleep)
    config = replace(settings(tmp_path), validation_max_retries=2)
    validator = AbstractValidator(config)
    result = validator.validate(pages("Abstract\n" + ABSTRACT))
    assert result.reason_code == expected and result.action == "needs_review"
    assert request.call_count == calls
    assert validator.store.get(result.cache_key) is None
    assert "secret" not in result.reason
    if status in {429, 503}:
        assert sleep.call_count == 2 and sleep.call_args_list[0].args[0] >= 2


def test_retry_after_long_wait_is_deferred(tmp_path, monkeypatch):
    request = MagicMock(side_effect=urllib.error.HTTPError("https://provider", 429, "busy", {"Retry-After": "3600"}, None))
    sleep = MagicMock()
    monkeypatch.setattr(AbstractValidator, "_request", request)
    monkeypatch.setattr("medical_rag.validation.time.sleep", sleep)
    result = AbstractValidator(replace(settings(tmp_path), validation_max_retries=2)).validate(pages("Abstract\n" + ABSTRACT))
    assert result.reason_code == "rate_limited"
    assert request.call_count == 1 and sleep.call_count == 0


def test_cache_invalidates_for_file_criteria_model_and_schema_inputs(tmp_path, monkeypatch):
    request = MagicMock(return_value=decision())
    monkeypatch.setattr(AbstractValidator, "_request", request)
    config = settings(tmp_path)
    source = pages("Abstract\n" + ABSTRACT)
    validator = AbstractValidator(config)
    first = validator.validate(source, file_hash="file-one")
    second = validator.validate(source, file_hash="file-one")
    assert second.cache_hit and first.cache_key == second.cache_key and request.call_count == 1
    validator.validate(source, file_hash="file-two")
    for changes in [{"validation_scope": "Other scope"}, {"validation_model": "other-model"},
                    {"validation_threshold": .99}, {"validation_max_abstract_chars": 3500},
                    {"validation_language_policy": "English only"}]:
        AbstractValidator(replace(config, **changes)).validate(source, file_hash="file-one")
    assert request.call_count == 7
    validator.validate(source, file_hash="file-one", force=True)
    assert request.call_count == 8


def test_manual_review_is_durable_and_scoped_to_criteria(tmp_path, monkeypatch):
    request = MagicMock(return_value=decision("uncertain"))
    monkeypatch.setattr(AbstractValidator, "_request", request)
    config = settings(tmp_path)
    validator = AbstractValidator(config)
    source = pages("Abstract\n" + ABSTRACT)
    pending = validator.validate(source)
    validator.store.review(pending.review_id, "accept", "Reviewer A", "Relevant human stroke study")
    reopened = AbstractValidator(config)
    approved = reopened.validate(source)
    assert approved.action == "accept" and approved.manual_override
    assert approved.decision == "uncertain" and approved.reason_code == "insufficient_information"
    assert approved.reviewer == "Reviewer A" and approved.reviewed_at
    assert request.call_count == 1
    item = reopened.store.inspect(pending.review_id)
    assert item["reviewer"] == "Reviewer A" and item["abstract"] == ABSTRACT.strip()
    changed = AbstractValidator(replace(config, validation_scope="New scope")).validate(source)
    assert changed.action == "needs_review" and not changed.manual_override
    reopened.store.review(pending.review_id, "reject", "Reviewer B", "Reviewed again")
    assert reopened.validate(source).action == "reject"
    reopened.store.reset(pending.review_id)
    assert reopened.validate(source, force=True).action == "needs_review"


@pytest.mark.parametrize("mode,accepted_count", [("off", 1), ("report_only", 1), ("enforce", 0)])
def test_rollout_modes(tmp_path, monkeypatch, mode, accepted_count):
    request = MagicMock(return_value=decision("reject"))
    monkeypatch.setattr(AbstractValidator, "_request", request)
    config = replace(settings(tmp_path), validation_enabled=False, validation_mode=mode)
    accepted, results = screen_pages(pages("Abstract\n" + ABSTRACT), config)
    assert len(accepted) == accepted_count
    assert request.call_count == (0 if mode == "off" else 1)
    assert bool(results) == (mode != "off")


@pytest.mark.parametrize("backend", ["json", "qdrant"])
@pytest.mark.parametrize("incremental", [False, True])
def test_outage_preserves_existing_vectors_even_after_accepted_document(tmp_path, monkeypatch, backend, incremental):
    if backend == "qdrant":
        from tests.test_vector_store import _use_fake_qdrant
        _use_fake_qdrant(monkeypatch)
    config = replace(settings(tmp_path), vector_store_backend=backend)
    if incremental:
        config = replace(config, manifest_path=tmp_path / "manifest.sqlite", extraction_cache_dir=tmp_path / "extracted")
    pdf(config)
    monkeypatch.setattr(AbstractValidator, "_request", lambda *_: decision())
    rag = StrokeRAG(config)
    rag.ingest()
    original = rag.sources()
    pdf(config, "second.pdf")
    request = MagicMock(side_effect=[decision(), TimeoutError("private provider diagnostics")])
    monkeypatch.setattr(AbstractValidator, "_request", request)
    with pytest.raises(RuntimeError, match="preserved"):
        rag.ingest(force=True)
    assert StrokeRAG(config).sources() == original


@pytest.mark.parametrize("backend", ["json", "qdrant"])
def test_true_dry_run_never_reaches_vector_store(tmp_path, monkeypatch, backend):
    config = replace(settings(tmp_path), vector_store_backend=backend)
    pdf(config)
    monkeypatch.setattr(AbstractValidator, "_request", lambda *_: decision())
    write = MagicMock(side_effect=AssertionError("Must not modify vectors"))
    monkeypatch.setattr("medical_rag.pipeline.ingest_vector_store", write)
    rag = StrokeRAG(config)
    rag.embedding_model.embed = MagicMock(side_effect=AssertionError("Must not embed"))
    report = rag.ingest(dry_run=True)
    assert report.dry_run and report.chunks == 0 and report.validation_results
    assert not config.index_path.exists() and write.call_count == 0
    assert rag.embedding_model.embed.call_count == 0


def test_validation_concurrency_and_queue_are_bounded(tmp_path, monkeypatch):
    lock = threading.Lock()
    active = peak = consumed = 0
    config = replace(settings(tmp_path), validation_concurrency=2)

    def assess(*_):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(.01)
        with lock:
            active -= 1
        return decision()

    def documents():
        nonlocal consumed
        for i in range(10):
            consumed += 1
            yield pages("Abstract\n" + ABSTRACT), str(i)

    monkeypatch.setattr(AbstractValidator, "_request", assess)
    results = AbstractValidator(config).validate_many(documents())
    next(results)
    assert consumed == 2
    assert len(list(results)) == 9
    assert peak <= 2


def test_manual_approval_reaches_normal_ingestion_on_next_run(tmp_path, monkeypatch):
    config = replace(settings(tmp_path), manifest_path=tmp_path / "manifest.sqlite",
                     extraction_cache_dir=tmp_path / "extracted")
    pdf(config)
    monkeypatch.setattr(AbstractValidator, "_request", lambda *_: decision("uncertain"))
    rag = StrokeRAG(config)
    first = rag.ingest()
    assert first.chunks == 0
    pending = next(iter(first.validation_results.values()))
    AbstractValidator(config).store.review(pending["review_id"], "accept", "Tester", "Confirmed relevance")
    second = StrokeRAG(config).ingest()
    assert second.documents == 1 and second.chunks > 0
    assert next(iter(second.validation_results.values()))["manual_override"]


def test_report_only_outage_still_ingests_and_text_bypasses_screening(tmp_path, monkeypatch):
    config = replace(settings(tmp_path), validation_enabled=False, validation_mode="report_only")
    pdf(config)
    monkeypatch.setattr(AbstractValidator, "_request", MagicMock(side_effect=TimeoutError()))
    result = StrokeRAG(config).ingest()
    assert result.documents == 1 and result.chunks > 0
    assert next(iter(result.validation_results.values()))["reason_code"] == "provider_unavailable"
    (config.corpus_dir / "notes.txt").write_text("Stroke rehabilitation includes swallowing support.")
    enforced = replace(config, validation_mode="enforce")
    monkeypatch.setattr(AbstractValidator, "_request", lambda *_: decision("reject"))
    result = StrokeRAG(enforced).ingest()
    assert result.documents == 1
    assert StrokeRAG(enforced).sources()[0]["source_id"] == "notes.txt"


def test_cli_review_workflow(tmp_path, monkeypatch, capsys):
    from medical_rag.cli import main
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RAG_EMBEDDING_BACKEND", "hash")
    config = settings(tmp_path)
    validator = AbstractValidator(config)
    pending = validator.validate(pages("No abstract"))
    assert main(["--index", str(config.index_path), "review", "list"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["id"] == pending.review_id
    assert main(["--index", str(config.index_path), "review", "approve", str(pending.review_id),
                 "--reviewer", "Test reviewer", "--reason", "Reviewed original PDF"]) == 0
    assert json.loads(capsys.readouterr().out)["action"] == "accept"
    assert validator.validate(pages("No abstract")).manual_override


def test_cli_validate_does_not_need_chat_generation_key(tmp_path, monkeypatch, capsys):
    from medical_rag.cli import main
    config = settings(tmp_path)
    pdf(config)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RAG_GENERATION_BACKEND", "api")
    for key in ("RAG_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    assert main(["--index", str(config.index_path), "validate", "--source", str(config.corpus_dir)]) == 0
    result = next(iter(json.loads(capsys.readouterr().out).values()))
    assert result["reason_code"] == "provider_configuration"
    assert not config.index_path.exists()


def test_prompt_and_parser_versions_invalidate_cache(tmp_path, monkeypatch):
    request = MagicMock(return_value=decision())
    monkeypatch.setattr(AbstractValidator, "_request", request)
    config = settings(tmp_path)
    source = pages("Abstract\n" + ABSTRACT)
    AbstractValidator(config).validate(source)
    monkeypatch.setattr("medical_rag.validation.PROMPT_VERSION", "new-prompt-version")
    AbstractValidator(config).validate(source)
    monkeypatch.setattr("medical_rag.validation.PARSER_VERSION", "new-parser-version")
    AbstractValidator(config).validate(source)
    assert request.call_count == 3


def test_explicit_environment_mode_overrides_legacy_flag(tmp_path, monkeypatch):
    from medical_rag.config import Settings
    monkeypatch.setenv("RAG_VALIDATE_PDFS", "true")
    monkeypatch.delenv("RAG_VALIDATION_MODE", raising=False)
    assert Settings.from_env(tmp_path).effective_validation_mode == "enforce"
    monkeypatch.setenv("RAG_VALIDATION_MODE", "off")
    assert Settings.from_env(tmp_path).effective_validation_mode == "off"
    monkeypatch.setenv("RAG_VALIDATION_MODE", "report_only")
    assert Settings.from_env(tmp_path).effective_validation_mode == "report_only"


def test_pdfs_without_text_keep_distinct_review_identifiers(tmp_path, monkeypatch):
    import fitz

    from medical_rag.validation import validate_source
    config = settings(tmp_path)
    config.corpus_dir.mkdir()
    for name in ("blank-one.pdf", "blank-two.pdf"):
        document = fitz.open()
        document.new_page()
        document.save(config.corpus_dir / name)
        document.close()
    request = MagicMock(side_effect=AssertionError("No provider call for blank PDFs"))
    monkeypatch.setattr(AbstractValidator, "_request", request)
    results = validate_source(config.corpus_dir.resolve(), config)
    # Byte-identical PDFs may be deduplicated; every returned identifier must be a real PDF.
    assert results and "unknown" not in results
    assert all(Path(path).is_file() and r["reason_code"] == "no_abstract_found" for path, r in results.items())
    assert request.call_count == 0


def test_structured_introduction_is_not_paper_body():
    content = ("Introduction\n" + ABSTRACT + "\nMethods\nAdult stroke registry.\n"
               "Results\nImproved swallowing.\nConclusion\nRelevant stroke findings.")
    result = extract_abstract_details(pages("Abstract\n" + content + "\nIntroduction\nActual paper body."))
    assert result.text.startswith("Introduction")
    assert "Relevant stroke findings." in result.text
    assert "Actual paper body" not in result.text
    assert not result.incomplete


def test_inline_keywords_and_translation_end_abstract():
    result = extract_abstract_details(pages("Abstract " + ABSTRACT + ". Keywords: stroke\nBackground Actual body"))
    assert "Keywords" not in result.text and "Actual body" not in result.text
    result = extract_abstract_details(pages("ABSTRACT: " + ABSTRACT + "\nRÉSUMÉ\nFrench translation"))
    assert "French translation" not in result.text


def test_structured_summary_without_abstract_heading():
    result = extract_abstract_details(pages("Title\nStudy Objectives: " + ABSTRACT
        + "\nMethods: Adult stroke patients.\nResults: Better function.\nConclusions: Promising.\nKeywords: stroke"))
    assert result.method == "structured_summary" and not result.incomplete
    assert "Better function" in result.text and "Keywords" not in result.text


def test_incomplete_column_fragment_is_held_without_provider_call(tmp_path, monkeypatch):
    request = MagicMock(side_effect=AssertionError("Incomplete abstract must be reviewed"))
    monkeypatch.setattr(AbstractValidator, "_request", request)
    fragment = "Abstract\nBackground: " + ABSTRACT + "\nMethods: We included adult stroke patients.\nCopyright 2020"
    result = AbstractValidator(settings(tmp_path)).validate(pages(fragment))
    assert result.reason_code == "incomplete_abstract" and result.action == "needs_review"
    assert request.call_count == 0


def test_layout_pipes_do_not_inflate_abstract_length():
    result = extract_abstract_details(pages("Abstract\n" + ABSTRACT.replace(" ", " | ") + "\nKeywords: stroke"))
    assert "|" not in result.text
    assert len(result.text) < len(ABSTRACT) + 10


def test_revalidation_resolves_and_supersedes_old_pending_items(tmp_path, monkeypatch):
    source = pages("Abstract\n" + ABSTRACT)
    config = settings(tmp_path)
    monkeypatch.setattr(AbstractValidator, "_request", lambda *_: decision("uncertain"))
    validator = AbstractValidator(config)
    first = validator.validate(source)
    assert len(validator.store.list_reviews()) == 1
    monkeypatch.setattr(AbstractValidator, "_request", lambda *_: decision())
    approved = validator.validate(source, force=True)
    assert approved.action == "accept" and not approved.manual_override
    assert validator.store.list_reviews() == []
    assert validator.store.inspect(first.review_id)["action"] == "resolved"
    monkeypatch.setattr(AbstractValidator, "_request", lambda *_: decision("uncertain"))
    validator.validate(source, force=True)
    updated = AbstractValidator(replace(config, validation_max_abstract_chars=5000)).validate(source)
    pending = validator.store.list_reviews()
    assert len(pending) == 1 and pending[0]["id"] == updated.review_id
    assert validator.store.inspect(first.review_id)["action"] == "superseded"
    assert len(validator.store.list_reviews(reason_code="insufficient_information")) == 1
    assert validator.store.list_reviews(reason_code="no_abstract_found") == []
    assert validator.store.list_reviews(offset=1) == []


def test_native_gemini_uses_schema_and_header_without_url_credentials(tmp_path, monkeypatch):
    config = replace(settings(tmp_path), api_base_url="https://generativelanguage.googleapis.com/v1beta/openai",
                     validation_model="gemini-flash", api_key="private-key")
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps({"candidates": [{"finishReason": "STOP",
        "content": {"parts": [{"text": "internal thought", "thought": True},
                              {"text": json.dumps(asdict(decision()))}]}}]}).encode()
    request = MagicMock(return_value=response)
    monkeypatch.setattr("medical_rag.validation.urllib.request.urlopen", request)
    result = AbstractValidator(config)._request(ABSTRACT)
    assert result.decision == "accept"
    sent = request.call_args.args[0]
    assert sent.full_url == "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash:generateContent"
    assert "private-key" not in sent.full_url
    assert sent.headers["X-goog-api-key"] == "private-key"
    body = json.loads(sent.data)
    assert body["generationConfig"]["responseJsonSchema"]["additionalProperties"] is False
    assert json.loads(body["contents"][0]["parts"][0]["text"])["abstract"] == ABSTRACT


@pytest.mark.parametrize("payload", [
    {"promptFeedback": {"blockReason": "SAFETY"}},
    {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": []}}]},
    {"candidates": [{"finishReason": "STOP", "content": {"parts": []}}]},
])
def test_native_gemini_does_not_accept_blocked_or_truncated_output(tmp_path, monkeypatch, payload):
    config = replace(settings(tmp_path), validation_transport="gemini_native")
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
    request = MagicMock(return_value=response)
    monkeypatch.setattr("medical_rag.validation.urllib.request.urlopen", request)
    result = AbstractValidator(config).validate(pages("Abstract\n" + ABSTRACT))
    assert result.action == "needs_review" and result.reason_code == "invalid_response"
    assert request.call_count == 2


def test_provider_circuit_defers_the_rest_of_the_batch_without_caching(tmp_path, monkeypatch):
    config = replace(settings(tmp_path), validation_failure_limit=2)
    request = MagicMock(side_effect=urllib.error.HTTPError("https://provider", 429, "limit", {}, None))
    monkeypatch.setattr(AbstractValidator, "_request", request)
    validator = AbstractValidator(config)
    source = pages("Abstract\n" + ABSTRACT)
    validator.validate(source, file_hash="one")
    validator.validate(source, file_hash="two")
    deferred = validator.validate(source, file_hash="three")
    assert request.call_count == 2
    assert deferred.reason_code == "provider_deferred" and deferred.action == "needs_review"
    assert validator.store.get(deferred.cache_key) is None
    monkeypatch.setattr(AbstractValidator, "_request", lambda *_: decision())
    assert AbstractValidator(config).validate(source, file_hash="three").action == "accept"


def test_success_does_not_reset_the_per_batch_failure_budget(tmp_path, monkeypatch):
    config = replace(settings(tmp_path), validation_failure_limit=2)
    request = MagicMock(side_effect=[TimeoutError(), decision(), TimeoutError()])
    monkeypatch.setattr(AbstractValidator, "_request", request)
    validator = AbstractValidator(config)
    source = pages("Abstract\n" + ABSTRACT)
    validator.validate(source, file_hash="a")
    assert validator.validate(source, file_hash="b").action == "accept"
    validator.validate(source, file_hash="c")
    assert validator.validate(source, file_hash="d").reason_code == "provider_deferred"
    assert request.call_count == 3
