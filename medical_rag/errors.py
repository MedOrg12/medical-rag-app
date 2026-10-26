"""Messages safe to display without exposing provider responses or local paths."""
from __future__ import annotations

import urllib.error


def user_error(exc: Exception, operation: str = "request") -> str:
    cause: BaseException | None = exc
    while cause is not None:
        if isinstance(cause, urllib.error.HTTPError):
            if cause.code in {401, 403}:
                return "The answer service needs attention. Please ask the app administrator to check its connection settings."
            if cause.code == 429:
                return "The answer service is busy or has reached its usage limit. Please try again later."
        if isinstance(cause, (TimeoutError, urllib.error.URLError)):
            return "The answer service could not be reached. Please try again in a moment."
        cause = cause.__cause__
    if operation == "ingest":
        return "We couldn't add those documents. Check that the selected folder contains readable PDF or text files, then try again."
    if isinstance(exc, FileNotFoundError):
        return "Your document library isn't ready yet. Add your documents before asking a question."
    if isinstance(exc, ValueError):
        return "We couldn't use that request. Please check your question and selected options, then try again."
    return "We couldn't complete that request right now. Please try again in a moment."
