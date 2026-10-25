from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from medical_rag.config import Settings
from medical_rag.server import create_app


def test_patient_and_developer_views_are_separate(tmp_path) -> None:
    settings = Settings(
        root_dir=Path(__file__).resolve().parents[1],
        corpus_dir=tmp_path / "corpus",
        index_path=tmp_path / "index.json",
        embedding_backend="hash",
    )
    client = TestClient(create_app(settings))

    patient = client.get("/")
    developer = client.get("/dev")

    assert patient.status_code == developer.status_code == 200
    assert "Stroke Companion" in patient.text
    assert 'id="top-k"' not in patient.text
    assert 'id="eval-run-button"' not in patient.text
    assert 'id="ingest-button"' not in patient.text
    assert 'id="top-k"' in developer.text
    assert 'id="eval-run-button"' in developer.text
    assert 'id="ingest-button"' in developer.text
    assert client.get("/static/patient.js").status_code == 200
    assert client.get("/static/dev.js").status_code == 200
    assert client.get("/static/dev.css").status_code == 200
    assert client.get("/static/icons.svg").status_code == 200


def test_patient_status_checks_index_without_provider_call(tmp_path, monkeypatch) -> None:
    def unexpected_provider_call(*args, **kwargs):
        raise AssertionError("Patient status must not query Ollama")

    settings = Settings(
        root_dir=tmp_path,
        corpus_dir=tmp_path / "corpus",
        index_path=tmp_path / "index.json",
        embedding_backend="hash",
    )
    monkeypatch.setattr("medical_rag.server.list_ollama_models", unexpected_provider_call)
    client = TestClient(create_app(settings))

    assert client.get("/status").json() == {"ready": False}
    settings.index_path.touch()
    response = client.get("/status")
    assert response.status_code == 200
    assert response.json() == {"ready": True}


def test_missing_developer_view_returns_not_found(tmp_path) -> None:
    settings = Settings(
        root_dir=tmp_path,
        corpus_dir=tmp_path / "corpus",
        index_path=tmp_path / "index.json",
        embedding_backend="hash",
    )
    client = TestClient(create_app(settings))

    assert client.get("/dev").status_code == 404


def test_health_reports_api_configuration_without_secret(tmp_path) -> None:
    settings = Settings(
        root_dir=tmp_path,
        corpus_dir=tmp_path / "corpus",
        index_path=tmp_path / ".rag" / "index.json",
        embedding_backend="hash",
        generation_backend="api",
        api_key="secret-key",
        api_base_url="https://api.example.test/v1",
        api_generation_model="chat-model",
        api_embedding_model="embed-model",
        api_max_output_tokens=500,
        api_reasoning_effort="low",
        api_max_retries=3,
        request_timeout_seconds=90,
    )
    client = TestClient(create_app(settings))

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["generation_model"] == "api:chat-model"
    assert payload["api_base_url"] == "https://api.example.test/v1"
    assert payload["api_key_configured"] is True
    assert payload["api_generation_model"] == "chat-model"
    assert payload["api_embedding_model"] == "embed-model"
    assert payload["api_max_output_tokens"] == 500
    assert payload["api_reasoning_effort"] == "low"
    assert payload["api_max_retries"] == 3
    assert payload["request_timeout_seconds"] == 90
    assert "secret-key" not in response.text


def test_eval_questions_endpoint_returns_packaged_suite(tmp_path) -> None:
    settings = Settings(
        root_dir=tmp_path,
        corpus_dir=tmp_path / "corpus",
        index_path=tmp_path / ".rag" / "index.json",
        embedding_backend="hash",
    )
    client = TestClient(create_app(settings))

    response = client.get("/eval/questions")

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == 1
    assert any(item["id"] == "q2" for item in payload["questions"])


def test_eval_run_endpoint_scores_selected_question(tmp_path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "dysphagia_rehabilitation.txt").write_text(
        "Dysphagia after stroke is difficulty swallowing. Swallow rehabilitation may include "
        "texture modified foods and liquids for safer eating.",
        encoding="utf-8",
    )
    settings = Settings(
        root_dir=tmp_path,
        corpus_dir=corpus,
        index_path=tmp_path / ".rag" / "index.json",
        chunk_size_chars=400,
        chunk_overlap_chars=40,
        embedding_backend="hash",
    )
    client = TestClient(create_app(settings))

    ingest_response = client.post("/ingest", json={})
    eval_response = client.post(
        "/eval/run",
        json={"question_ids": ["q2"], "top_k": 3, "answer_mode": "patient"},
    )

    assert ingest_response.status_code == 200
    assert eval_response.status_code == 200
    payload = eval_response.json()
    assert payload["summary"]["total_questions"] == 1
    assert payload["results"][0]["question_id"] == "q2"
    assert payload["results"][0]["retrieval_hit"] is True


def test_health_survives_unreachable_remote_embedding_service(tmp_path) -> None:
    settings = Settings(
        root_dir=tmp_path,
        corpus_dir=tmp_path / "corpus",
        index_path=tmp_path / ".rag" / "index.json",
        embedding_backend="remote",
        embedding_service_url="http://127.0.0.1:9",
        embedding_service_timeout_seconds=1.0,
    )
    client = TestClient(create_app(settings))

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["embedding_backend"] == "remote"
    assert payload["active_embedding_model"] is None
    assert "127.0.0.1:9" in payload["embedding_model_error"]


def test_health_survives_unreachable_qdrant(tmp_path) -> None:
    settings = Settings(
        root_dir=tmp_path,
        corpus_dir=tmp_path / "corpus",
        index_path=tmp_path / ".rag" / "index.json",
        embedding_backend="hash",
        vector_store_backend="qdrant",
        qdrant_url="http://127.0.0.1:9",
        qdrant_timeout_seconds=1.0,
    )
    client = TestClient(create_app(settings))

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["vector_store_backend"] == "qdrant"
    assert payload["index_exists"] is None
    assert "127.0.0.1:9" in payload["vector_store_error"]

    ask = client.post("/ask", json={"question": "What is a stroke?"})
    assert ask.status_code == 400
    assert "Could not reach Qdrant" in ask.json()["detail"]


def test_sources_reports_vector_store_failure_as_json(tmp_path) -> None:
    settings = Settings(
        root_dir=tmp_path,
        corpus_dir=tmp_path / "corpus",
        index_path=tmp_path / ".rag" / "index.json",
        embedding_backend="hash",
    )
    client = TestClient(create_app(settings))

    with patch(
        "medical_rag.pipeline.StrokeRAG.sources", side_effect=TimeoutError("timed out")
    ):
        response = client.get("/sources")

    assert response.status_code == 503
    assert "timed out" in response.json()["detail"]


def test_unhandled_errors_return_json(tmp_path) -> None:
    settings = Settings(
        root_dir=tmp_path,
        corpus_dir=tmp_path / "corpus",
        index_path=tmp_path / ".rag" / "index.json",
        embedding_backend="hash",
    )
    client = TestClient(create_app(settings), raise_server_exceptions=False)

    with patch(
        "medical_rag.pipeline.StrokeRAG.ask", side_effect=TimeoutError("http://internal:6333")
    ):
        response = client.post("/ask", json={"question": "What is a stroke?"})

    assert response.status_code == 500
    assert "server log" in response.json()["detail"]
    assert "internal:6333" not in response.text
