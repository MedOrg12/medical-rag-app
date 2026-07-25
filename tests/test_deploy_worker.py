from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from deploy_agent import worker
from deploy_agent.worker import WorkerSettings

DIGEST = f"sha256:{'a' * 64}"
PREVIOUS_DIGEST = f"sha256:{'b' * 64}"
SHA = "c" * 40


class FakeValidator:
    def __init__(self, _settings: Any) -> None:
        pass

    def validate(self, token: str) -> dict[str, str]:
        assert token == "oidc-token"
        return {"sha": SHA}


def settings(tmp_path: Path) -> WorkerSettings:
    return WorkerSettings(
        state_dir=tmp_path / "state",
        compose_file=tmp_path / "compose.yaml",
        compose_env_file=tmp_path / ".deploy.env",
        service="medical-rag",
        image_repository="ghcr.io/mocode98/medical-rag-app",
        readiness_url="http://127.0.0.1:8000/ready",
        readiness_timeout_seconds=1,
    )


def queue_request(config: WorkerSettings) -> Path:
    path = config.state_dir / "pending" / "deployment.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "deployment_id": "deployment",
                "digest": DIGEST,
                "oidc_token": "oidc-token",
                "github": {"sha": SHA},
            }
        )
    )
    return path


def test_worker_revalidates_identity_and_deploys_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = settings(tmp_path)
    pending = queue_request(config)
    monkeypatch.setattr(worker, "GitHubOidcValidator", FakeValidator)
    monkeypatch.setattr(worker.DeployApiSettings, "from_env", lambda: object())
    calls: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        worker,
        "_deploy",
        lambda _settings, digest, revision=None: calls.append((digest, revision)),
    )

    worker.process_request(config, pending)

    assert calls == [(DIGEST, SHA)]
    result = json.loads((config.state_dir / "status" / "deployment.json").read_text())
    assert result["state"] == "healthy"
    assert "oidc_token" not in result


def test_readiness_failure_rolls_back_previous_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = settings(tmp_path)
    config.compose_env_file.write_text(f"IMAGE_DIGEST={PREVIOUS_DIGEST}\n")
    pending = queue_request(config)
    monkeypatch.setattr(worker, "GitHubOidcValidator", FakeValidator)
    monkeypatch.setattr(worker.DeployApiSettings, "from_env", lambda: object())
    calls: list[str] = []

    def deploy(_settings: WorkerSettings, digest: str, _revision: str | None = None) -> None:
        calls.append(digest)
        if digest == DIGEST:
            raise RuntimeError("not ready")

    monkeypatch.setattr(worker, "_deploy", deploy)
    worker.process_request(config, pending)

    assert calls == [DIGEST, PREVIOUS_DIGEST]
    result = json.loads((config.state_dir / "status" / "deployment.json").read_text())
    assert result["state"] == "rolled_back"
    assert result["rolled_back_to"] == PREVIOUS_DIGEST
