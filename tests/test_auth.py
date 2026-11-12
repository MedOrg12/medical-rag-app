from __future__ import annotations

import base64
import time
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from medical_rag.auth import Authenticator, frontend_api_from_publishable_key
from medical_rag.config import Settings
from medical_rag.server import create_app

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_API = "example-app.clerk.accounts.dev"
PUBLISHABLE_KEY = "pk_test_" + base64.b64encode(f"{FRONTEND_API}$".encode()).decode().rstrip("=")
ADMIN_ENDPOINTS = [
    ("get", "/health", None),
    ("get", "/sources", None),
    ("post", "/ingest", {}),
    ("get", "/ingest/status", None),
    ("get", "/eval/questions", None),
    ("post", "/eval/run", {}),
]


class FakeAuthenticator(Authenticator):
    """Stands in for Clerk: fixed tokens and public metadata, with call counting."""

    def __init__(self, settings: Settings, metadata: dict[str, object] | None = None, **kwargs):
        super().__init__(settings, **kwargs)
        self.tokens = {"user-token": "user_1", "admin-token": "user_admin"}
        self.metadata = metadata if metadata is not None else {
            "user_1": {},
            "user_admin": {"admin": True},
        }
        self.lookups = 0

    def verify_token(self, token: str) -> str | None:
        return self.tokens.get(token)

    def fetch_public_metadata(self, user_id: str) -> object:
        self.lookups += 1
        value = self.metadata[user_id]
        if isinstance(value, Exception):
            raise value
        return value


def _settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "root_dir": ROOT,
        "corpus_dir": tmp_path / "corpus",
        "index_path": tmp_path / "index.json",
        "embedding_backend": "hash",
        "clerk_publishable_key": PUBLISHABLE_KEY,
        "clerk_secret_key": "sk_test_secret",
    }
    values.update(overrides)
    return Settings(**values)


def _client(settings: Settings, authenticator: Authenticator | None = None) -> TestClient:
    return TestClient(create_app(settings, authenticator=authenticator))


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_frontend_api_is_decoded_from_publishable_key() -> None:
    assert frontend_api_from_publishable_key(PUBLISHABLE_KEY) == FRONTEND_API
    live = "pk_live_" + base64.b64encode(b"clerk.example.org$").decode()
    assert frontend_api_from_publishable_key(live) == "clerk.example.org"
    assert frontend_api_from_publishable_key("sk_test_abc") is None
    assert frontend_api_from_publishable_key("pk_test_!!!") is None
    no_dollar = "pk_test_" + base64.b64encode(b"example.dev").decode()
    assert frontend_api_from_publishable_key(no_dollar) is None
    with_path = "pk_test_" + base64.b64encode(b"evil.test/x$").decode()
    assert frontend_api_from_publishable_key(with_path) is None


def test_pages_are_served_without_sign_in(tmp_path) -> None:
    client = _client(_settings(tmp_path), FakeAuthenticator(_settings(tmp_path)))

    for path in ("/", "/clinician", "/dev", "/status"):
        assert client.get(path).status_code == 200, path
    # /ready is public too; 503 here only means no index has been built yet.
    assert client.get("/ready").json() == {"status": "not_ready", "index_exists": False}
    clinician = client.get("/clinician")
    assert clinician.status_code == 200
    assert "/static/auth.js" in clinician.text
    assert 'id="auth-gate"' in client.get("/dev").text


def test_auth_config_exposes_publishable_key_only(tmp_path) -> None:
    settings = _settings(tmp_path)
    response = _client(settings, FakeAuthenticator(settings)).get("/auth/config")

    assert response.json() == {
        "enabled": True,
        "configured": True,
        "publishable_key": PUBLISHABLE_KEY,
        "frontend_api": FRONTEND_API,
    }
    assert "sk_test_secret" not in response.text


def test_patient_answers_stay_public(tmp_path) -> None:
    settings = _settings(tmp_path)
    client = _client(settings, FakeAuthenticator(settings))

    # 409 means the request got past the auth check to the (missing) index.
    response = client.post("/ask", json={"question": "What is a stroke?", "answer_mode": "patient"})
    assert response.status_code == 409


