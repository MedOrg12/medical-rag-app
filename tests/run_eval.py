#!/usr/bin/env python3
"""
Evaluation runner for the Stroke Medical RAG system.

Usage:
    python tests/run_eval.py [--url http://localhost:8000] [--data tests/eval_data.json]

Requires the server to be running and the index to be ingested first.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class EvalResult:
    question_id: str
    question: str
    retrieval_hit: bool
    citation_relevance: float
    should_refuse: bool
    refused: bool
    answer_snippet: str
    citation_sources: list[str] = field(default_factory=list)


_DISCLAIMER_PHRASES = [
    "no relevant",
    "not found",
    "no information",
    "unable to find",
    "outside the scope",
    "not in the",
    "no evidence",
    "cannot find",
    "don't have information",
]


def ask(base_url: str, question: str) -> dict:
    payload = json.dumps({"question": question}).encode()
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/ask",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def evaluate_question(base_url: str, item: dict) -> EvalResult:
    response = ask(base_url, item["question"])
    citations = response.get("citations", [])
    answer = response.get("answer", "").lower()

    source_hints = [h.lower() for h in item["expected_source_hints"]]
    citation_sources = [c.get("source", "").lower() for c in citations]

    retrieval_hit = bool(source_hints) and any(
        any(hint in src for hint in source_hints)
        for src in citation_sources
    )

    answer_terms = [t.lower() for t in item["expected_answer_terms"]]
    if citations and answer_terms:
        hits = sum(
            1 for c in citations
            if any(term in c.get("excerpt", "").lower() for term in answer_terms)
        )
        citation_relevance = hits / len(citations)
    else:
        citation_relevance = 1.0 if not item["expected_answer_terms"] else 0.0

    refused = not citations or any(p in answer for p in _DISCLAIMER_PHRASES)

    return EvalResult(
        question_id=item["id"],
        question=item["question"],
        retrieval_hit=retrieval_hit,
        citation_relevance=citation_relevance,
        should_refuse=item["should_refuse"],
        refused=refused,
        answer_snippet=response.get("answer", "")[:200],
        citation_sources=citation_sources,
    )


def run_eval(base_url: str, data_path: Path) -> int:
    data = json.loads(data_path.read_text(encoding="utf-8"))
    questions = data["questions"]

    results: list[EvalResult] = []
    for item in questions:
        label = item["question"][:60]
        print(f"  [{item['id']}] {label}...", end=" ", flush=True)
        try:
            result = evaluate_question(base_url, item)
            results.append(result)
            print("OK")
        except Exception as exc:
            print(f"ERROR: {exc}")

    in_scope = [r for r in results if not r.should_refuse]
    negative = [r for r in results if r.should_refuse]

    retrieval_hits = sum(1 for r in in_scope if r.retrieval_hit)
    avg_citation_relevance = (
        sum(r.citation_relevance for r in in_scope) / len(in_scope)
        if in_scope else 0.0
    )
    refusal_correct = sum(1 for r in negative if r.refused)

    print()
    print("=" * 60)
    print("EVALUATION REPORT")
    print("=" * 60)
    print(f"Total questions:         {len(results)}")
    print(f"In-scope questions:      {len(in_scope)}")
    print(f"Negative-control:        {len(negative)}")
    print()
    if in_scope:
        pct = retrieval_hits / len(in_scope) * 100
        print(f"Retrieval hit rate:      {retrieval_hits}/{len(in_scope)} ({pct:.0f}%)")
        print(f"Avg citation relevance:  {avg_citation_relevance:.2f}")
    if negative:
        print(f"Refusal correctness:     {refusal_correct}/{len(negative)}")
    print()

    print("DETAIL")
    print("-" * 60)
    all_passed = True
    for r in results:
        if r.should_refuse:
            status = "PASS" if r.refused else "FAIL"
            note = "correctly refused" if r.refused else "should have refused"
        else:
            status = "PASS" if r.retrieval_hit and r.citation_relevance >= 0.4 else "FAIL"
            note = (
                f"retrieval={'hit' if r.retrieval_hit else 'MISS'}, "
                f"citation_rel={r.citation_relevance:.2f}"
            )
        if status == "FAIL":
            all_passed = False
        print(f"  [{status}] {r.question_id}: {note}")
        if status == "FAIL":
            print(f"         sources: {r.citation_sources}")

    print()
    if all_passed:
        print("All checks passed.")
        return 0
    else:
        print("Some checks FAILED — see detail above.")
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Stroke RAG evaluation suite")
    parser.add_argument("--url", default="http://localhost:8000", help="Server base URL")
    parser.add_argument(
        "--data",
        default=str(Path(__file__).parent / "eval_data.json"),
        help="Path to eval_data.json",
    )
    args = parser.parse_args()
    sys.exit(run_eval(args.url, Path(args.data)))


if __name__ == "__main__":
    main()
