"""Controlled generation checks with fixed evidence, independent of corpus retrieval."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from medical_rag.config import Settings
from medical_rag.llm import Generator, make_generator
from medical_rag.types import Chunk, SearchResult

DEFAULT_ANSWER_EVAL_PATH = Path(__file__).with_name("answer_eval_data.json")


def load_answer_cases(path: Path = DEFAULT_ANSWER_EVAL_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def case_passages(case: dict[str, Any]) -> list[SearchResult]:
    return [
        SearchResult(
            chunk=Chunk(
                id=f"{case['id']}-{index}",
                text=text,
                metadata={"source_id": f"{case['id']}-note-{index}.txt", "page": 1},
            ),
            score=1.0,
            rank=index,
        )
        for index, text in enumerate(case["passages"], start=1)
    ]


def check_answer(case: dict[str, Any], answer: str) -> list[str]:
    """Mechanical regression checks only; semantic support and coherence need review."""
    issues = []
    normalized = " ".join(answer.casefold().replace("\u2019", "'").split())
    citations = {int(value) for value in re.findall(r"\[(\d+)\]", answer)}
    valid_ids = set(range(1, len(case["passages"]) + 1))
    if not answer.strip():
        issues.append("Empty answer")
    if "generation backend was unavailable" in normalized:
        issues.append("Generation backend failed; extractive fallback is not a synthesis result")
    if citations - valid_ids:
        issues.append("Citation references a passage that was not provided")
    if set(case.get("required_citations", [])) - citations:
        issues.append("Missing required evidence citation")
    for concept in case.get("required_concepts", []):
        if not any(term.casefold() in normalized for term in concept):
            issues.append(f"Missing supported concept: {' / '.join(concept)}")
    limitation_terms = case.get("limitation_terms", [])
    if limitation_terms and not any(term.casefold() in normalized for term in limitation_terms):
        issues.append("Missing evidence limitation")
    if any(re.search(pattern, answer, re.IGNORECASE) for pattern in case.get("forbidden_patterns", [])):
        issues.append("Answer contains a prohibited unsupported detail")
    return issues


def evaluate_answers(
    generator: Generator,
    cases: list[dict[str, Any]],
    answer_mode: str = "patient",
) -> dict[str, Any]:
    results = []
    for case in cases:
        try:
            answer = generator.generate(case["question"], case_passages(case), answer_mode=answer_mode)
            issues = check_answer(case, answer)
            error = None
        except (RuntimeError, ValueError) as exc:
            answer = ""
            error = str(exc)
            issues = [f"Generation error: {error}"]
        results.append({
            "id": case["id"],
            "coverage": case["coverage"],
            "question": case["question"],
            "passages": case["passages"],
            "answer": answer,
            "checks_passed": not issues,
            "issues": issues,
            "error": error,
            "review_criteria": case["review_criteria"],
        })
    return {
        "model": generator.model_name,
        "answer_mode": answer_mode,
        "checks_passed": all(item["checks_passed"] for item in results),
        "review_required": True,
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_ANSWER_EVAL_PATH)
    parser.add_argument("--mode", choices=["patient", "clinician"], default="patient")
    parser.add_argument("--output", type=Path, help="Optional JSON report, including answers and review criteria")
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    if settings.generation_backend not in {"api", "ollama"}:
        parser.error("Set RAG_GENERATION_BACKEND=api or ollama to evaluate synthesized answers.")
    data = load_answer_cases(args.data)
    generator = make_generator(settings)
    print(f"Running {len(data['cases'])} controlled cases with {generator.model_name} ({args.mode})...", flush=True)
    report = evaluate_answers(generator, data["cases"], args.mode)
    report["version"] = data["version"]
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    for result in report["results"]:
        status = "CHECKS PASSED" if result["checks_passed"] else "CHECKS FAILED"
        print(f"{status}: {result['id']} ({result['coverage']})")
        for issue in result["issues"]:
            print(f"  {issue}")
        print(result["answer"])
        for criterion in result["review_criteria"]:
            print(f"  Review: {criterion}")
        print()
    print("These are heuristic checks. Review coherence and claim support against the supplied passages.")
    return 0 if report["checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