def test_clinician_answers_need_a_signed_in_user(tmp_path) -> None:
    settings = _settings(tmp_path)
    client = _client(settings, FakeAuthenticator(settings))
    body = {"question": "When is thrombectomy indicated?", "answer_mode": "clinician"}

    anonymous = client.post("/ask", json=body)
    assert anonymous.status_code == 401
    assert anonymous.headers["www-authenticate"] == "Bearer"
    assert client.post("/ask", json=body, headers=_bearer("forged")).status_code == 401
    assert client.post("/ask", json=body, headers=_bearer("user-token")).status_code == 409


def test_default_clinician_mode_also_needs_sign_in(tmp_path) -> None:
    settings = _settings(tmp_path, answer_mode="clinician")
    client = _client(settings, FakeAuthenticator(settings))

    assert client.post("/ask", json={"question": "What is a stroke?"}).status_code == 401
    assert (
        client.post("/ask", json={"question": "What is a stroke?", "answer_mode": "patient"})
        .status_code
        == 409
    )


@pytest.mark.parametrize(("method", "path", "body"), ADMIN_ENDPOINTS)
def test_developer_api_needs_an_admin(tmp_path, method, path, body) -> None:
    settings = _settings(tmp_path)
    client = _client(settings, FakeAuthenticator(settings))
    call = getattr(client, method)
    kwargs = {"json": body} if body is not None else {}

    assert call(path, **kwargs).status_code == 401
    assert call(path, headers=_bearer("user-token"), **kwargs).status_code == 403
    assert call(path, headers=_bearer("admin-token"), **kwargs).status_code not in {401, 403}


def test_session_cookie_is_not_accepted(tmp_path) -> None:
    settings = _settings(tmp_path)
    client = _client(settings, FakeAuthenticator(settings))

    response = client.get("/eval/questions", headers={"Cookie": "__session=admin-token"})

    assert response.status_code == 401


def test_admin_flag_must_be_json_true(tmp_path) -> None:
    settings = _settings(tmp_path)
    auth = FakeAuthenticator(
        settings, metadata={"user_1": {"admin": "true"}, "user_admin": {"admin": 1}}
    )
    client = _client(settings, auth)

    assert client.get("/eval/questions", headers=_bearer("user-token")).status_code == 403
    assert client.get("/eval/questions", headers=_bearer("admin-token")).status_code == 403


def test_auth_me_reports_the_viewer(tmp_path) -> None:
    settings = _settings(tmp_path)
    client = _client(settings, FakeAuthenticator(settings))

    assert client.get("/auth/me").json() == {"signed_in": False, "admin": False}
    assert client.get("/auth/me", headers=_bearer("user-token")).json() == {
        "signed_in": True,
        "admin": False,
    }
    assert client.get("/auth/me", headers=_bearer("admin-token")).json() == {
        "signed_in": True,
        "admin": True,
    }


def test_admin_lookup_is_cached_briefly(tmp_path) -> None:
    now = [1000.0]
    settings = _settings(tmp_path)
    auth = FakeAuthenticator(settings, admin_cache_seconds=30, clock=lambda: now[0])
    client = _client(settings, auth)

    for _ in range(3):
        assert client.get("/eval/questions", headers=_bearer("admin-token")).status_code == 200
    assert auth.lookups == 1

    # Revoking admin takes effect once the cache entry expires.
    auth.metadata["user_admin"] = {}
    now[0] += 31
    assert client.get("/eval/questions", headers=_bearer("admin-token")).status_code == 403
    assert auth.lookups == 2


def test_clerk_lookup_failure_is_503(tmp_path, caplog) -> None:
    settings = _settings(tmp_path)
    auth = FakeAuthenticator(settings, metadata={"user_admin": ConnectionError("clerk down")})
    client = _client(settings, auth)

    with caplog.at_level("WARNING", logger="medical_rag.auth"):
        response = client.get("/eval/questions", headers=_bearer("admin-token"))

    assert response.status_code == 503
    assert "clerk down" not in response.text
    assert "clerk down" in caplog.text


def test_missing_clerk_keys_close_protected_areas(tmp_path, caplog) -> None:
    settings = _settings(tmp_path, clerk_publishable_key=None, clerk_secret_key=None)
    with caplog.at_level("WARNING", logger="medical_rag.server"):
        client = _client(settings)

    assert "Sign-in is not configured" in caplog.text
    assert client.get("/auth/config").json()["configured"] is False
    assert client.get("/eval/questions").status_code == 503
    assert client.post("/ask", json={"question": "x", "answer_mode": "clinician"}).status_code == 503
    assert client.post("/ask", json={"question": "x", "answer_mode": "patient"}).status_code == 409


