"""Stroke-focused retrieval-augmented generation package."""

from importlib.metadata import PackageNotFoundError, version

from medical_rag.config import Settings
from medical_rag.pipeline import StrokeRAG

try:
    __version__ = version("stroke-medical-rag")
except PackageNotFoundError:
    __version__ = "0.1.0"

__all__ = ["Settings", "StrokeRAG", "__version__"]
