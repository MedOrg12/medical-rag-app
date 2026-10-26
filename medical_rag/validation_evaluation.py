"""Offline comparison of a validation report with explicitly attributed reference labels."""
from __future__ import annotations

from typing import Any


def compare_validation_report(report: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    results = report.get("results", report)
    by_hash = {value["file_hash"]: value for value in results.values()}
    cases = []
    for case in reference["cases"]:
        result = by_hash.get(case["file_hash"])
        cases.append({**case, "observed_action": result["action"] if result else "not_assessed",
                      "reason_code": result["reason_code"] if result else None,
                      "model_decision": result["decision"] if result else None,
                      "confidence": result["confidence"] if result else None})
    thresholds = []
    for threshold in (.5, .7, .8, .9):
        comparable = correct = false_accepts = deferred = 0
        for case in cases:
            model_assessed = case["reason_code"] in {"in_scope", "out_of_scope", "insufficient_information"}
            if case["expected_action"] == "needs_review":
                continue
            if not model_assessed or case["confidence"] < threshold or case["model_decision"] == "uncertain":
                deferred += 1
                continue
            comparable += 1
            correct += case["model_decision"] == case["expected_action"]
            false_accepts += case["model_decision"] == "accept" and case["expected_action"] == "reject"
        thresholds.append({"threshold": threshold, "comparable_cases": comparable,
                           "correct": correct, "false_accepts": false_accepts,
                           "deferred": deferred, "agreement": correct / comparable if comparable else None})
    return {"reference_type": reference.get("review_type"),
            "reviewed_by": reference.get("reviewed_by"), "limitations": reference.get("limitations"),
            "sample_size": len(cases), "threshold_checks": thresholds, "cases": cases,
            "structural_review_checks": {"total": sum(c["expected_action"] == "needs_review" for c in cases),
                "held": sum(c["expected_action"] == c["observed_action"] == "needs_review" for c in cases)},
            "enforcement_ready": False,
            "enforcement_note": "A small assistant-labelled smoke sample does not establish independent clinical review or calibrate model confidence."}
