from medical_rag.validation_evaluation import compare_validation_report


def test_validation_reference_comparison_separates_deferred_from_wrong_decisions():
    def case(key, action):
        return {"file_hash": key, "expected_action": action}
    reference = {"cases": [case("human", "accept"), case("animal", "reject"), case("missing", "needs_review"), case("pending", "reject")]}
    report = {"results": {
        "a": {"file_hash": "human", "action": "accept", "decision": "accept", "confidence": .95, "reason_code": "in_scope"},
        "b": {"file_hash": "animal", "action": "accept", "decision": "accept", "confidence": .75, "reason_code": "in_scope"},
        "c": {"file_hash": "missing", "action": "needs_review", "decision": "uncertain", "confidence": 0, "reason_code": "no_abstract_found"},
    }}
    result = compare_validation_report(report, reference)
    check = next(row for row in result["threshold_checks"] if row["threshold"] == .7)
    assert check == {"threshold": .7, "comparable_cases": 2, "correct": 1, "false_accepts": 1, "deferred": 1, "agreement": .5}
    higher = next(row for row in result["threshold_checks"] if row["threshold"] == .8)
    assert higher["false_accepts"] == 0 and higher["deferred"] == 2
    assert result["structural_review_checks"] == {"total": 1, "held": 1}
    assert result["enforcement_ready"] is False
