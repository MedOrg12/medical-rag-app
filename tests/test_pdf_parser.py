from __future__ import annotations

import pytest

from medical_rag.documents import (
    _block_text,
    _detect_columns,
    _is_noise_block,
    _looks_like_table_row,
    _order_two_column,
    _table_block_to_lines,
)


def make_block(text: str, x0: float, y0: float, x1: float = 200.0, y1: float = 20.0) -> dict:
    """Minimal fitz-style block dict for testing."""
    return {
        "type": 0,
        "bbox": [x0, y0, x1, y1],
        "lines": [
            {
                "spans": [{"text": text, "bbox": [x0, y0, x1, y1]}],
            }
        ],
    }


def make_multispan_block(spans: list[tuple[str, float]], y0: float = 0.0) -> dict:
    """Block with multiple spans at different x positions."""
    return {
        "type": 0,
        "bbox": [0, y0, 600, y0 + 20],
        "lines": [
            {
                "spans": [
                    {"text": text, "bbox": [x0, y0, x0 + 80, y0 + 20]}
                    for text, x0 in spans
                ],
            }
        ],
    }


class TestColumnDetection:
    def test_single_column_all_left(self):
        blocks = [make_block("text", x0=10, y0=i * 20) for i in range(10)]
        assert _detect_columns(blocks, page_width=600) == 1

    def test_two_column_split(self):
        left = [make_block("left", x0=10, y0=i * 20) for i in range(5)]
        right = [make_block("right", x0=320, y0=i * 20) for i in range(5)]
        assert _detect_columns(left + right, page_width=600) == 2

    def test_empty_blocks_returns_one(self):
        assert _detect_columns([], page_width=600) == 1

    def test_two_column_ordering_left_before_right(self):
        left = [make_block(f"L{i}", x0=10, y0=i * 20) for i in range(3)]
        right = [make_block(f"R{i}", x0=320, y0=i * 20) for i in range(3)]
        ordered = _order_two_column(left + right, page_width=600)
        texts = [_block_text(b) for b in ordered]
        assert texts.index("L0") < texts.index("R0"), "Left column must precede right"
        assert texts.index("L2") < texts.index("R0"), "All left blocks must precede right"

    def test_two_column_within_column_sorted_by_y(self):
        left = [make_block(f"L{i}", x0=10, y0=i * 20) for i in range(3)]
        right = [make_block(f"R{i}", x0=320, y0=i * 20) for i in range(3)]
        ordered = _order_two_column(left + right, page_width=600)
        texts = [_block_text(b) for b in ordered]
        left_texts = [t for t in texts if t.startswith("L")]
        assert left_texts == ["L0", "L1", "L2"]


class TestHeaderFooterRemoval:
    def test_page_number_bare(self):
        assert _is_noise_block("42") is True

    def test_page_number_with_word(self):
        assert _is_noise_block("Page 5") is True

    def test_doi_line(self):
        assert _is_noise_block("doi: 10.1161/STROKEAHA.119.026043") is True

    def test_url_line(self):
        assert _is_noise_block("https://www.nejm.org/article/123") is True

    def test_www_url(self):
        assert _is_noise_block("www.stroke.org") is True

    def test_copyright_line(self):
        assert _is_noise_block("Copyright © 2023 American Heart Association") is True

    def test_downloaded_from(self):
        assert _is_noise_block("Downloaded from jaha.ahajournals.org") is True

    def test_body_text_not_noise(self):
        assert _is_noise_block("Stroke rehabilitation improves functional outcomes.") is False

    def test_clinical_sentence_not_noise(self):
        assert _is_noise_block("Early mobilisation after stroke is recommended.") is False


class TestTableExtraction:
    def test_looks_like_table_row_true(self):
        block = make_multispan_block([
            ("Class I", 0.0),
            ("Level A", 110.0),
            ("Anticoagulation recommended", 220.0),
        ])
        assert _looks_like_table_row(block) is True

    def test_looks_like_table_row_false_long_paragraph(self):
        block = {
            "type": 0,
            "bbox": [0, 0, 500, 20],
            "lines": [
                {
                    "spans": [
                        {
                            "text": "Rehabilitation after stroke should begin as soon as the patient is medically stable and able to participate.",
                            "bbox": [0, 0, 500, 20],
                        }
                    ]
                }
            ],
        }
        assert _looks_like_table_row(block) is False

    def test_looks_like_table_row_false_two_spans(self):
        block = make_multispan_block([("Yes", 0.0), ("No", 100.0)])
        assert _looks_like_table_row(block) is False

    def test_table_block_to_lines_joins_cells(self):
        block = make_multispan_block([
            ("Class I", 0.0),
            ("Level A", 110.0),
            ("Anticoagulation recommended", 220.0),
        ])
        result = _table_block_to_lines(block)
        assert len(result) == 1
        assert "Class I" in result[0]
        assert "Level A" in result[0]
        assert " | " in result[0]

    def test_table_block_to_lines_empty_block(self):
        block = {"lines": [{"spans": [{"text": "  "}]}]}
        assert _table_block_to_lines(block) == []

    def test_block_text_joins_spans(self):
        block = make_multispan_block([("Hello", 0.0), (" world", 50.0)])
        result = _block_text(block)
        assert "Hello" in result
        assert "world" in result
