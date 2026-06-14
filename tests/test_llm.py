from medical_rag.llm import ExtractiveGenerator, FallbackGenerator, Generator
from medical_rag.types import Chunk, SearchResult


class BrokenGenerator(Generator):
    model_name = "broken"

    def generate(
        self, question: str, results: list[SearchResult], answer_mode: str = "patient"
    ) -> str:
        raise RuntimeError("Could not generate with Ollama at http://localhost:11434")


def test_fallback_generator_includes_backend_error() -> None:
    generator = FallbackGenerator(primary=BrokenGenerator(), fallback=ExtractiveGenerator())

    answer = generator.generate("What should I eat after stroke?", [])

    assert "Generation backend was unavailable" in answer
    assert "Could not generate with Ollama" in answer


def test_extractive_diet_answer_has_patient_and_clinician_modes() -> None:
    result = SearchResult(
        chunk=Chunk(
            id="diet",
            text=(
                "Dysphagia is common after stroke. Tube feeds via nasogastric route are "
                "reasonable for the first 2 to 3 weeks after stroke. Fruits and vegetables "
                "and lower salt and saturated fat intake can support secondary prevention."
            ),
            metadata={"source_id": "rehab.txt", "page": 1},
        ),
        score=0.5,
        rank=1,
    )
    generator = ExtractiveGenerator()

    patient_answer = generator.generate(
        "What should I eat after a stroke?", [result], answer_mode="patient"
    )
    clinician_answer = generator.generate(
        "What should I eat after a stroke?", [result], answer_mode="clinician"
    )

    assert "Dysphagia means difficulty swallowing" in patient_answer
    assert "aspiration risk" in clinician_answer
    assert patient_answer != clinician_answer
