import json

import pytest

from medical_rag.evidence import (
    SourceCatalog,
    citation_ids,
    document_path,
    make_citation,
    partition_evidence,
)
from medical_rag.types import Chunk, Citation, SearchResult


@pytest.mark.parametrize("text, expected", [
    ("Facts [2] [1] [2].", {1, 2}),
    ("Facts [1, 3] [4-6].", {1, 3, 4, 5, 6}),
    ("[0] [5-3] [1-999999999]", {0, 1, 3, 5, 999999999}),
    ("No citations.", set()),
])
def test_citation_number_parsing(text, expected):
    assert citation_ids(text) == expected


def test_invalid_and_missing_citations_are_flagged_without_claim_verification():
    evidence = [Citation(i, "notes.txt", 1, f"c{i}", 0.9, "Stroke recovery.") for i in (1, 2)]
    used, unused, validation = partition_evidence("Fact [2] [99].", evidence)
    assert [item.id for item in used] == [2]
    assert [item.id for item in unused] == [1]
    assert validation["invalid_ids"] == [99]
    assert validation["status"] == "needs_review"
    assert validation["claim_support_verified"] is False
    assert partition_evidence("No citations.", evidence)[2]["warnings"]
    assert partition_evidence("No evidence.", [])[2]["status"] == "no_citations"


def test_citation_keeps_full_text_and_pdf_page_range(tmp_path):
    pdf = tmp_path / "guideline.pdf"
    pdf.write_bytes(b"%PDF-1.7\n")
    text = "A full supporting passage. " * 30
    result = SearchResult(Chunk("chunk-id", text, {
        "source_id": pdf.name, "source_path": str(pdf), "title": "Guideline",
        "page": 3, "page_start": 3, "page_end": 4, "section": "Recovery",
        "publisher": "Example society", "publication_year": 2025,
    }), 0.8, 1)
    citation = make_citation(result, 2, tmp_path)
    assert citation.id == 2
    assert citation.text == text
    assert len(citation.excerpt) <= 320
    assert citation.page == 3 and citation.page_end == 4
    assert citation.title == "Guideline" and citation.section == "Recovery"
    assert citation.publisher == "Example society" and citation.publication_year == 2025
    assert citation.document_url == "/evidence/chunk-id/document#page=3"
    assert "source_path" not in citation.to_dict()


def test_original_document_rejects_outside_root_symlinks_nonpdfs_and_missing_files(tmp_path):
    root = tmp_path / "corpus"
    root.mkdir()
    outside = tmp_path / "private.pdf"
    outside.write_bytes(b"%PDF-1.7\n")
    link = root / "link.pdf"
    link.symlink_to(outside)
    invalid = root / "not-a-pdf.pdf"
    invalid.write_text("Not a PDF")
    text = root / "notes.txt"
    text.write_text("Notes")
    for path in (outside, link, invalid, text, root / "missing.pdf"):
        assert document_path(Chunk("id", "", {"source_path": str(path)}), root) is None
    valid = root / "valid.pdf"
    valid.write_bytes(b"%PDF-1.7\n")
    assert document_path(Chunk("id", "", {"source_path": str(valid)}), root) == valid
    assert document_path(Chunk("id", "", {"source_path": str(valid)}), valid) == valid


def test_catalog_enriches_existing_results_without_reingestion_and_reloads(tmp_path):
    path = tmp_path / "catalog.json"
    catalog = SourceCatalog(path)
    result = SearchResult(Chunk("id", "Passage", {"source_id": "guide.pdf", "title": "Old title"}), 0.5, 1)
    assert catalog.enrich(result) == result
    path.write_text(json.dumps({"guide.pdf": {"title": "Curated title", "publisher": "Society", "publication_year": 2024}}))
    enriched = catalog.enrich(result)
    assert enriched.chunk.metadata["title"] == "Curated title"
    assert enriched.chunk.metadata["publication_year"] == 2024
    assert result.chunk.metadata["title"] == "Old title"
    path.write_text(json.dumps({"guide.pdf": {"publication_year": 2025}}))
    assert catalog.enrich(result).chunk.metadata["publication_year"] == 2025
    path.unlink()
    assert catalog.enrich(result) == result
    assert make_citation(result, 1, tmp_path).publication_year is None


@pytest.mark.parametrize("entry", [{"publication_year": "2024"}, {"publisher": 7}, {"source_path": "/private.pdf"}])
def test_catalog_rejects_invalid_metadata_and_cannot_change_document_paths(tmp_path, entry):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({"guide.pdf": entry}))
    with pytest.raises(ValueError):
        SourceCatalog(path).enrich(SearchResult(Chunk("id", "Passage", {"source_id": "guide.pdf"}), 1.0, 1))
