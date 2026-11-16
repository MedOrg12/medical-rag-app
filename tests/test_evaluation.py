from __future__ import annotations

from dataclasses import replace

from medical_rag.evaluation import EvalQuestion, evaluate_rag
from medical_rag.types import Citation, RagAnswer


class FakeRag:
    def ask(
        self,
        question: str,
        top_k: int | None = None,
        answer_mode: str | None = None,
    ) -> RagAnswer:
        if "capital" in question.lower():
            return RagAnswer(
                question=question,
                answer="I could not find relevant indexed evidence for that question.",
                citations=[],
                retrieval_model="test",
                generation_model="test",
                answer_mode=answer_mode or "patient",
                safety_notice="test",
            )

        return RagAnswer(
            question=question,
            answer="Dysphagia means difficulty swallowing after stroke. Texture modified foods may be used.",
            citations=[
                Citation(
                    id=1,
                    source="stroke rehabilitation dysphagia guideline.pdf",
                    page=12,
                    chunk_id="abc",
                    score=0.9,
                    excerpt="Dysphagia and swallow rehabilitation can include texture modified diets.",
                )
            ],
            retrieval_model="test",
            generation_model="test",
            answer_mode=answer_mode or "patient",
            safety_notice="test",
        )


def test_evaluate_rag_scores_in_scope_and_negative_controls() -> None:
    questions = [
        EvalQuestion(
            id="dysphagia",
            question="What is dysphagia after stroke?",
            expected_source_hints=["dysphagia", "swallow"],
            expected_answer_terms=["dysphagia", "swallowing", "texture", "modified"],
        ),
        EvalQuestion(
            id="negative",
            question="What is the capital of France?",
            expected_source_hints=[],
            expected_answer_terms=[],
            should_refuse=True,
        ),
    ]

    result = evaluate_rag(FakeRag(), questions=questions, version=1, top_k=3, answer_mode="patient")

    assert result.passed
    assert result.summary.total_questions == 2
    assert result.summary.passed_questions == 2
    assert result.summary.retrieval_hit_rate == 1.0
    assert result.summary.refusal_accuracy == 1.0
    assert result.results[0].answer_term_coverage >= 0.75
    assert result.results[1].refused


def test_evaluate_rag_fails_when_answer_coverage_is_too_low() -> None:
    class ThinAnswerRag:
        def ask(
            self,
            question: str,
            top_k: int | None = None,
            answer_mode: str | None = None,
        ) -> RagAnswer:
            return RagAnswer(
                question=question,
                answer="Dysphagia can happen after stroke.",
                citations=[
                    Citation(
                        id=1,
                        source="stroke rehabilitation dysphagia guideline.pdf",
                        page=12,
                        chunk_id="abc",
                        score=0.9,
                        excerpt=(
                            "Dysphagia and swallow rehabilitation can include "
                            "texture modified diets."
                        ),
                    )
                ],
                retrieval_model="test",
                generation_model="test",
                answer_mode=answer_mode or "patient",
                safety_notice="test",
            )

    questions = [
        EvalQuestion(
            id="dysphagia",
            question="What is dysphagia after stroke?",
            expected_source_hints=["dysphagia", "swallow"],
            expected_answer_terms=["dysphagia", "swallowing", "texture", "modified"],
        )
    ]

    result = evaluate_rag(ThinAnswerRag(), questions=questions, version=1)

    assert not result.passed
    assert result.summary.failed_questions == 1
    assert result.results[0].retrieval_hit is True
    assert result.results[0].citation_term_coverage >= 0.5
    assert result.results[0].answer_term_coverage < 0.4


def test_evaluate_rag_records_question_errors() -> None:
    class FailingRag:
        def ask(self, *_args: object, **_kwargs: object) -> RagAnswer:
            raise FileNotFoundError("index missing")

    questions = [
        EvalQuestion(
            id="q1",
            question="What is dysphagia?",
            expected_source_hints=["dysphagia"],
            expected_answer_terms=["swallow"],
        )
    ]

    result = evaluate_rag(FailingRag(), questions=questions, version=1)

    assert not result.passed
    assert result.summary.error_questions == 1
    assert result.results[0].status == "error"
    assert result.results[0].error == "index missing"


def test_retrieval_hit_does_not_make_an_uncited_answer_pass():
    class UncitedRag(FakeRag):
        def ask(self, question, **kwargs):
            response = super().ask(question, **kwargs)
            return replace(response, citations=[], retrieved_evidence=response.citations)

    question = EvalQuestion("dysphagia", "What is dysphagia?", ["dysphagia"], ["swallowing", "texture"])
    result = evaluate_rag(UncitedRag(), questions=[question]).results[0]
    assert result.retrieval_hit is True
    assert result.citation_term_coverage == 0
    assert result.status == "fail"
    assert result.refused is False
    assert result.retrieved_evidence and not result.citations


def test_uncited_out_of_scope_answer_is_not_automatically_a_refusal():
    class UngroundedRag(FakeRag):
        def ask(self, question, **kwargs):
            return replace(super().ask(question, **kwargs), answer="Paris is the capital of France.")

    question = EvalQuestion("negative", "What is the capital of France?", [], [], should_refuse=True)
    result = evaluate_rag(UngroundedRag(), questions=[question]).results[0]
    assert result.status == "fail"
    assert result.refused is False
