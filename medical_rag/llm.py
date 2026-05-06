from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass

from medical_rag.config import Settings
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


class Generator(ABC):
    model_name: str

    @abstractmethod
    def generate(self, question: str, results: list[SearchResult]) -> str:
        raise NotImplementedError


@dataclass
class ExtractiveGenerator(Generator):
    model_name: str = "extractive"

    def generate(self, question: str, results: list[SearchResult]) -> str:
        if not results:
            return (
                "I could not find indexed stroke literature that answers that question. "
                "Add or ingest more source documents, then try again."
            )

        passages = []
        for citation_id, result in enumerate(results[:3], start=1):
            excerpt = _best_excerpt(result.chunk.text, question, max_chars=520)
            passages.append(f"{excerpt} [{citation_id}]")

        return (
            "The most relevant indexed passages say:\n\n"
            + "\n\n".join(passages)
            + f"\n\n{SAFETY_NOTICE}"
        )


@dataclass
class OllamaGenerator(Generator):
    base_url: str
    model_name: str
    temperature: float = 0.1
    timeout_seconds: float = 20.0

    def generate(self, question: str, results: list[SearchResult]) -> str:
        if not results:
            return (
                "I could not find indexed stroke literature that answers that question. "
                "Add or ingest more source documents, then try again."
            )

        payload = json.dumps(
            {
                "model": self.model_name,
                "stream": False,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": _user_prompt(question, results)},
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

    def generate(self, question: str, results: list[SearchResult]) -> str:
        try:
            return self.primary.generate(question, results)
        except RuntimeError:
            fallback_answer = self.fallback.generate(question, results)
            return (
                fallback_answer
                + "\n\nGeneration backend was unavailable, so this answer uses extractive retrieval."
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


def _user_prompt(question: str, results: list[SearchResult]) -> str:
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
        "matching bracketed number. If the passages do not answer the question, say that plainly.\n\n"
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
