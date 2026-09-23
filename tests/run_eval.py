#!/usr/bin/env python3
"""
Evaluation runner for the Stroke Medical RAG system.

Usage:
    python tests/run_eval.py [--url http://localhost:8000] [--data medical_rag/eval_data.json]

Requires the server to be running and the index to be ingested first.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from medical_rag.evaluation import DEFAULT_EVAL_DATA_PATH, evaluate_rag, load_eval_suite
from medical_rag.types import Citation, RagAnswer


class HttpRag:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def ask(
        self,
        question: str,
        top_k: int | None = None,
        answer_mode: str | None = None,
    ) -> RagAnswer:
        payload: dict[str, Any] = {"question": question}
        if top_k is not None:
            payload["top_k"] = top_k
        if answer_mode is not None:
            payload["answer_mode"] = answer_mode

        request = urllib.request.Request(
            f"{self.base_url}/ask",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.loads(response.read())

        return RagAnswer(
            question=str(data.get("question", question)),
            answer=str(data.get("answer", "")),
            citations=[
                Citation(
                    id=int(citation.get("id", index)),
                    source=str(citation.get("source", "unknown")),
                    page=citation.get("page"),
                    chunk_id=str(citation.get("chunk_id", "")),
                    score=float(citation.get("score", 0.0)),
                    excerpt=str(citation.get("excerpt", "")),
                )
                for index, citation in enumerate(data.get("citations", []), start=1)
            ],
            retrieval_model=str(data.get("retrieval_model", "")),
            generation_model=str(data.get("generation_model", "")),
            answer_mode=str(data.get("answer_mode", answer_mode or "patient")),
            safety_notice=str(data.get("safety_notice", "")),
            retrieval_mode=str(data.get("retrieval_mode", "")),
            fallback_embedding=bool(data.get("fallback_embedding", False)),
        )


def run_eval(base_url: str, data_path: Path, top_k: int | None = None, answer_mode: str | None = None) -> int:
    version, questions = load_eval_suite(data_path)
    result = evaluate_rag(
        HttpRag(base_url),
        questions=questions,
        version=version,
        top_k=top_k,
        answer_mode=answer_mode,
    )

    summary = result.summary
    print()
    print("=" * 60)
    print("EVALUATION REPORT")
    print("=" * 60)
    print(f"Total questions:          {summary.total_questions}")
    print(f"Completed questions:      {summary.completed_questions}")
    print(f"In-scope questions:       {summary.in_scope_questions}")
    print(f"Negative controls:        {summary.negative_controls}")
    print(f"Passed:                   {summary.passed_questions}")
    print(f"Failed:                   {summary.failed_questions}")
    print(f"Errors:                   {summary.error_questions}")
    print(f"Retrieval hit rate:       {summary.retrieval_hit_rate:.2f}")
    print(f"Avg citation coverage:    {summary.average_citation_term_coverage:.2f}")
    print(f"Avg answer coverage:      {summary.average_answer_term_coverage:.2f}")
    print(f"Refusal accuracy:         {summary.refusal_accuracy:.2f}")
    print(f"Duration seconds:         {summary.duration_seconds:.2f}")
    print()
    print("DETAIL")
    print("-" * 60)

    for item in result.results:
        note = (
            f"retrieval={'hit' if item.retrieval_hit else 'MISS'}, "
            f"answer_terms={item.answer_term_coverage:.2f}, "
            f"citation_terms={item.citation_term_coverage:.2f}"
        )
        if item.should_refuse:
            note = "correctly refused" if item.refused else "should have refused"
        if item.error:
            note = item.error
        print(f"  [{item.status.upper()}] {item.question_id}: {note}")
        if item.status != "pass":
            sources = [citation["source"] for citation in item.citations]
            print(f"         sources: {sources}")

    print()
    if result.passed:
        print("All checks passed.")
        return 0

    print("Some checks FAILED; see detail above.")
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Stroke RAG evaluation suite")
    parser.add_argument("--url", default="http://localhost:8000", help="Server base URL")
    parser.add_argument(
        "--data",
        default=str(DEFAULT_EVAL_DATA_PATH),
        help="Path to eval_data.json",
    )
    parser.add_argument("--top-k", type=int, default=None, help="Override retrieval top_k")
    parser.add_argument(
        "--answer-mode",
        choices=["patient", "clinician"],
        default=None,
        help="Override answer mode",
    )
    args = parser.parse_args()
    sys.exit(run_eval(args.url, Path(args.data), top_k=args.top_k, answer_mode=args.answer_mode))


if __name__ == "__main__":
    main()
