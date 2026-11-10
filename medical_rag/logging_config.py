from __future__ import annotations

import logging
import os
import sys

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_PACKAGE_LOGGER = "medical_rag"


def configure_logging(level: str | None = None) -> logging.Logger:
    """Attach a plain stderr handler to the ``medical_rag`` logger.

    Idempotent: a second call only updates the level. The handler goes on the package
    logger rather than the root so uvicorn's own logging configuration is left alone.
    Propagation stays on so test harnesses that listen on the root logger still see
    the records.

    The level comes from ``RAG_LOG_LEVEL`` (default ``INFO``) unless passed explicitly.
    """
    raw_level = (level or os.getenv("RAG_LOG_LEVEL") or "INFO").strip().upper()
    resolved = logging.getLevelName(raw_level)
    level_known = isinstance(resolved, int)
    if not level_known:
        resolved = logging.INFO

    logger = logging.getLogger(_PACKAGE_LOGGER)
    logger.setLevel(resolved)
    if not any(getattr(handler, "_medical_rag_handler", False) for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(_FORMAT))
        handler._medical_rag_handler = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    if not level_known:
        logger.warning("Unknown RAG_LOG_LEVEL %r; using INFO", raw_level)
    return logger


def describe_exception(exc: BaseException) -> str:
    """Render ``exc`` and its cause chain on one line for a log message.

    ``str(exc)`` alone drops the reason a wrapped error was raised, which for network
    failures is the useful part (timeout, connection refused, name resolution). This
    follows ``__cause__`` (``raise ... from``) and implicit ``__context__`` and renders
    each link as ``Type: message``.
    """
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        message = str(current).strip()
        name = current.__class__.__name__
        parts.append(f"{name}: {message}" if message else name)
        if current.__cause__ is not None:
            current = current.__cause__
        elif not current.__suppress_context__:
            current = current.__context__
        else:
            current = None
    return "; caused by ".join(parts)
