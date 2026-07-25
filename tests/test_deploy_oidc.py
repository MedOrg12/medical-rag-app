from __future__ import annotations

import time
from pathlib import Path

import jwt
import pytest
from fastapi import HTTPException

from deploy_agent.api import DeployApiSettings, GitHubOidcValidator


class StaticJwks:
    class Key:
        key = "test-secret"

    def get_signing_key_from_jwt(self, _token: str) -> Key:
        return self.Key()


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


def token(overrides: dict[str, object] | None = None) -> str:
    now = int(time.time())
    claims: dict[str, object] = {
        "iss": "https://token.actions.githubusercontent.com",
        "aud": "https://example.test/internal/deploy",
        "sub": "repo:MoCode98/medical-rag-app:environment:production",
        "exp": now + 300,
        "iat": now,
        "jti": "token-id",
        "repository": "MoCode98/medical-rag-app",
        "repository_id": "123",
        "ref": "refs/heads/main",
        "environment": "production",
        "workflow_ref": ("MoCode98/medical-rag-app/.github/workflows/ci-cd.yml@refs/heads/main"),
        "event_name": "push",
    }
    claims.update(overrides or {})
    return jwt.encode(claims, "test-secret", algorithm="HS256")


def validator(tmp_path: Path) -> GitHubOidcValidator:
    result = GitHubOidcValidator(settings(tmp_path))
    result.jwks = StaticJwks()  # type: ignore[assignment]
    return result


def test_oidc_claims_are_checked_after_signature_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claims = jwt.decode(
        token(),
        "test-secret",
        algorithms=["HS256"],
        audience="https://example.test/internal/deploy",
    )
    monkeypatch.setattr(
        jwt,
        "decode",
        lambda *_args, **_kwargs: claims,
    )
    claims = validator(tmp_path).validate("opaque")
    assert claims["repository_id"] == "123"


@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("repository", "attacker/repo"),
        ("repository_id", "999"),
        ("ref", "refs/heads/feature"),
        ("environment", "staging"),
        ("workflow_ref", "attacker/workflow@refs/heads/main"),
        ("event_name", "pull_request"),
    ],
)
def test_oidc_rejects_wrong_identity_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    claim: str,
    value: str,
) -> None:
    claims = jwt.decode(
        token({claim: value}),
        "test-secret",
        algorithms=["HS256"],
        audience="https://example.test/internal/deploy",
    )
    monkeypatch.setattr(jwt, "decode", lambda *_args, **_kwargs: claims)
    with pytest.raises(HTTPException) as error:
        validator(tmp_path).validate("opaque")
    assert error.value.status_code == 403
