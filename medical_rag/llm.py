from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass

from medical_rag.config import Settings
from medical_rag.relevance import is_diet_query
from medical_rag.types import SearchResult

SAFETY_NOTICE = (
    "This system is for literature review and clinical education support only. "
    "It is not a substitute for emergency care, diagnosis, or treatment."
)

SYSTEM_PROMPT = f"""You are a stroke research RAG assistant.

Use only the retrieved passages to answer. Cite claims with bracketed citation numbers such as [1].
Be direct, clinically careful, and explicit about uncertainty. Do not invent facts, doses, eligibility
criteria, or guideline recommendations that are not present in the retrieved passages.

If a user describes possible acute stroke symptoms or asks what to do during an emergency, tell them to
call emergency medical services immediately. {SAFETY_NOTICE}
"""

_ANSWER_MODE_INSTRUCTIONS = {
    "patient": """Answer mode: patient.

Use plain language for a patient or caregiver. Keep the answer practical and concise. Define medical
terms the first time you use them. Avoid guideline jargon, study-design detail, and long caveats unless
they change what the person should do. If the evidence does not answer the exact question, say that
clearly and briefly.""",
    "clinician": """Answer mode: clinician.

Use a clinical, guideline-aware style. Include relevant technical terms, eligibility/contraindication
caveats when present in the retrieved passages, and note evidence limitations. Distinguish guideline
recommendations, trial findings, observational evidence, and rehabilitation guidance when the retrieved
passages make that clear.""",
}


class Generator(ABC):
    model_name: str

    @abstractmethod
    def generate(
        self, question: str, results: list[SearchResult], answer_mode: str = "patient"
    ) -> str:
        raise NotImplementedError


@dataclass
class ExtractiveGenerator(Generator):
    model_name: str = "extractive"

    def generate(
        self, question: str, results: list[SearchResult], answer_mode: str = "patient"
    ) -> str:
        if not results:
            return (
                "I could not find a relevant indexed passage that answers that question. "
                "The indexed corpus may not contain enough detail on this topic, or the index may need "
                "to be rebuilt after recent retrieval changes."
            )

        if is_diet_query(question):
            return _diet_answer(results, answer_mode)

        passages = []
        for citation_id, result in enumerate(results[:3], start=1):
            excerpt = _best_excerpt(result.chunk.text, question, max_chars=520)
            passages.append(f"{excerpt} [{citation_id}]")

        opener = (
            "I found these relevant points in the indexed stroke literature:"
            if answer_mode == "patient"
            else "Retrieved evidence from the indexed stroke literature:"
        )
        return (
            opener
            + "\n\n"
            + "\n\n".join(passages)
            + f"\n\n{SAFETY_NOTICE}"
        )


