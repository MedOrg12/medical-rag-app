from __future__ import annotations

import asyncio
from dataclasses import replace

import httpx

from medical_rag.config import Settings
from medical_rag.embedding_server import create_app
from medical_rag.embeddings import HashingEmbeddingModel


def _settings(tmp_path, **overrides: object) -> Settings:
    return replace(Settings.from_env(tmp_path), **overrides)


async def _request(
    app,
    method: str,
    path: str,
    *,
    json: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, path, json=json, headers=headers)


def _get(app, path: str) -> httpx.Response:
    return asyncio.run(_request(app, "GET", path))


def _post(
    app,
    path: str,
    *,
    json: dict[str, object],
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return asyncio.run(_request(app, "POST", path, json=json, headers=headers))


def test_embedding_server_health_shape(tmp_path) -> None:
    app = create_app(_settings(tmp_path), model=HashingEmbeddingModel(dimensions=8))

    response = _get(app, "/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "model_name": "hashing-bow-8",
        "device": "unknown",
        "dimensions": 8,
        "max_batch_size": 256,
    }


def test_embedding_server_embed_round_trip(tmp_path) -> None:
    app = create_app(_settings(tmp_path), model=HashingEmbeddingModel(dimensions=8))

    response = _post(
        app,
        "/embed",
        json={"texts": ["stroke symptoms", "arm weakness"], "model_name": "hashing-bow-8"},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["model_name"] == "hashing-bow-8"
    assert payload["dimensions"] == 8
    assert len(payload["embeddings"]) == 2
    assert all(len(vector) == 8 for vector in payload["embeddings"])


def test_embedding_server_rejects_model_name_mismatch(tmp_path) -> None:
    app = create_app(_settings(tmp_path), model=HashingEmbeddingModel(dimensions=8))

    response = _post(
        app,
        "/embed",
        json={"texts": ["stroke"], "model_name": "sentence-transformers:other"},
    )

    assert response.status_code == 409
    assert set(response.json()["error"]) == {"code", "message"}
    assert response.json()["error"]["code"] == "model_mismatch"


def test_embedding_server_rejects_batches_over_limit(tmp_path) -> None:
    app = create_app(
        _settings(tmp_path, embedding_service_max_batch_size=1),
        model=HashingEmbeddingModel(dimensions=8),
    )

    response = _post(app, "/embed", json={"texts": ["one", "two"]})

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "batch_too_large"


def test_embedding_server_requires_configured_bearer_token(tmp_path) -> None:
    app = create_app(
        _settings(tmp_path, embedding_service_token="secret"),
        model=HashingEmbeddingModel(dimensions=8),
    )

    missing = _post(app, "/embed", json={"texts": ["stroke"]})
    wrong = _post(
        app,
        "/embed",
        json={"texts": ["stroke"]},
        headers={"Authorization": "Bearer wrong"},
    )
    ok = _post(
        app,
        "/embed",
        json={"texts": ["stroke"]},
        headers={"Authorization": "Bearer secret"},
    )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert missing.json()["error"]["code"] == "unauthorized"
    assert set(wrong.json()["error"]) == {"code", "message"}
    assert ok.status_code == 200
