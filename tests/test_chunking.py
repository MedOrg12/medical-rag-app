from medical_rag.chunking import chunk_pages, split_text
from medical_rag.types import PageText


def test_split_text_respects_size_for_long_text() -> None:
    text = " ".join(["stroke rehabilitation recovery evidence"] * 120)

    chunks = split_text(text, chunk_size_chars=180, chunk_overlap_chars=30)

    assert len(chunks) > 1
    assert all(len(chunk) <= 180 for chunk in chunks)


def test_chunk_pages_adds_page_metadata() -> None:
    page = PageText(
        source_id="paper.pdf",
        source_path="/tmp/paper.pdf",
        title="Stroke Paper",
        page_number=7,
        text="Stroke systems of care coordinate prehospital triage and hospital treatment.",
    )

    chunks = chunk_pages([page], chunk_size_chars=200, chunk_overlap_chars=20)

    assert len(chunks) == 1
    assert chunks[0].metadata["source_id"] == "paper.pdf"
    assert chunks[0].metadata["page"] == 7
    assert chunks[0].id