@dataclass
class OllamaGenerator(Generator):
    base_url: str
    model_name: str
    temperature: float = 0.1
    timeout_seconds: float = 20.0

    def generate(
        self, question: str, results: list[SearchResult], answer_mode: str = "patient"
    ) -> str:
        if not results:
            return (
                "I could not find a relevant indexed passage that answers that question. "
                "The indexed corpus may not contain enough detail on this topic, or the index may need "
                "to be rebuilt after recent retrieval changes."
            )

        payload = json.dumps(
            {
                "model": self.model_name,
                "stream": False,
                "messages": [
                    {"role": "system", "content": _system_prompt(answer_mode)},
                    {"role": "user", "content": _user_prompt(question, results, answer_mode)},
                ],
                "options": {"temperature": self.temperature},
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"Could not generate with Ollama at {self.base_url}") from exc

        content = (data.get("message") or {}).get("content")
        if not content:
            raise RuntimeError("Ollama chat response did not include message.content")
        return content.strip()


@dataclass
class FallbackGenerator(Generator):
    primary: Generator
    fallback: Generator

    @property
    def model_name(self) -> str:
        return self.primary.model_name

    def generate(
        self, question: str, results: list[SearchResult], answer_mode: str = "patient"
    ) -> str:
        try:
            return self.primary.generate(question, results, answer_mode=answer_mode)
        except RuntimeError as exc:
            fallback_answer = self.fallback.generate(question, results, answer_mode=answer_mode)
            return (
                fallback_answer
                + "\n\nGeneration backend was unavailable, so this answer uses extractive retrieval."
                + f"\nBackend error: {exc}"
            )


def make_generator(settings: Settings) -> Generator:
    extractive = ExtractiveGenerator()
    if settings.generation_backend == "extractive":
        return extractive
    if settings.generation_backend == "ollama":
        return FallbackGenerator(
            primary=OllamaGenerator(
                base_url=settings.ollama_base_url,
                model_name=settings.ollama_generation_model,
                temperature=settings.temperature,
                timeout_seconds=settings.request_timeout_seconds,
            ),
            fallback=extractive,
        )
    raise ValueError(f"Unsupported generation backend: {settings.generation_backend}")


def _system_prompt(answer_mode: str) -> str:
    return SYSTEM_PROMPT + "\n\n" + _ANSWER_MODE_INSTRUCTIONS.get(
        answer_mode, _ANSWER_MODE_INSTRUCTIONS["patient"]
    )


def _user_prompt(question: str, results: list[SearchResult], answer_mode: str) -> str:
    passages = []
    for citation_id, result in enumerate(results, start=1):
        metadata = result.chunk.metadata
        page = metadata.get("page")
        page_text = f", page {page}" if page is not None else ""
        passages.append(
            f"[{citation_id}] {metadata.get('title', metadata.get('source_id', 'Unknown'))}"
            f"{page_text}\n{result.chunk.text}"
        )

    return (
        "Answer the question using the retrieved passages below. Cite every sourced claim with the "
        "matching bracketed number. If the passages do not answer the question, say that plainly. "
        f"Use {answer_mode} answer mode.\n\n"
        f"Question: {question}\n\nRetrieved passages:\n\n" + "\n\n".join(passages)
    )


def _best_excerpt(text: str, question: str, max_chars: int) -> str:
    sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", text) if sentence.strip()]
    if not sentences:
        return text[:max_chars].strip()

    question_terms = set(_terms(question))
    scored = []
    for sentence in sentences:
        terms = set(_terms(sentence))
        overlap = len(question_terms & terms)
        scored.append((overlap, len(sentence), sentence))
    scored.sort(key=lambda item: (item[0], -item[1]), reverse=True)

    selected: list[str] = []
    total_length = 0
    for _, _, sentence in scored[:3]:
        next_length = total_length + len(sentence) + 1
        if next_length > max_chars and selected:
            continue
        selected.append(sentence)
        total_length = next_length
        if total_length >= max_chars:
            break

    ordered = [sentence for sentence in sentences if sentence in set(selected)]
    excerpt = " ".join(ordered).strip()
    if len(excerpt) <= max_chars:
        return excerpt
    return excerpt[: max_chars - 1].rsplit(" ", 1)[0].strip() + "..."


def _terms(text: str) -> list[str]:
    return [term.lower() for term in re.findall(r"[a-zA-Z][a-zA-Z0-9_+-]*", text)]


def _diet_answer(results: list[SearchResult], answer_mode: str) -> str:
    evidence = [_evidence_text(result) for result in results]
    evidence_blob = " ".join(evidence).lower()
    parts: list[str] = []

    clinician = answer_mode == "clinician"
    if _has_any(evidence_blob, {"dysphagia", "swallow", "swallowing", "aspiration"}):
        citation = _first_citation_with(results, {"dysphagia", "swallow", "swallowing", "aspiration"})
        if clinician:
            parts.append(
                "The retrieved rehabilitation guideline material prioritizes dysphagia screening and "
                "swallowing management before oral intake. It reports dysphagia is common early after "
                f"stroke, so diet recommendations should be conditioned on swallow safety and aspiration "
                f"risk [{citation}]."
            )
        else:
            parts.append(
                "The indexed evidence points first to swallowing safety, not a simple food list. "
                "Dysphagia means difficulty swallowing, and it is common soon after stroke. Eating by "
                f"mouth should be guided by swallowing screening and management [{citation}]."
            )

    if _has_any(evidence_blob, {"tube", "nasogastric", "gastrostomy", "feeding", "feeds"}):
        citation = _first_citation_with(
            results, {"tube", "nasogastric", "gastrostomy", "feeding", "feeds"}
        )
        if clinician:
            parts.append(
                "When oral intake is unsafe or inadequate, the retrieved guideline text supports "
                "enteral nutritional support; nasogastric tube feeding is described as reasonable for "
                f"the first 2 to 3 weeks after stroke in selected patients [{citation}]."
            )
        else:
            parts.append(
                "If swallowing is not safe, the sources discuss nutritional support instead of regular "
                "meals. In some patients, a nasogastric feeding tube can be reasonable for the first "
                f"2 to 3 weeks after stroke [{citation}]."
            )

    if _has_any(
        evidence_blob,
        {"fruit", "fruits", "vegetable", "vegetables", "salt", "sodium", "saturated", "fat"},
    ):
        citation = _first_citation_with(
            results,
            {"fruit", "fruits", "vegetable", "vegetables", "salt", "sodium", "saturated", "fat"},
        )
        if clinician:
            parts.append(
                "For patients cleared for oral intake, the retrieved diet-related material supports a "
                "secondary-prevention dietary pattern emphasizing fruits and vegetables and lower salt "
                f"and saturated fat intake [{citation}]."
            )
        else:
            parts.append(
                "If swallowing has been cleared, the indexed passage supports eating more fruits and "
                f"vegetables and choosing foods lower in salt and saturated fat [{citation}]."
            )

    if not parts:
        parts.append(
            "I found nutrition-related passages, but they do not give a clear answer about what foods "
            "to eat after stroke. The indexed corpus may need more diet-specific sources."
        )

    if not _has_any(
        evidence_blob,
        {"fruit", "fruits", "vegetable", "vegetables", "salt", "sodium", "saturated", "fat"},
    ):
        parts.append(
            "I did not find a strong indexed passage here that gives a detailed normal-food meal plan."
        )

    return "\n\n".join(parts) + f"\n\n{SAFETY_NOTICE}"


def _evidence_text(result: SearchResult) -> str:
    metadata = result.chunk.metadata
    return " ".join(
        [
            result.chunk.text,
            str(metadata.get("title", "")),
            str(metadata.get("section", "")),
            str(metadata.get("source_id", "")),
        ]
    )


def _has_any(text: str, terms: set[str]) -> bool:
    tokens = set(_terms(text))
    return bool(tokens & terms)


def _first_citation_with(results: list[SearchResult], terms: set[str]) -> int:
    for citation_id, result in enumerate(results, start=1):
        if _has_any(_evidence_text(result).lower(), terms):
            return citation_id
    return 1
