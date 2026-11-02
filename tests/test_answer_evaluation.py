from __future__ import annotations

import json

import pytest

from medical_rag.answer_evaluation import check_answer, evaluate_answers, load_answer_cases, main
from medical_rag.llm import Generator


@pytest.fixture
def cases():
    return {case["id"]: case for case in load_answer_cases()["cases"]}


def test_cases_cover_synthesis_partial_and_unsupported_questions(cases):
    assert {case["coverage"] for case in cases.values()} == {"supported", "partial", "unsupported"}
    assert len(cases["combine_sources"]["passages"]) == 2
    assert cases["combine_sources"]["required_citations"] == [1, 2]
    assert cases["partial_outcome"]["limitation_terms"]
    assert not cases["empty_context"]["passages"]
    assert all(case["review_criteria"] for case in cases.values())


def test_synthesis_checks_require_both_evidence_sources(cases):
    case = cases["combine_sources"]
    answer = (
        "The pilot identified two complementary needs: plain language for unfamiliar terms [1], "
        "and written reminders to revisit information later [2]."
    )
    assert check_answer(case, answer) == []
    assert "Missing required evidence citation" in check_answer(case, answer.replace("[2]", ""))
    assert "Citation references a passage that was not provided" in check_answer(case, answer + " [9]")


def test_partial_answer_needs_supported_content_and_a_specific_limitation(cases):
    case = cases["partial_outcome"]
    answer = (
        "The pilot tracked which reminders caregivers opened [1]. Hospital admissions were not "
        "measured, so the passage cannot tell us whether admissions changed."
    )
    assert check_answer(case, answer) == []
    blanket_refusal = "I can't answer because hospital admissions were not measured."
    assert any(issue.startswith("Missing supported concept") for issue in check_answer(case, blanket_refusal))
    unsupported_conclusion = "It tracked which reminders were opened [1] and reduced admissions."
    assert "Missing evidence limitation" in check_answer(case, unsupported_conclusion)


def test_unsupported_medication_answer_cannot_guess_a_dose(cases):
    case = cases["unsupported_dose"]
    assert check_answer(case, "The supplied pilot does not provide medication dosing information.") == []
    issues = check_answer(case, "I don't have enough information, but take 10 mg [1].")
    assert "Answer contains a prohibited unsupported detail" in issues
    assert any(issue.startswith("Missing supported concept") for issue in check_answer(case, "I can't provide medical advice."))
    assert "Answer contains a prohibited unsupported detail" in check_answer(case, "The sources do not cover this. Call emergency medical services.")


def test_citation_can_support_an_evidence_gap_even_when_question_is_unsupported(cases):
    answer = "The supplied pilot did not evaluate medications [1], so it cannot establish a dose."
    assert check_answer(cases["unsupported_dose"], answer) == []
    assert "Citation references a passage that was not provided" in check_answer(
        cases["empty_context"], "No relevant evidence was retrieved [1]."
    )


def test_eval_does_not_treat_backend_fallback_as_synthesis(cases):
    answer = (
        "Plain language [1] and written reminders [2].\n"
        "Generation backend was unavailable, so this answer uses extractive retrieval."
    )
    assert any("Generation backend failed" in issue for issue in check_answer(cases["combine_sources"], answer))


def test_eval_supplies_fixed_passages_once_and_preserves_review_rubric(cases):
    class RecordingGenerator(Generator):
        model_name = "test"

        def __init__(self):
            self.calls = []

        def generate(self, question, results, answer_mode="patient"):
            self.calls.append((question, results, answer_mode))
            return "The pilot tracked opened reminders [1]. Hospital admissions were not measured."

    generator = RecordingGenerator()
    report = evaluate_answers(generator, [cases["partial_outcome"]], "clinician")

    assert report["checks_passed"]
    assert report["review_required"] is True
    assert len(generator.calls) == 1
    assert generator.calls[0][0] == cases["partial_outcome"]["question"]
    assert generator.calls[0][1][0].chunk.text == cases["partial_outcome"]["passages"][0]
    assert generator.calls[0][2] == "clinician"
    assert report["results"][0]["review_criteria"] == cases["partial_outcome"]["review_criteria"]


def test_eval_records_provider_failure(cases):
    class BrokenGenerator(Generator):
        model_name = "broken"

        def generate(self, *args, **kwargs):
            raise RuntimeError("provider unavailable")

    report = evaluate_answers(BrokenGenerator(), [cases["combine_sources"]])
    assert not report["checks_passed"]
    assert report["results"][0]["error"] == "provider unavailable"


def test_cli_requires_a_generative_backend(monkeypatch):
    monkeypatch.setenv("RAG_GENERATION_BACKEND", "extractive")
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_cli_writes_inspectable_report_and_returns_failure_for_failed_checks(monkeypatch, tmp_path, capsys):
    class UncitedGenerator(Generator):
        model_name = "test"

        def generate(self, *args, **kwargs):
            return "An answer without the required evidence."

    monkeypatch.setenv("RAG_GENERATION_BACKEND", "ollama")
    monkeypatch.setattr("medical_rag.answer_evaluation.make_generator", lambda settings: UncitedGenerator())
    output = tmp_path / "reports" / "answers.json"

    assert main(["--mode", "clinician", "--output", str(output)]) == 1
    report = json.loads(output.read_text())
    assert report["answer_mode"] == "clinician"
    assert report["version"] == load_answer_cases()["version"]
    assert report["review_required"] is True
    assert report["results"][0]["passages"]
    assert "Missing required evidence citation" in report["results"][0]["issues"]
    assert "CHECKS FAILED" in capsys.readouterr().out
