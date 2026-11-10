from __future__ import annotations

import logging

import pytest

from medical_rag.logging_config import configure_logging, describe_exception


def _own_handlers(logger: logging.Logger) -> list[logging.Handler]:
    return [h for h in logger.handlers if getattr(h, "_medical_rag_handler", False)]


@pytest.fixture
def package_logger():
    """Hand the test a bare ``medical_rag`` logger and restore its state afterwards."""
    logger = logging.getLogger("medical_rag")
    saved_handlers = list(logger.handlers)
    saved_level = logger.level
    for handler in _own_handlers(logger):
        logger.removeHandler(handler)
    try:
        yield logger
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
        for handler in saved_handlers:
            logger.addHandler(handler)
        logger.setLevel(saved_level)


def test_configure_logging_is_idempotent_and_reads_level(monkeypatch, package_logger) -> None:
    logger = package_logger

    monkeypatch.setenv("RAG_LOG_LEVEL", "debug")
    configure_logging()
    configure_logging()

    assert len(_own_handlers(logger)) == 1
    assert logger.level == logging.DEBUG
    assert logger.propagate is True

    configure_logging(level="WARNING")
    assert logger.level == logging.WARNING


def test_configure_logging_falls_back_to_info_on_unknown_level(
    monkeypatch, caplog, package_logger
) -> None:
    monkeypatch.setenv("RAG_LOG_LEVEL", "loud")
    with caplog.at_level(logging.DEBUG, logger="medical_rag"):
        configure_logging()
        assert logging.getLogger("medical_rag").level == logging.INFO

    assert any("Unknown RAG_LOG_LEVEL" in r.getMessage() for r in caplog.records)


def test_describe_exception_includes_cause_chain() -> None:
    try:
        try:
            raise TimeoutError("timed out")
        except TimeoutError as network_error:
            raise RuntimeError("Could not generate with Ollama") from network_error
    except RuntimeError as exc:
        described = describe_exception(exc)

    assert described == (
        "RuntimeError: Could not generate with Ollama; caused by TimeoutError: timed out"
    )


def test_describe_exception_flattens_multiline_messages() -> None:
    exc = RuntimeError("Provider returned an error:\n  {\"code\": 503}\n")

    assert describe_exception(exc) == 'RuntimeError: Provider returned an error: {"code": 503}'


def test_describe_exception_handles_bare_and_suppressed_context() -> None:
    assert describe_exception(ValueError()) == "ValueError"

    try:
        try:
            raise KeyError("inner")
        except KeyError:
            raise ValueError("outer") from None
    except ValueError as exc:
        assert describe_exception(exc) == "ValueError: outer"
