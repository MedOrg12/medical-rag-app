from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from medical_rag.types import Citation, RagAnswer

DEFAULT_EVAL_DATA_PATH = Path(__file__).with_name("eval_data.json")
DEFAULT_ANSWER_TERM_THRESHOLD = 0.4
DEFAULT_CITATION_TERM_THRESHOLD = 0.25

_REFUSAL_PHRASES = [
    "no relevant",
    "not found",
    "no information",
    "unable to find",
    "outside the scope",
    "not in the",
    "no evidence",
    "cannot find",
    "could not find",
    "don't have information",
    "do not have information",
    "not enough indexed evidence",
]


@dataclass(frozen=True)
class EvalQuestion:
    id: str
    question: str
    expected_source_hints: list[str]
    expected_answer_terms: list[str]
    should_refuse: bool = False

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EvalQuestion":
        return cls(
            id=str(payload["id"]),
            question=str(payload["question"]),
            expected_source_hints=[str(item) for item in payload.get("expected_source_hints", [])],
            expected_answer_terms=[str(item) for item in payload.get("expected_answer_terms", [])],
            should_refuse=bool(payload.get("should_refuse", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvalQuestionResult:
    question_id: str
    question: str
    status: str
    should_refuse: bool
    refused: bool
    retrieval_hit: bool
    citation_term_coverage: float
    answer_term_coverage: float
    source_hints_found: list[str]
    answer_terms_found: list[str]
    answer_terms_missing: list[str]
    latency_seconds: float
    answer_snippet: str
    answer: str | None = None
    citations: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvalSummary:
    total_questions: int
    completed_questions: int
    in_scope_questions: int
    negative_controls: int
    passed_questions: int
    failed_questions: int
    error_questions: int
    retrieval_hit_rate: float
    average_citation_term_coverage: float
    average_answer_term_coverage: float
    refusal_accuracy: float
    duration_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvalSuiteResult:
    version: int
    summary: EvalSummary
    results: list[EvalQuestionResult]
    top_k: int | None
    answer_mode: str | None

    @property
    def passed(self) -> bool:
        return self.summary.failed_questions == 0 and self.summary.error_questions == 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["passed"] = self.passed
        return payload


def load_eval_suite(path: Path | None = None) -> tuple[int, list[EvalQuestion]]:
    eval_path = path or DEFAULT_EVAL_DATA_PATH
    data = json.loads(eval_path.read_text(encoding="utf-8"))
    return int(data.get("version", 1)), [
        EvalQuestion.from_dict(item) for item in data.get("questions", [])
    ]


def evaluate_rag(
    rag: Any,
    questions: list[EvalQuestion] | None = None,
    version: int | None = None,
    top_k: int | None = None,
    answer_mode: str | None = None,
    question_ids: list[str] | None = None,
    include_answers: bool = False,
) -> EvalSuiteResult:
    if questions is None:
        version, questions = load_eval_suite()
    selected_ids = set(question_ids or [])
    selected = [item for item in questions if not selected_ids or item.id in selected_ids]

    started = time.perf_counter()
    results = [
        evaluate_question(
            rag=rag,
            item=item,
            top_k=top_k,
            answer_mode=answer_mode,
            include_answer=include_answers,
        )
        for item in selected
    ]
    duration = time.perf_counter() - started

    return EvalSuiteResult(
        version=version or 1,
        summary=_summarize(results, duration),
        results=results,
        top_k=top_k,
        answer_mode=answer_mode,
    )


def evaluate_question(
    rag: Any,
    item: EvalQuestion,
    top_k: int | None = None,
    answer_mode: str | None = None,
    include_answer: bool = False,
) -> EvalQuestionResult:
    started = time.perf_counter()
    try:
        response: RagAnswer = rag.ask(item.question, top_k=top_k, answer_mode=answer_mode)
    except Exception as exc:
        return EvalQuestionResult(
            question_id=item.id,
            question=item.question,
            status="error",
            should_refuse=item.should_refuse,
            refused=False,
            retrieval_hit=False,
            citation_term_coverage=0.0,
            answer_term_coverage=0.0,
            source_hints_found=[],
            answer_terms_found=[],
            answer_terms_missing=list(item.expected_answer_terms),
            latency_seconds=round(time.perf_counter() - started, 4),
            answer_snippet="",
            citations=[],
            error=str(exc),
        )

    latency = round(time.perf_counter() - started, 4)
    answer = response.answer
    citations = response.citations
    refused = _looks_like_refusal(answer, citations)
    source_hints_found = _terms_found(item.expected_source_hints, _citation_blob(citations))
    answer_terms_found = _terms_found(item.expected_answer_terms, answer)
    citation_terms_found = _terms_found(item.expected_answer_terms, _citation_blob(citations))
    answer_terms_missing = [
        term for term in item.expected_answer_terms if term.lower() not in answer_terms_found
    ]

    citation_term_coverage = _coverage(citation_terms_found, item.expected_answer_terms)
    answer_term_coverage = _coverage(answer_terms_found, item.expected_answer_terms)
    retrieval_hit = bool(source_hints_found) or (
        citation_term_coverage >= DEFAULT_CITATION_TERM_THRESHOLD
    )
    status = _question_status(
        should_refuse=item.should_refuse,
        refused=refused,
        retrieval_hit=retrieval_hit,
        citation_term_coverage=citation_term_coverage,
        answer_term_coverage=answer_term_coverage,
    )

    return EvalQuestionResult(
        question_id=item.id,
        question=item.question,
        status=status,
        should_refuse=item.should_refuse,
        refused=refused,
        retrieval_hit=retrieval_hit,
        citation_term_coverage=round(citation_term_coverage, 4),
        answer_term_coverage=round(answer_term_coverage, 4),
        source_hints_found=source_hints_found,
        answer_terms_found=answer_terms_found,
        answer_terms_missing=answer_terms_missing,
        latency_seconds=latency,
        answer_snippet=_snippet(answer),
        answer=answer if include_answer else None,
        citations=[_citation_to_eval_dict(citation) for citation in citations],
    )


def _summarize(results: list[EvalQuestionResult], duration_seconds: float) -> EvalSummary:
    completed = [result for result in results if result.status != "error"]
    in_scope = [result for result in completed if not result.should_refuse]
    negative = [result for result in completed if result.should_refuse]
    passed = [result for result in results if result.status == "pass"]
    failed = [result for result in results if result.status == "fail"]
    errors = [result for result in results if result.status == "error"]

    retrieval_hit_rate = (
        sum(1 for result in in_scope if result.retrieval_hit) / len(in_scope) if in_scope else 0.0
    )
    average_citation_term_coverage = (
        sum(result.citation_term_coverage for result in in_scope) / len(in_scope)
        if in_scope
        else 0.0
    )
    average_answer_term_coverage = (
        sum(result.answer_term_coverage for result in in_scope) / len(in_scope)
        if in_scope
        else 0.0
    )
    refusal_accuracy = (
        sum(1 for result in negative if result.refused) / len(negative) if negative else 0.0
    )

    return EvalSummary(
        total_questions=len(results),
        completed_questions=len(completed),
        in_scope_questions=len(in_scope),
        negative_controls=len(negative),
        passed_questions=len(passed),
        failed_questions=len(failed),
        error_questions=len(errors),
        retrieval_hit_rate=round(retrieval_hit_rate, 4),
        average_citation_term_coverage=round(average_citation_term_coverage, 4),
        average_answer_term_coverage=round(average_answer_term_coverage, 4),
        refusal_accuracy=round(refusal_accuracy, 4),
        duration_seconds=round(duration_seconds, 4),
    )


def _question_status(
    should_refuse: bool,
    refused: bool,
    retrieval_hit: bool,
    citation_term_coverage: float,
    answer_term_coverage: float,
) -> str:
    if should_refuse:
        return "pass" if refused else "fail"
    if not retrieval_hit:
        return "fail"
    return "pass" if answer_term_coverage >= DEFAULT_ANSWER_TERM_THRESHOLD else "fail"


def _looks_like_refusal(answer: str, citations: list[Citation]) -> bool:
    if not citations:
        return True
    normalized = answer.lower()
    return any(phrase in normalized for phrase in _REFUSAL_PHRASES)


def _citation_blob(citations: list[Citation]) -> str:
    return " ".join(
        f"{citation.source} {citation.page or ''} {citation.chunk_id} {citation.excerpt}"
        for citation in citations
    )


def _terms_found(expected_terms: list[str], text: str) -> list[str]:
    normalized = text.lower()
    return [term.lower() for term in expected_terms if term.lower() in normalized]


def _coverage(found_terms: list[str], expected_terms: list[str]) -> float:
    if not expected_terms:
        return 1.0
    return len(set(found_terms)) / len(set(term.lower() for term in expected_terms))


def _citation_to_eval_dict(citation: Citation) -> dict[str, Any]:
    return {
        "id": citation.id,
        "source": citation.source,
        "page": citation.page,
        "score": citation.score,
        "excerpt": citation.excerpt,
    }


def _snippet(answer: str, limit: int = 240) -> str:
    cleaned = " ".join(answer.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rsplit(" ", 1)[0] + "..."
