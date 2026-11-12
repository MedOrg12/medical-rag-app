"""Clerk sign-in for the clinician view and the developer workbench.

The patient view stays public. Clinician answers need a signed-in Clerk user, and the
developer workbench and its API need a user whose Clerk public metadata has
``"admin": true``.

The browser sends Clerk session tokens as ``Authorization: Bearer <token>``. The
``__session`` cookie is deliberately ignored: accepting it would let another site make a
signed-in user's browser call the developer API (CSRF), and the pages here always have a
fresh token from ClerkJS to put in the header.
"""

from __future__ import annotations

import base64
import binascii
import logging
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import HTTPException, Request, status

from medical_rag.config import Settings
from medical_rag.logging_config import describe_exception

logger = logging.getLogger(__name__)

# Clerk token failures that mean Clerk could not be reached, not that the token is bad.
_UNAVAILABLE_REASONS = {"jwk-failed-to-load", "server-error"}


class AuthUnavailableError(RuntimeError):
    """Clerk could not be reached to verify a token or look up a user."""


@dataclass(frozen=True)
class Principal:
    user_id: str | None
    is_admin: bool


@dataclass(frozen=True)
class _HeaderOnlyRequest:
    """Hands the Clerk SDK the Authorization header only, so it never reads cookies."""

    headers: Mapping[str, str]


def frontend_api_from_publishable_key(publishable_key: str) -> str | None:
    """Return the Clerk Frontend API host encoded in a publishable key.

    A key looks like ``pk_test_<base64("example.clerk.accounts.dev$")>``.
    """
    prefix, _, encoded = publishable_key.partition("_")
    environment, _, encoded = encoded.partition("_")
    if prefix != "pk" or environment not in {"test", "live"} or not encoded:
        return None
    try:
        decoded = base64.b64decode(encoded + "=" * (-len(encoded) % 4), validate=True).decode()
    except (binascii.Error, UnicodeDecodeError):
        return None
    host = decoded.removesuffix("$")
    if not host or not decoded.endswith("$") or any(char in host for char in "/?#@ "):
        return None
    return host


