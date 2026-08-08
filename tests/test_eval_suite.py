"""
Pytest integration for the eval suite.

Requires the server to be running on http://localhost:8000 and the index
to be ingested before running.

Skip eval tests in CI:
    pytest -m "not eval"
"""

from __future__ import annotations

import pytest
from pathlib import Path

EVAL_DATA = Path(__file__).parent / "eval_data.json"


@pytest.mark.eval
def test_eval_suite_passes():
    """Full eval suite must report zero failures against a running server."""
    from tests.run_eval import run_eval

    exit_code = run_eval("http://localhost:8000", EVAL_DATA)
    assert exit_code == 0, "Eval suite reported failures — see stdout for detail"


def test_eval_data_is_valid_json():
    """eval_data.json must exist and be valid JSON with required fields."""
    import json

    assert EVAL_DATA.exists(), "tests/eval_data.json not found"
    data = json.loads(EVAL_DATA.read_text(encoding="utf-8"))
    assert "version" in data
    assert "questions" in data
    assert len(data["questions"]) >= 7, "Expect at least 7 questions"

    required_keys = {"id", "question", "expected_source_hints", "expected_answer_terms", "should_refuse"}
    for q in data["questions"]:
        missing = required_keys - set(q.keys())
        assert not missing, f"Question {q.get('id')} missing keys: {missing}"

    negative = [q for q in data["questions"] if q["should_refuse"]]
    assert len(negative) >= 1, "At least one negative-control question required"


def test_run_eval_help_exits_cleanly():
    """run_eval.py --help should exit without error (no server needed)."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "run_eval.py"), "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--url" in result.stdout
    assert "--data" in result.stdout
