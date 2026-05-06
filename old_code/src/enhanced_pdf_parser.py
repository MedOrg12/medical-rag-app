"""
Enhanced PDF parsing module with support for tables, figures, and references.
Extends the base PDF parser with advanced extraction capabilities.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf as fitz

from src.config import settings
from src.logger import logger
from src.pdf_parser import PDFParser


@dataclass
class TableData:
    """Represents an extracted table."""

    page_number: int
    caption: str | None
    content: str  # Markdown or text representation
    cell_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "caption": self.caption,
            "content": self.content,
            "cell_count": self.cell_count,
        }


@dataclass
class FigureData:
    """Represents an extracted figure."""

    page_number: int
    caption: str | None
    bbox: tuple[float, float, float, float]  # (x0, y0, x1, y1)
    image_index: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "caption": self.caption,
            "bbox": list(self.bbox),
            "image_index": self.image_index,
        }


@dataclass
class ReferenceData:
    """Represents extracted references/citations."""

    reference_text: str
    reference_number: int | None
    authors: str | None
    year: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.reference_text,
            "number": self.reference_number,
            "authors": self.authors,
            "year": self.year,
        }


class EnhancedPDFParser(PDFParser):
    """
    Enhanced PDF parser with table, figure, and reference extraction.
    Extends the base PDFParser with additional capabilities.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.extract_tables_enabled = True
        self.extract_figures_enabled = True
        self.extract_references_enabled = True

    def extract_tables_from_page(self, page: fitz.Page, page_num: int) -> list[TableData]:
        """
        Extract tables from a PDF page using PyMuPDF.

        Args:
            page: PyMuPDF page object
            page_num: Page number

        Returns:
            List of TableData objects
        """
        tables = []

        try:
            # PyMuPDF table extraction
            tabs = page.find_tables()

            for tab_idx, tab in enumerate(tabs):
                # Get table as pandas dataframe or list of lists
                try:
                    table_data = tab.extract()

                    if not table_data:
                        continue

                    # Convert to markdown-style table
                    markdown_table = self._format_table_as_markdown(table_data)

                    # Try to find caption near the table
                    caption = self._find_table_caption(page, tab.bbox, page_num)

                    # Count cells
                    cell_count = sum(len(row) for row in table_data if row)

                    table = TableData(
                        page_number=page_num,
                        caption=caption,
                        content=markdown_table,
                        cell_count=cell_count,
                    )

                    tables.append(table)
                    logger.debug(f"Extracted table {tab_idx+1} from page {page_num}")

                except Exception as e:
                    logger.warning(f"Error extracting table {tab_idx} on page {page_num}: {e}")
                    continue

        except Exception as e:
            logger.warning(f"Error finding tables on page {page_num}: {e}")

        return tables

    def _format_table_as_markdown(self, table_data: list[list]) -> str:
        """
        Format table data as markdown.

        Args:
            table_data: List of lists representing table rows

        Returns:
            Markdown-formatted table string
        """
        if not table_data:
            return ""

        # Filter out empty rows
        table_data = [row for row in table_data if any(cell for cell in row if cell)]

        if not table_data:
            return ""

        # Assume first row is header
        header = table_data[0]
        rows = table_data[1:]

        # Create markdown table
        markdown_lines = []

        # Header row
        header_line = "| " + " | ".join(str(cell or "") for cell in header) + " |"
        markdown_lines.append(header_line)

        # Separator
        separator = "| " + " | ".join("---" for _ in header) + " |"
        markdown_lines.append(separator)

        # Data rows
        for row in rows:
            row_line = "| " + " | ".join(str(cell or "") for cell in row) + " |"
            markdown_lines.append(row_line)

        return "\n".join(markdown_lines)

    def _find_table_caption(
        self, page: fitz.Page, table_bbox: tuple[float, float, float, float], page_num: int
    ) -> str | None:
        """
        Try to find caption text near a table.

        Args:
            page: PyMuPDF page
            table_bbox: Table bounding box
            page_num: Page number

        Returns:
            Caption text if found
        """
        try:
            # Search for text above the table
            search_bbox = (
                table_bbox[0],
                max(0, table_bbox[1] - 50),  # 50 points above
                table_bbox[2],
                table_bbox[1],
            )

            text_instances = page.get_text("dict", clip=search_bbox)

            # Extract text blocks
            text_blocks = []
            for block in text_instances.get("blocks", []):
                if "lines" in block:
                    for line in block["lines"]:
                        for span in line.get("spans", []):
                            text_blocks.append(span.get("text", ""))

            caption_text = " ".join(text_blocks).strip()

            # Check if it looks like a caption (starts with "Table", "Tab.", etc.)
            if re.match(r"^(Table|Tab\.)\s+\d+", caption_text, re.IGNORECASE):
                return caption_text[:200]  # Limit caption length

        except Exception as e:
            logger.debug(f"Error finding table caption: {e}")

        return None

    def extract_figures_from_page(self, page: fitz.Page, page_num: int) -> list[FigureData]:
        """
        Extract figure information from a PDF page.

        Args:
            page: PyMuPDF page object
            page_num: Page number

        Returns:
            List of FigureData objects
        """
        figures = []

        try:
            # Get images on the page
            image_list = page.get_images()

            # Limit number of figures per page to prevent slowdowns
            if len(image_list) > settings.max_figures_per_page:
                logger.debug(
                    f"Page {page_num} has {len(image_list)} images, "
                    f"limiting to {settings.max_figures_per_page}"
                )
                image_list = image_list[: settings.max_figures_per_page]

            for img_idx, img in enumerate(image_list):
                try:
                    # Get image bounding box
                    bbox = page.get_image_bbox(img[7])  # img[7] is xref

                    # Try to find figure caption (with timeout protection)
                    caption = self._find_figure_caption(page, bbox, page_num)

                    figure = FigureData(
                        page_number=page_num,
                        caption=caption,
                        bbox=(bbox.x0, bbox.y0, bbox.x1, bbox.y1),
                        image_index=img_idx,
                    )

                    figures.append(figure)
                    logger.debug(f"Extracted figure {img_idx+1} from page {page_num}")

                except Exception as e:
                    logger.debug(f"Skipping figure {img_idx} on page {page_num}: {e}")
                    continue

        except Exception as e:
            logger.warning(f"Error finding figures on page {page_num}: {e}")

        return figures

    def _find_figure_caption(
        self, page: fitz.Page, figure_bbox: fitz.Rect, page_num: int
    ) -> str | None:
        """
        Try to find caption text near a figure.

        Args:
            page: PyMuPDF page
            figure_bbox: Figure bounding box
            page_num: Page number

        Returns:
            Caption text if found
        """
        try:
            # Search below the figure
            search_bbox = fitz.Rect(
                figure_bbox.x0,
                figure_bbox.y1,
                figure_bbox.x1,
                min(page.rect.height, figure_bbox.y1 + settings.figure_caption_search_distance),
            )

            # Use simpler "text" mode instead of "dict" to avoid hangs
            # "dict" mode can be very slow on complex pages
            caption_text = page.get_text("text", clip=search_bbox).strip()

            # Check if it looks like a caption (starts with "Figure", "Fig.", etc.)
            if re.match(r"^(Figure|Fig\.)\s+\d+", caption_text, re.IGNORECASE):
                # Clean up and limit caption length
                caption_text = " ".join(caption_text.split())  # Normalize whitespace
                return caption_text[:200]

        except Exception as e:
            logger.debug(f"Error finding figure caption on page {page_num}: {e}")

        return None

    def extract_references(self, content: str) -> list[ReferenceData]:
        """
        Extract references from document content.

        Args:
            content: Full document text

        Returns:
            List of ReferenceData objects
        """
        references = []

        try:
            # Security: Limit content size to prevent regex DoS (catastrophic backtracking)
            if len(content) > settings.max_content_for_references:
                logger.debug(
                    f"Content too large ({len(content)} chars), "
                    f"truncating to {settings.max_content_for_references} for reference extraction"
                )
                content = content[
                    -settings.max_content_for_references :
                ]  # Take last part (references usually at end)

            # Find references section (more efficient pattern)
            ref_section_start = -1
            for pattern in [r"\nReferences\s*\n", r"\nBibliography\s*\n", r"\nWorks Cited\s*\n"]:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    ref_section_start = match.end()
                    break

            if ref_section_start == -1:
                logger.debug("No references section found")
                return references

            # Extract reference section (limit to reasonable size)
            ref_section_limit = settings.max_content_for_references // 2  # Half of max content
            ref_text = content[ref_section_start : ref_section_start + ref_section_limit]

        except Exception as e:
            logger.warning(f"Error finding references section: {e}")
            return references

        try:
            # Split into individual references
            # Pattern: Numbered references like "1." or "[1]"
            ref_pattern = r"(?:^|\n)\s*(?:\[)?(\d+)(?:\])?\.?\s+([^\n]+(?:\n(?!\s*\d+[\.\]]).*)*)"

            matches = list(re.finditer(ref_pattern, ref_text, re.MULTILINE))

            # Limit number of references to extract (prevent hanging on huge reference lists)
            if len(matches) > settings.max_references_to_extract:
                logger.debug(
                    f"Found {len(matches)} references, "
                    f"limiting to {settings.max_references_to_extract}"
                )
                matches = matches[: settings.max_references_to_extract]

            for match in matches:
                try:
                    ref_num = int(match.group(1))
                    ref_content = match.group(2).strip()

                    # Try to extract authors (simple heuristic)
                    authors = self._extract_authors(ref_content)

                    # Try to extract year
                    year = self._extract_year(ref_content)

                    reference = ReferenceData(
                        reference_text=ref_content[:500],  # Limit length
                        reference_number=ref_num,
                        authors=authors,
                        year=year,
                    )

                    references.append(reference)

                except Exception as e:
                    logger.debug(f"Error extracting individual reference: {e}")
                    continue

            logger.info(f"Extracted {len(references)} references")

        except Exception as e:
            logger.warning(f"Error extracting references: {e}")

        return references

    def _extract_authors(self, ref_text: str) -> str | None:
        """Extract author names from reference text."""
        # Simple heuristic: authors usually come first, before year
        # Pattern: Last, F.M.; Last2, F.M.
        author_pattern = (
            r"^([A-Z][a-zA-Z\-]+(?:,\s*[A-Z]\.?)+(?:;\s*[A-Z][a-zA-Z\-]+(?:,\s*[A-Z]\.?)+)*)"
        )
        match = re.search(author_pattern, ref_text)
        if match:
            return match.group(1)[:100]  # Limit length
        return None

    def _extract_year(self, ref_text: str) -> int | None:
        """Extract publication year from reference text."""
        # Look for 4-digit year in parentheses or standalone
        year_pattern = r"\((\d{4})\)|(\d{4})"
        match = re.search(year_pattern, ref_text)
        if match:
            year_str = match.group(1) or match.group(2)
            year = int(year_str)
            # Sanity check
            if 1900 <= year <= 2030:
                return year
        return None

    def parse_pdf_enhanced(self, pdf_path: Path) -> dict[str, Any]:
        """
        Parse PDF with enhanced extraction of tables, figures, and references.

        Args:
            pdf_path: Path to PDF file

        Returns:
            Dictionary with enhanced parsing results
        """
        logger.info(f"Enhanced parsing: {pdf_path.name}")

        # First, do standard parsing
        doc = self.parse_pdf(pdf_path)

        if not doc:
            return None

        # Now add enhanced extraction
        enhanced_data = {"document": doc, "tables": [], "figures": [], "references": []}

        try:
            pdf_doc = fitz.open(pdf_path)

            # Extract tables and figures from each page
            if self.extract_tables_enabled:
                for page_num, page in enumerate(pdf_doc, start=1):
                    tables = self.extract_tables_from_page(page, page_num)
                    enhanced_data["tables"].extend(tables)

            if self.extract_figures_enabled:
                for page_num, page in enumerate(pdf_doc, start=1):
                    figures = self.extract_figures_from_page(page, page_num)
                    enhanced_data["figures"].extend(figures)

            pdf_doc.close()

            # Extract references from full content
            if self.extract_references_enabled:
                logger.debug("Extracting references...")
                references = self.extract_references(doc.content)
                enhanced_data["references"] = references
                logger.debug(f"Extracted {len(references)} references")

            logger.info(
                f"Enhanced extraction complete: "
                f"{len(enhanced_data['tables'])} tables, "
                f"{len(enhanced_data['figures'])} figures, "
                f"{len(enhanced_data['references'])} references"
            )

        except Exception as e:
            logger.error(f"Error in enhanced parsing: {e}")

        return enhanced_data

    def parse_all_enhanced(self, save_json: bool = True) -> dict[str, list]:
        """
        Parse all PDFs with enhanced extraction.

        Args:
            save_json: Whether to save results

        Returns:
            Dictionary with documents, tables, figures, references
        """
        pdf_files = self.get_pdf_files()

        if not pdf_files:
            logger.warning("No PDF files found")
            return {"documents": [], "tables": [], "figures": [], "references": []}

        all_results = {"documents": [], "tables": [], "figures": [], "references": []}

        for pdf_path in pdf_files:
            try:
                result = self.parse_pdf_enhanced(pdf_path)

                if result:
                    all_results["documents"].append(result["document"])
                    all_results["tables"].extend(result["tables"])
                    all_results["figures"].extend(result["figures"])
                    all_results["references"].extend(result["references"])

            except Exception as e:
                logger.error(f"Error parsing {pdf_path.name}: {e}")

        # Save if requested
        if save_json and all_results["documents"]:
            output_path = settings.data_folder / "enhanced_parsing_results.json"
            settings.data_folder.mkdir(parents=True, exist_ok=True)

            # Convert to serializable format
            save_data = {
                "documents": [doc.to_dict() for doc in all_results["documents"]],
                "tables": [t.to_dict() for t in all_results["tables"]],
                "figures": [f.to_dict() for f in all_results["figures"]],
                "references": [r.to_dict() for r in all_results["references"]],
            }

            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(save_data, f, indent=2, ensure_ascii=False)

            logger.info(f"Saved enhanced results to {output_path}")

        return all_results


if __name__ == "__main__":
    # Test enhanced parser
    parser = EnhancedPDFParser()

    results = parser.parse_all_enhanced()

    print("\nEnhanced Parsing Results:")
    print(f"  Documents: {len(results['documents'])}")
    print(f"  Tables: {len(results['tables'])}")
    print(f"  Figures: {len(results['figures'])}")
    print(f"  References: {len(results['references'])}")

    if results["tables"]:
        print("\nSample Table:")
        print(results["tables"][0].content[:300])
