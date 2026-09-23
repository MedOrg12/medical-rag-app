from __future__ import annotations

from fastapi.testclient import TestClient

from medical_rag.config import Settings
from medical_rag.server import create_app


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
