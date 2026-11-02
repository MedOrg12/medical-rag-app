import time
from dataclasses import replace
from unittest.mock import patch

from fastapi.testclient import TestClient

from medical_rag.config import Settings
from medical_rag.server import create_app
from medical_rag.validation import AbstractValidator


def test_scanner_credentials_are_separate_from_generation(tmp_path):
    settings = Settings(root_dir=tmp_path, corpus_dir=tmp_path, index_path=tmp_path / "index.json",
                        api_base_url="https://api.openai.com/v1", api_key="openai-test-key",
                        validation_api_base_url="https://generativelanguage.googleapis.com/v1beta/openai",
                        validation_api_key="gemini-test-key")
    validator = AbstractValidator(settings)
    assert validator.settings.api_key == "gemini-test-key"
    assert validator.settings.api_base_url == settings.validation_api_base_url
    assert settings.api_key == "openai-test-key"
    assert not AbstractValidator(replace(settings, validation_api_key="")).settings.api_key


def test_background_screening_returns_results_without_ingesting(tmp_path):
    settings = Settings(root_dir=tmp_path, corpus_dir=tmp_path,
                        index_path=tmp_path / "index.json", embedding_backend="hash", api_key="test")
    client = TestClient(create_app(settings))
    report = {"paper.pdf": {"action": "needs_review", "reason_code": "no_abstract"}}
    with patch("medical_rag.server.validate_source", return_value=report) as scan:
        assert client.post("/validation/run", json={}).status_code == 200
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            status = client.get("/validation/status").json()
            if not status["running"]:
                break
            time.sleep(0.01)
        assert status["results"] == report
        scan.assert_called_once_with(tmp_path.resolve(), settings, False)
    assert not settings.index_path.exists()
    assert client.get("/validation/reviews").json() == []
    assert client.get("/validation/reviews/999").status_code == 404
    assert client.get("/validation/reviews?limit=0").status_code == 400


def test_screening_provider_failure_is_reported(tmp_path):
    client = TestClient(create_app(Settings(root_dir=tmp_path, corpus_dir=tmp_path,
                        index_path=tmp_path / "index.json", embedding_backend="hash", api_key="test")))
    with patch("medical_rag.server.validate_source", side_effect=RuntimeError("offline")):
        assert client.post("/validation/run", json={}).status_code == 200
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            status = client.get("/validation/status").json()
            if not status["running"]:
                break
            time.sleep(0.01)
        assert status["last_error"]
        assert status["results"] is None


def test_provider_selection_keeps_keys_separate(tmp_path):
    settings = Settings(root_dir=tmp_path, corpus_dir=tmp_path,
                        index_path=tmp_path / "index.json", embedding_backend="hash",
                        validation_provider="openai", validation_openai_api_key="openai-secret",
                        validation_gemini_api_key="gemini-secret")
    client = TestClient(create_app(settings))
    providers = client.get("/validation/providers")
    assert providers.json()["default"] == "openai"
    assert {p["id"] for p in providers.json()["providers"]} == {"openai", "gemini"}
    assert "secret" not in providers.text
    for provider, secret, host, transport in [
        ("openai", "openai-secret", "api.openai.com", "compatible"),
        ("gemini", "gemini-secret", "generativelanguage.googleapis.com", "gemini_native"),
    ]:
        with patch("medical_rag.server.validate_source", return_value={}) as scan:
            assert client.post("/validation/run", json={"provider": provider}).status_code == 200
            deadline = time.monotonic() + 3
            while client.get("/validation/status").json()["running"] and time.monotonic() < deadline:
                time.sleep(0.01)
            effective = AbstractValidator(scan.call_args.args[1]).settings
            assert effective.api_key == secret
            assert host in effective.api_base_url
            assert effective.validation_transport == transport
    assert client.post("/validation/run", json={"provider": "invalid"}).status_code == 422


def test_missing_provider_key_prevents_scan(tmp_path):
    settings = Settings(root_dir=tmp_path, corpus_dir=tmp_path,
                        index_path=tmp_path / "index.json", embedding_backend="hash",
                        api_key="openai-secret", validation_provider="gemini")
    client = TestClient(create_app(settings))
    with patch("medical_rag.server.validate_source") as scan:
        assert client.post("/validation/run", json={}).status_code == 400
        scan.assert_not_called()
