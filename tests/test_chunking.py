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


def test_chunk_pages_keeps_section_across_pages() -> None:
    pages = [
        PageText(
            source_id="guideline.pdf",
            source_path="/tmp/guideline.pdf",
            title="Guideline",
            page_number=10,
            text="RECOMMENDATIONS\nPatients with suspected stroke should receive organized triage.",
        ),
        PageText(
            source_id="guideline.pdf",
            source_path="/tmp/guideline.pdf",
            title="Guideline",
            page_number=11,
            text="Stroke unit care improves coordination and recovery planning.",
        ),
    ]

    chunks = chunk_pages(pages, chunk_size_chars=400, chunk_overlap_chars=60)

    assert len(chunks) == 1
    assert chunks[0].text.startswith("Section: Recommendations")
    assert chunks[0].metadata["section"] == "Recommendations"
    assert chunks[0].metadata["page_start"] == 10
    assert chunks[0].metadata["page_end"] == 11
    assert chunks[0].metadata["page_range"] == "10-11"


def test_chunk_pages_omits_reference_lists() -> None:
    page = PageText(
        source_id="trial.pdf",
        source_path="/tmp/trial.pdf",
        title="Trial",
        page_number=12,
        text=(
            "RESULTS\nMobile stroke unit care reduced time to treatment.\n"
            "REFERENCES\n1. Example Citation. 2. Another Citation."
        ),
    )

    chunks = chunk_pages([page], chunk_size_chars=300, chunk_overlap_chars=40)
    joined = " ".join(chunk.text for chunk in chunks)

    assert "Mobile stroke unit care" in joined
    assert "Example Citation" not in joined
    assert chunks[0].metadata["section"] == "Results"
