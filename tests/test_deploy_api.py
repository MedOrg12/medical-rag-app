from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from deploy_agent.api import DeployApiSettings, create_app

DIGEST = f"sha256:{'a' * 64}"


class FakeValidator:
    def __init__(self, claims: dict[str, Any] | None = None) -> None:
        self.claims = claims or {
            "jti": "unique-token-id",
            "repository": "MoCode98/medical-rag-app",
            "sha": "b" * 40,
            "workflow_ref": (
                "MoCode98/medical-rag-app/.github/workflows/ci-cd.yml@refs/heads/main"
            ),
        }

    def validate(self, _token: str) -> dict[str, Any]:
        return dict(self.claims)


def settings(tmp_path: Path) -> DeployApiSettings:
    return DeployApiSettings(
        state_dir=tmp_path,
        audience="https://example.test/internal/deploy",
        repository="MoCode98/medical-rag-app",
        repository_id="123",
        ref="refs/heads/main",
        environment="production",
        workflow_ref="MoCode98/medical-rag-app/.github/workflows/ci-cd.yml@refs/heads/main",
        event_name="push",
    )


def test_deploy_requires_bearer_token(tmp_path: Path) -> None:
    client = TestClient(create_app(settings(tmp_path), FakeValidator()))
    response = client.post("/deploy", json={"digest": DIGEST})
    assert response.status_code == 401


def test_deploy_queues_validated_digest_without_exposing_token(tmp_path: Path) -> None:
    client = TestClient(create_app(settings(tmp_path), FakeValidator()))
    response = client.post(
        "/deploy",
        headers={"Authorization": "Bearer secret-token"},
        json={"digest": DIGEST},
    )
    assert response.status_code == 202
    result = response.json()
    assert result["state"] == "queued"

    queued_path = tmp_path / "pending" / f"{result['deployment_id']}.json"
    queued = json.loads(queued_path.read_text())
    assert queued["digest"] == DIGEST
    assert queued["oidc_token"] == "secret-token"
    assert "oidc_token" not in result


def test_replayed_token_is_idempotent_for_same_digest(tmp_path: Path) -> None:
    client = TestClient(create_app(settings(tmp_path), FakeValidator()))
    headers = {"Authorization": "Bearer token"}
    first = client.post("/deploy", headers=headers, json={"digest": DIGEST})
    second = client.post("/deploy", headers=headers, json={"digest": DIGEST})
    assert second.status_code == 202
    assert second.json() == first.json()


def test_replayed_token_cannot_change_digest(tmp_path: Path) -> None:
    client = TestClient(create_app(settings(tmp_path), FakeValidator()))
    headers = {"Authorization": "Bearer token"}
    assert client.post("/deploy", headers=headers, json={"digest": DIGEST}).status_code == 202
    response = client.post(
        "/deploy",
        headers=headers,
        json={"digest": f"sha256:{'c' * 64}"},
    )
    assert response.status_code == 409


def test_request_rejects_tags_and_unknown_fields(tmp_path: Path) -> None:
    client = TestClient(create_app(settings(tmp_path), FakeValidator()))
    headers = {"Authorization": "Bearer token"}
    assert client.post("/deploy", headers=headers, json={"digest": "latest"}).status_code == 422
    assert (
        client.post(
            "/deploy",
            headers=headers,
            json={"digest": DIGEST, "image": "attacker/image"},
        ).status_code
        == 422
    )


def test_status_is_authenticated(tmp_path: Path) -> None:
    client = TestClient(create_app(settings(tmp_path), FakeValidator()))
    queued = client.post(
        "/deploy",
        headers={"Authorization": "Bearer token"},
        json={"digest": DIGEST},
    ).json()
    assert client.get(f"/deploy/{queued['deployment_id']}").status_code == 401
    response = client.get(
        f"/deploy/{queued['deployment_id']}",
        headers={"Authorization": "Bearer token"},
    )
    assert response.json()["state"] == "queued"
