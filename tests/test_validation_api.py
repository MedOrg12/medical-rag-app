import time
from unittest.mock import patch

from fastapi.testclient import TestClient

from medical_rag.config import Settings
from medical_rag.server import create_app


def test_background_screening_returns_results_without_ingesting(tmp_path):
    settings = Settings(root_dir=tmp_path, corpus_dir=tmp_path,
                        index_path=tmp_path / "index.json", embedding_backend="hash")
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
                        index_path=tmp_path / "index.json", embedding_backend="hash")))
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
