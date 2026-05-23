from __future__ import annotations

import re

from medical_rag.types import SearchResult

_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_+-]*")

_DIET_QUERY_TERMS = {
    "eat",
    "eating",
    "food",
    "foods",
    "diet",
    "dietary",
    "nutrition",
    "nutritional",
    "meal",
    "meals",
}

_DIET_CONTEXT_TERMS = {
    "calorie",
    "calories",
    "cholesterol",
    "dash",
    "diet",
    "dietary",
    "dysphagia",
    "eat",
    "eating",
    "fat",
    "feeding",
    "fiber",
    "fruit",
    "fruits",
    "malnutrition",
    "mediterranean",
    "meal",
    "meals",
    "nutrition",
    "nutritional",
    "protein",
    "salt",
    "saturated",
    "sodium",
    "swallow",
    "swallowing",
    "vegetable",
    "vegetables",
}

_DIET_EXPANSION = (
    "diet nutrition dietary food eating meals Mediterranean DASH fruit vegetables sodium salt "
    "saturated fat cholesterol hypertension dysphagia swallowing protein malnutrition secondary "
    "prevention lifestyle"
)


def expand_query_for_retrieval(question: str) -> str:
    if is_diet_query(question):
        return f"{question} {_DIET_EXPANSION}"
    return question


def filter_results_for_question(question: str, results: list[SearchResult]) -> list[SearchResult]:
    if is_diet_query(question):
        return [result for result in results if _has_diet_evidence(result)]

    return [result for result in results if result.score > 0]


def is_diet_query(question: str) -> bool:
    terms = set(_terms(question))
    return bool(terms & _DIET_QUERY_TERMS)


def _has_diet_evidence(result: SearchResult) -> bool:
    metadata = result.chunk.metadata
    searchable = " ".join(
        [
            result.chunk.text,
            str(metadata.get("title", "")),
            str(metadata.get("section", "")),
            str(metadata.get("source_id", "")),
        ]
    )
    return bool(set(_terms(searchable)) & _DIET_CONTEXT_TERMS)


def _terms(text: str) -> list[str]:
    return [match.group(0).lower() for match in _TOKEN_RE.finditer(text)]
