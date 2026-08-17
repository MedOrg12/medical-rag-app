from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com"
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} must be set")
    return value


@dataclass(frozen=True)
class DeployApiSettings:
    state_dir: Path
    audience: str
    repository: str
    ref: str
    environment: str
    workflow_ref: str
    repository_id: str
    event_name: str = "push"
    max_token_age_seconds: int = 300

    @classmethod
    def from_env(cls) -> DeployApiSettings:
        return cls(
            state_dir=Path(os.getenv("DEPLOY_STATE_DIR", "/var/lib/medical-rag-deploy")),
            audience=_required_env("DEPLOY_OIDC_AUDIENCE"),
            repository=_required_env("DEPLOY_GITHUB_REPOSITORY"),
            repository_id=_required_env("DEPLOY_GITHUB_REPOSITORY_ID"),
            ref=os.getenv("DEPLOY_GITHUB_REF", "refs/heads/main"),
            environment=os.getenv("DEPLOY_GITHUB_ENVIRONMENT", "production"),
            workflow_ref=_required_env("DEPLOY_GITHUB_WORKFLOW_REF"),
            event_name=os.getenv("DEPLOY_GITHUB_EVENT_NAME", "push"),
            max_token_age_seconds=int(os.getenv("DEPLOY_MAX_TOKEN_AGE_SECONDS", "300")),
        )


class TokenValidator(Protocol):
    def validate(self, token: str) -> dict[str, Any]: ...


class GitHubOidcValidator:
    def __init__(self, settings: DeployApiSettings) -> None:
        self.settings = settings
        self.jwks = jwt.PyJWKClient(
            f"{GITHUB_OIDC_ISSUER}/.well-known/jwks",
            cache_keys=True,
            lifespan=3600,
        )

    def validate(self, token: str) -> dict[str, Any]:
        try:
            key = self.jwks.get_signing_key_from_jwt(token).key
        except jwt.exceptions.PyJWKClientConnectionError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Deployment identity provider is unavailable",
            ) from exc
        except jwt.PyJWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid deployment identity",
            ) from exc

        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self.settings.audience,
                issuer=GITHUB_OIDC_ISSUER,
                options={
                    "require": [
                        "aud",
                        "exp",
                        "iat",
                        "iss",
                        "jti",
                        "repository",
                        "ref",
                        "sub",
                    ]
                },
            )
        except jwt.PyJWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid deployment identity",
            ) from exc

        expected = {
            "repository": self.settings.repository,
            "ref": self.settings.ref,
            "environment": self.settings.environment,
            "workflow_ref": self.settings.workflow_ref,
            "event_name": self.settings.event_name,
        }
        if any(claims.get(name) != value for name, value in expected.items()):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Deployment identity is not authorized",
            )
        if str(claims.get("repository_id")) != self.settings.repository_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Deployment repository identity is not authorized",
            )

        now = int(time.time())
        issued_at = claims.get("iat")
        if not isinstance(issued_at, int) or now - issued_at > self.settings.max_token_age_seconds:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Deployment identity is too old",
            )
        return claims


class DeployRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class DeployResponse(BaseModel):
    deployment_id: str
    state: str


def _atomic_json_create(path: Path, payload: dict[str, Any]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(path, flags, 0o640)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return True


def create_app(
    settings: DeployApiSettings | None = None,
    validator: TokenValidator | None = None,
) -> FastAPI:
    app_settings = settings or DeployApiSettings.from_env()
    token_validator = validator or GitHubOidcValidator(app_settings)
    for directory in ("pending", "processing", "receipts", "status"):
        (app_settings.state_dir / directory).mkdir(parents=True, exist_ok=True)
    app = FastAPI(
        title="Medical RAG Deployment Agent",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    def authorize(authorization: str = Header(default="")) -> dict[str, Any]:
        scheme, separator, token = authorization.partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Bearer deployment identity required",
            )
        claims = token_validator.validate(token)
        claims["_raw_token"] = token
        return claims

    @app.get("/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(
        "/deploy",
        response_model=DeployResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def deploy(
        request: DeployRequest,
        claims: dict[str, Any] = Depends(authorize),  # noqa: B008
    ) -> DeployResponse:
        if not DIGEST_RE.fullmatch(request.digest):
            raise HTTPException(status_code=422, detail="Invalid image digest")

        deployment_id = hashlib.sha256(str(claims["jti"]).encode()).hexdigest()[:32]
        payload = {
            "deployment_id": deployment_id,
            "digest": request.digest,
            "oidc_token": claims["_raw_token"],
            "requested_at": int(time.time()),
            "github": {
                "actor": claims.get("actor"),
                "repository": claims["repository"],
                "run_id": claims.get("run_id"),
                "run_attempt": claims.get("run_attempt"),
                "sha": claims.get("sha"),
                "workflow_ref": claims.get("workflow_ref"),
            },
        }
        pending_path = app_settings.state_dir / "pending" / f"{deployment_id}.json"
        status_path = app_settings.state_dir / "status" / f"{deployment_id}.json"
        receipt_path = app_settings.state_dir / "receipts" / f"{deployment_id}.json"
        receipt_created = _atomic_json_create(
            receipt_path,
            {"deployment_id": deployment_id, "digest": request.digest},
        )
        if not receipt_created:
            try:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError) as exc:
                raise HTTPException(
                    status_code=409, detail="Deployment request already used"
                ) from exc
            if receipt.get("digest") != request.digest:
                raise HTTPException(status_code=409, detail="Deployment identity already used")
            candidates = (
                (status_path, None),
                (app_settings.state_dir / "processing" / pending_path.name, "deploying"),
                (pending_path, "queued"),
            )
            existing = next((item for item in candidates if item[0].exists()), None)
            if existing is None:
                return DeployResponse(deployment_id=deployment_id, state="unknown")
            try:
                recorded = json.loads(existing[0].read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError) as exc:
                raise HTTPException(
                    status_code=409, detail="Deployment request already used"
                ) from exc
            return DeployResponse(
                deployment_id=deployment_id,
                state=str(recorded.get("state") or existing[1] or "unknown"),
            )
        if not _atomic_json_create(pending_path, payload):
            raise HTTPException(status_code=500, detail="Unable to queue deployment")
        return DeployResponse(deployment_id=deployment_id, state="queued")

    @app.get("/deploy/{deployment_id}", response_model=DeployResponse)
    def deployment_status(
        deployment_id: str,
        _claims: dict[str, Any] = Depends(authorize),  # noqa: B008
    ) -> DeployResponse:
        if not re.fullmatch(r"[0-9a-f]{32}", deployment_id):
            raise HTTPException(status_code=404, detail="Deployment not found")
        for directory, default_state in (
            ("status", None),
            ("processing", "deploying"),
            ("pending", "queued"),
        ):
            path = app_settings.state_dir / directory / f"{deployment_id}.json"
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                continue
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=500, detail="Invalid deployment state") from exc
            return DeployResponse(
                deployment_id=deployment_id,
                state=str(payload.get("state") or default_state or "unknown"),
            )
        raise HTTPException(status_code=404, detail="Deployment not found")

    return app
