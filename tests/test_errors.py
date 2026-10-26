import urllib.error

import pytest
from fastapi.testclient import TestClient

from medical_rag.config import Settings
from medical_rag.errors import user_error
from medical_rag.server import create_app


@pytest.mark.parametrize("failure,status", [
    (RuntimeError("provider rejected secret-key at /private/patient-data"), 400),
    (FileNotFoundError("/private/patient-data/index.json"), 409),
    (ValueError("invalid input: secret-key"), 400),
    (OSError("database failure /private/patient-data"), 500),
])
def test_ask_masks_failures_and_logs_details(tmp_path, monkeypatch, caplog, failure, status):
    def fail(self, **kwargs):
        raise failure

    monkeypatch.setattr("medical_rag.server.StrokeRAG.ask", fail)
    settings = Settings(root_dir=tmp_path, corpus_dir=tmp_path,
                        index_path=tmp_path / "index.json", embedding_backend="hash")
    client = TestClient(create_app(settings))
    response = client.post("/ask", json={"question": "Hello"})
    assert response.status_code == status
    assert "secret-key" not in response.text
    assert "/private/patient-data" not in response.text
    assert str(failure) in caplog.text
    assert isinstance(response.json()["detail"], str)


def test_validation_does_not_echo_input(tmp_path):
    settings = Settings(root_dir=tmp_path, corpus_dir=tmp_path,
                        index_path=tmp_path / "index.json", embedding_backend="hash")
    client = TestClient(create_app(settings))
    response = client.post("/ask", json={"question": {"private": "secret-patient-data"}})
    assert response.status_code == 422
    assert "secret-patient-data" not in response.text
    assert "check your question" in response.json()["detail"]


@pytest.mark.parametrize("code,phrase", [(401, "administrator"), (403, "administrator"),
                                         (429, "usage limit"), (503, "try again")])
def test_provider_errors_get_safe_actionable_messages(code, phrase):
    underlying = urllib.error.HTTPError("https://private-provider", code, "secret", {}, None)
    error = RuntimeError("raw provider response includes secret")
    error.__cause__ = underlying
    message = user_error(error)
    assert phrase in message.lower()
    assert "secret" not in message
    assert "private-provider" not in message