class Authenticator:
    """Verifies Clerk session tokens and checks the admin flag in public metadata."""

    def __init__(
        self,
        settings: Settings,
        *,
        admin_cache_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.disabled = settings.auth_disabled
        self.publishable_key = settings.clerk_publishable_key or ""
        self.frontend_api = (
            frontend_api_from_publishable_key(self.publishable_key)
            if self.publishable_key
            else None
        )
        self._secret_key = settings.clerk_secret_key or ""
        self._jwt_key = settings.clerk_jwt_key or None
        self._authorized_parties = list(settings.clerk_authorized_parties) or None
        self._admin_cache_seconds = admin_cache_seconds
        self._clock = clock
        self._admin_cache: dict[str, tuple[float, bool]] = {}
        self._cache_lock = threading.Lock()
        self._client: Any = None

    @property
    def configured(self) -> bool:
        return self.configuration_problem() is None and not self.disabled

    def configuration_problem(self) -> str | None:
        if self.disabled:
            return None
        if self._secret_key and self.frontend_api:
            # Production instances must name the origins allowed to use their tokens, or a
            # token minted for another app on the same Clerk instance would be accepted.
            if self.publishable_key.startswith("pk_live_") and not self._authorized_parties:
                return "CLERK_AUTHORIZED_PARTIES must be set with a production (pk_live_) key"
            return None
        if not self._secret_key and not self.publishable_key:
            return "CLERK_PUBLISHABLE_KEY and CLERK_SECRET_KEY are not set"
        if not self._secret_key:
            return "CLERK_SECRET_KEY is not set"
        if not self.publishable_key:
            return "CLERK_PUBLISHABLE_KEY is not set"
        return "CLERK_PUBLISHABLE_KEY is not a valid Clerk publishable key"

    def client_config(self) -> dict[str, Any]:
        """What the browser needs to load ClerkJS."""
        if self.disabled:
            return {"enabled": False, "configured": True}
        return {
            "enabled": True,
            "configured": self.configured,
            "publishable_key": self.publishable_key if self.configured else None,
            "frontend_api": self.frontend_api if self.configured else None,
        }

    # -- request checks -------------------------------------------------------------------

    def principal(self, request: Request) -> Principal | None:
        """Return the signed-in user, or None when the request carries no valid token."""
        if self.disabled:
            return Principal(user_id=None, is_admin=True)
        if not self.configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Sign-in is not configured on this server.",
            )
        authorization = request.headers.get("authorization")
        if not authorization or not authorization.lower().startswith("bearer "):
            return None
        token = authorization[len("bearer ") :].strip()
        if not token:
            return None
        try:
            user_id = self.verify_token(token)
        except AuthUnavailableError as exc:
            logger.warning("Could not verify a Clerk session token: %s", describe_exception(exc))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Sign-in is temporarily unavailable. Please try again.",
            ) from exc
        if user_id is None:
            return None
        return Principal(user_id=user_id, is_admin=False)

    def require_user(self, request: Request) -> Principal:
        principal = self.principal(request)
        if principal is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Sign in to use this feature.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return principal

    def require_admin(self, request: Request) -> Principal:
        principal = self.require_user(request)
        if principal.is_admin:
            return principal
        if not self.user_is_admin(principal.user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This area is limited to administrators.",
            )
        return Principal(user_id=principal.user_id, is_admin=True)

    def user_is_admin(self, user_id: str | None) -> bool:
        if self.disabled:
            return True
        if not user_id:
            return False
        now = self._clock()
        with self._cache_lock:
            cached = self._admin_cache.get(user_id)
        if cached is not None and cached[0] > now:
            return cached[1]
        try:
            metadata = self.fetch_public_metadata(user_id)
        except Exception as exc:  # noqa: BLE001 - the Clerk SDK raises several transport types
            logger.warning(
                "Could not look up Clerk user %s for the admin check: %s",
                user_id,
                describe_exception(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Could not check your access right now. Please try again.",
            ) from exc
        # Only a JSON true counts; "true" or 1 set by mistake in the dashboard does not.
        is_admin = isinstance(metadata, Mapping) and metadata.get("admin") is True
        with self._cache_lock:
            self._admin_cache[user_id] = (now + self._admin_cache_seconds, is_admin)
        return is_admin

    # -- Clerk calls (overridden in tests) ----------------------------------------------------

    def verify_token(self, token: str) -> str | None:
        """Return the user id of a valid session token, or None if it is not valid."""
        from clerk_backend_api.security import authenticate_request
        from clerk_backend_api.security.types import AuthenticateRequestOptions

        try:
            state = authenticate_request(
                _HeaderOnlyRequest(headers={"Authorization": f"Bearer {token}"}),
                AuthenticateRequestOptions(
                    secret_key=self._secret_key,
                    jwt_key=self._jwt_key,
                    authorized_parties=self._authorized_parties,
                    accepts_token=["session_token"],
                ),
            )
        except httpx.HTTPError as exc:
            # The SDK retries the JWKS fetch but lets a final connection error escape.
            raise AuthUnavailableError(f"could not fetch Clerk's signing keys: {exc}") from exc
        if state.is_signed_in and state.payload:
            subject = state.payload.get("sub")
            return subject if isinstance(subject, str) and subject else None
        reason = state.reason.value[0] if state.reason is not None else "unknown"
        if reason in _UNAVAILABLE_REASONS:
            raise AuthUnavailableError(state.message or reason)
        logger.info("Rejected a Clerk session token: %s", reason)
        return None

    def fetch_public_metadata(self, user_id: str) -> Any:
        if self._client is None:
            from clerk_backend_api import Clerk

            self._client = Clerk(bearer_auth=self._secret_key)
        return self._client.users.get(user_id=user_id).public_metadata
