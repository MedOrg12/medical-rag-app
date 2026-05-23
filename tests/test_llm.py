from medical_rag.llm import ExtractiveGenerator, FallbackGenerator, Generator
from medical_rag.types import SearchResult


class BrokenGenerator(Generator):
    model_name = "broken"

    def generate(self, question: str, results: list[SearchResult]) -> str:
        raise RuntimeError("Could not generate with Ollama at http://localhost:11434")


def test_fallback_generator_includes_backend_error() -> None:
    generator = FallbackGenerator(primary=BrokenGenerator(), fallback=ExtractiveGenerator())

    answer = generator.generate("What should I eat after stroke?", [])

    assert "Generation backend was unavailable" in answer
    assert "Could not generate with Ollama" in answer
