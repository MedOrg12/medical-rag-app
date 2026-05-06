"""
Process-wide runtime overrides for settings that can be changed via the
Settings tab without restarting the app. Imported by both app.py (for the
GET/POST /api/settings endpoints) and api/query.py (so new RAG sessions
pick up the latest model/temperature/etc.).
"""

from typing import Any

# Module-level dict — single source of truth for runtime overrides.
_overrides: dict[str, Any] = {}


def get_overrides() -> dict[str, Any]:
    """Return the live overrides dict (mutations are visible)."""
    return _overrides


def set_override(key: str, value: Any) -> None:
    _overrides[key] = value


def clear_overrides() -> None:
    _overrides.clear()


def get(key: str, default: Any = None) -> Any:
    return _overrides.get(key, default)
