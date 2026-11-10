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