def test_production_key_needs_authorized_parties(tmp_path) -> None:
    live_key = "pk_live_" + base64.b64encode(b"clerk.example.org$").decode()
    settings = _settings(tmp_path, clerk_publishable_key=live_key)
    client = _client(settings, FakeAuthenticator(settings))

    assert client.get("/auth/config").json()["configured"] is False
    assert client.get("/eval/questions", headers=_bearer("admin-token")).status_code == 503

    settings = _settings(
        tmp_path,
        clerk_publishable_key=live_key,
        clerk_authorized_parties=("https://stroke.example.org",),
    )
    client = _client(settings, FakeAuthenticator(settings))
    assert client.get("/auth/config").json()["configured"] is True
    assert client.get("/eval/questions", headers=_bearer("admin-token")).status_code == 200


def test_auth_disabled_opens_everything(tmp_path) -> None:
    settings = _settings(
        tmp_path, clerk_publishable_key=None, clerk_secret_key=None, auth_disabled=True
    )
    client = _client(settings)

    assert client.get("/auth/config").json() == {"enabled": False, "configured": True}
    assert client.get("/eval/questions").status_code == 200
    assert client.post("/ask", json={"question": "x", "answer_mode": "clinician"}).status_code == 409


def test_settings_read_clerk_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CLERK_PUBLISHABLE_KEY", f" {PUBLISHABLE_KEY} ")
    monkeypatch.setenv("CLERK_SECRET_KEY", "sk_test_secret")
    monkeypatch.setenv("CLERK_JWT_KEY", "-----BEGIN PUBLIC KEY-----\\nabc\\n-----END PUBLIC KEY-----")
    monkeypatch.setenv("CLERK_AUTHORIZED_PARTIES", "https://a.test/, https://b.test,,")
    monkeypatch.setenv("RAG_AUTH_DISABLED", "true")

    settings = Settings.from_env(tmp_path)

    assert settings.clerk_publishable_key == PUBLISHABLE_KEY
    assert settings.clerk_secret_key == "sk_test_secret"
    assert settings.clerk_jwt_key == "-----BEGIN PUBLIC KEY-----\nabc\n-----END PUBLIC KEY-----"
    assert settings.clerk_authorized_parties == ("https://a.test", "https://b.test")
    assert settings.auth_disabled is True


# -- the real Clerk SDK verification path, kept networkless with CLERK_JWT_KEY -------------


@pytest.fixture(scope="module")
def signing_key():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return private_key, public_pem


def _session_token(private_key, **claims) -> str:
    now = int(time.time())
    payload = {
        "sub": "user_real",
        "sid": "sess_1",
        "iss": f"https://{FRONTEND_API}",
        "azp": "https://app.test",
        "iat": now - 5,
        "nbf": now - 5,
        "exp": now + 60,
        "v": 2,
    }
    payload.update(claims)
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": "ins_test"})


def test_sdk_verifies_session_tokens(tmp_path, signing_key) -> None:
    private_key, public_pem = signing_key
    auth = Authenticator(
        _settings(
            tmp_path, clerk_jwt_key=public_pem, clerk_authorized_parties=("https://app.test",)
        )
    )

    assert auth.verify_token(_session_token(private_key)) == "user_real"
    assert auth.verify_token(_session_token(private_key, exp=int(time.time()) - 120)) is None
    assert auth.verify_token(_session_token(private_key, azp="https://evil.test")) is None
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert auth.verify_token(_session_token(other_key)) is None
    # API keys and other machine tokens are not session tokens.
    assert auth.verify_token("ak_123") is None


def test_unreachable_jwks_is_503(tmp_path, signing_key, monkeypatch, caplog) -> None:
    import httpx

    def refuse(*_args, **_kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("clerk_backend_api.security.verifytoken._fetch_jwks", refuse)
    private_key, _ = signing_key
    settings = _settings(tmp_path)
    client = _client(settings, Authenticator(settings))

    with caplog.at_level("WARNING", logger="medical_rag.auth"):
        response = client.get("/eval/questions", headers=_bearer(_session_token(private_key)))

    assert response.status_code == 503
    assert "connection refused" in caplog.text
