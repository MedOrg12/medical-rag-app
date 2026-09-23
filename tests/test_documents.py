from __future__ import annotations

import pytest

from medical_rag.documents import iter_source_files, is_supported_source_file


def test_iter_source_files_excludes_sources_markdown(tmp_path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    pdf = corpus / "stroke.pdf"
    notes = corpus / "notes.md"
    sources = corpus / "SOURCES.md"
    pdf.write_bytes(b"%PDF-1.4")
    notes.write_text("Stroke rehabilitation notes.", encoding="utf-8")
    sources.write_text("Source acquisition checklist.", encoding="utf-8")

    discovered = [path.name for path in iter_source_files(corpus)]

    assert discovered == ["notes.md", "stroke.pdf"]


def test_sources_markdown_is_excluded_even_when_requested_directly(tmp_path) -> None:
    sources = tmp_path / "SOURCES.md"
    sources.write_text("Source acquisition checklist.", encoding="utf-8")

    assert not is_supported_source_file(sources)
    with pytest.raises(ValueError, match="Unsupported or excluded source file"):
        iter_source_files(sources)
