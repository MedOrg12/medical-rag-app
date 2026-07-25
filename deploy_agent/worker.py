from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deploy_agent.api import DeployApiSettings, GitHubOidcValidator

DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class WorkerSettings:
    state_dir: Path
    compose_file: Path
    compose_env_file: Path
    service: str
    image_repository: str
    readiness_url: str
    readiness_timeout_seconds: int

    @classmethod
    def from_env(cls) -> WorkerSettings:
        return cls(
            state_dir=Path(os.getenv("DEPLOY_STATE_DIR", "/var/lib/medical-rag-deploy")),
            compose_file=Path(
                os.getenv("DEPLOY_COMPOSE_FILE", "/opt/medical-rag/compose.production.yaml")
            ),
            compose_env_file=Path(
                os.getenv(
                    "DEPLOY_COMPOSE_ENV_FILE",
                    "/var/lib/medical-rag-deploy/deploy.env",
                )
            ),
            service=os.getenv("DEPLOY_COMPOSE_SERVICE", "medical-rag"),
            image_repository=os.getenv(
                "DEPLOY_IMAGE_REPOSITORY",
                "ghcr.io/mocode98/medical-rag-app",
            ),
            readiness_url=os.getenv("DEPLOY_READINESS_URL", "http://127.0.0.1:8000/health"),
            readiness_timeout_seconds=int(os.getenv("DEPLOY_READINESS_TIMEOUT_SECONDS", "180")),
        )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _read_current_digest(path: Path) -> str | None:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("IMAGE_DIGEST="):
                digest = line.partition("=")[2].strip()
                return digest if DIGEST_RE.fullmatch(digest) else None
    except FileNotFoundError:
        pass
    return None


def _write_digest(path: Path, digest: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(f"IMAGE_DIGEST={digest}\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _compose(settings: WorkerSettings, *args: str) -> None:
    command = [
        "docker",
        "compose",
        "--env-file",
        str(settings.compose_env_file),
        "-f",
        str(settings.compose_file),
        *args,
    ]
    subprocess.run(command, check=True, timeout=600)


def _wait_ready(url: str, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = "not ready"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == 200:
                    payload = json.load(response)
                    if payload.get("status") == "ok":
                        return
                    last_error = f"unexpected health response: {payload!r}"
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last_error = str(exc)
        time.sleep(3)
    raise RuntimeError(f"readiness check failed: {last_error}")


def _image_revision(settings: WorkerSettings, digest: str) -> str:
    image = f"{settings.image_repository}@{digest}"
    result = subprocess.run(
        [
            "docker",
            "image",
            "inspect",
            image,
            "--format",
            '{{ index .Config.Labels "org.opencontainers.image.revision" }}',
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout.strip()


def _deploy(
    settings: WorkerSettings,
    digest: str,
    expected_revision: str | None = None,
) -> None:
    _write_digest(settings.compose_env_file, digest)
    _compose(settings, "pull", settings.service)
    if expected_revision and _image_revision(settings, digest) != expected_revision:
        raise RuntimeError("image revision does not match the authorized GitHub commit")
    _compose(settings, "up", "-d", "--no-deps", settings.service)
    _wait_ready(settings.readiness_url, settings.readiness_timeout_seconds)


def process_request(settings: WorkerSettings, pending_path: Path) -> None:
    processing_path = settings.state_dir / "processing" / pending_path.name
    status_path = settings.state_dir / "status" / pending_path.name
    processing_path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(pending_path, processing_path)
    request = json.loads(processing_path.read_text(encoding="utf-8"))
    digest = str(request.get("digest", ""))
    token = request.pop("oidc_token", None)
    try:
        if not DIGEST_RE.fullmatch(digest):
            raise ValueError("queued request contains an invalid digest")
        if not isinstance(token, str):
            raise ValueError("queued request has no deployment identity")
        claims = GitHubOidcValidator(DeployApiSettings.from_env()).validate(token)
        expected_revision = claims.get("sha")
        if not isinstance(expected_revision, str) or not re.fullmatch(
            r"[0-9a-f]{40}", expected_revision
        ):
            raise ValueError("deployment identity has no valid commit SHA")
        if request.get("github", {}).get("sha") != expected_revision:
            raise ValueError("queued commit does not match deployment identity")
    except Exception as validation_error:
        request["state"] = "rejected"
        request["error"] = str(validation_error)[:1000] or type(validation_error).__name__
        request["finished_at"] = int(time.time())
        _write_json(status_path, request)
        processing_path.unlink(missing_ok=True)
        return

    previous_digest = _read_current_digest(settings.compose_env_file)
    request["state"] = "deploying"
    request["started_at"] = int(time.time())
    _write_json(processing_path, request)
    try:
        _deploy(settings, digest, expected_revision)
        request["state"] = "healthy"
    except Exception as deploy_error:
        request["error"] = str(deploy_error)[:1000]
        if previous_digest and previous_digest != digest:
            try:
                _deploy(settings, previous_digest)
                request["state"] = "rolled_back"
                request["rolled_back_to"] = previous_digest
            except Exception as rollback_error:
                request["state"] = "rollback_failed"
                request["rollback_error"] = str(rollback_error)[:1000]
        else:
            request["state"] = "failed"
    finally:
        request["finished_at"] = int(time.time())
        _write_json(status_path, request)
        processing_path.unlink(missing_ok=True)


def main() -> int:
    settings = WorkerSettings.from_env()
    pending_dir = settings.state_dir / "pending"
    pending_dir.mkdir(parents=True, exist_ok=True)
    lock_path = settings.state_dir / "worker.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        exit_code = 0
        for pending_path in sorted(pending_dir.glob("*.json")):
            try:
                process_request(settings, pending_path)
            except Exception as exc:
                print(f"failed to process {pending_path.name}: {exc}", file=sys.stderr)
                exit_code = 1
        return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
