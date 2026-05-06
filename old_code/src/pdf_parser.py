"""
PDF parsing module for extracting structured content from medical research papers.
Uses pymupdf4llm for better structure preservation and fallback to pymupdf for robustness.
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pymupdf as fitz
import pymupdf4llm
from tqdm import tqdm

from src.config import settings
from src.file_utils import FileOperationError, check_file_readable
from src.logger import logger


@dataclass
class PDFDocument:
    """Represents a parsed PDF document with metadata."""

    file_path: str
    file_name: str
    title: str | None
    num_pages: int
    content: str
    metadata: dict[str, Any]
    sections: list[dict[str, Any]]  # List of {title, content, page_start, page_end}

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)


class PDFParser:
    """Parser for extracting structured content from medical research PDFs."""

    def __init__(self, pdf_folder: Path = None):
        """
        Initialize the PDF parser.

        Args:
            pdf_folder: Path to folder containing PDFs. Defaults to config setting.
        """
        self.pdf_folder = pdf_folder or settings.pdf_folder
        self.pdf_folder = Path(self.pdf_folder)

        if not self.pdf_folder.exists():
            logger.warning(f"PDF folder not found: {self.pdf_folder}. Creating it.")
            self.pdf_folder.mkdir(parents=True, exist_ok=True)

    def get_pdf_files(self) -> list[Path]:
        """
        Get all PDF files in the configured folder.

        Returns:
            List of PDF file paths
        """
        if not self.pdf_folder.exists():
            logger.error(f"PDF folder does not exist: {self.pdf_folder}")
            return []

        pdf_files = list(self.pdf_folder.glob("*.pdf"))
        logger.info(f"Found {len(pdf_files)} PDF files in {self.pdf_folder}")
        return pdf_files

    def extract_metadata(self, pdf_path: Path) -> dict[str, Any]:
        """
        Extract metadata from PDF using PyMuPDF.

        Args:
            pdf_path: Path to PDF file

        Returns:
            Dictionary containing metadata
        """
        try:
            # Validate file is readable
            check_file_readable(pdf_path)

            doc = fitz.open(pdf_path)
            metadata = doc.metadata or {}
            metadata["num_pages"] = len(doc)
            doc.close()
            return metadata
        except FileOperationError as e:
            logger.error(f"Cannot read PDF {pdf_path.name}: {e}")
            return {}
        except Exception as e:
            logger.error(f"Error extracting metadata from {pdf_path.name}: {e}")
            return {}

    def parse_with_pymupdf4llm(self, pdf_path: Path) -> dict[str, Any] | None:
        """
        Parse PDF using pymupdf4llm for better structure preservation.

        Uses ``page_chunks=True`` so we get one markdown blob per page, and
        prepends a ``[Page N]`` marker to each. The chunker later reads those
        markers to record real page numbers on every chunk — without them
        every chunk falls back to page 0.

        Args:
            pdf_path: Path to PDF file

        Returns:
            Parsed content as markdown with [Page N] markers, or None if failed
        """
        try:
            # Validate file is readable
            check_file_readable(pdf_path)

            # page_chunks=True returns a list of {text, metadata, ...} per page
            page_chunks = pymupdf4llm.to_markdown(str(pdf_path), page_chunks=True)

            if not isinstance(page_chunks, list) or not page_chunks:
                logger.warning(
                    f"pymupdf4llm returned no page chunks for {pdf_path.name}"
                )
                return None

            parts = []
            for entry in page_chunks:
                # Each entry is a dict; metadata.page is 0-indexed in pymupdf4llm
                meta = entry.get("metadata", {}) if isinstance(entry, dict) else {}
                page_num = meta.get("page")
                if page_num is None:
                    # Fallback: position-based numbering if metadata is missing
                    page_num = len(parts)
                page_num_1based = int(page_num) + 1
                text = (entry.get("text") if isinstance(entry, dict) else str(entry)) or ""
                if not text.strip():
                    continue
                parts.append(f"[Page {page_num_1based}]\n{text}")

            if not parts:
                return None

            md_text = "\n\n".join(parts)
            return {"content": md_text, "format": "markdown"}
        except Exception as e:
            logger.warning(f"pymupdf4llm failed for {pdf_path.name}: {e}")
            return None

    def parse_with_pymupdf(self, pdf_path: Path) -> dict[str, Any] | None:
        """
        Fallback parser using PyMuPDF for direct text extraction.

        Args:
            pdf_path: Path to PDF file

        Returns:
            Parsed content with page-level structure, or None if failed
        """
        try:
            doc = fitz.open(pdf_path)
            pages = []

            for page_num, page in enumerate(doc, start=1):
                text = page.get_text()
                if text.strip():
                    pages.append({"page_number": page_num, "content": text})

            doc.close()

            # Combine all pages
            full_text = "\n\n".join([f"[Page {p['page_number']}]\n{p['content']}" for p in pages])

            return {"content": full_text, "format": "text", "pages": pages}
        except Exception as e:
            logger.error(f"PyMuPDF fallback failed for {pdf_path.name}: {e}")
            return None

    def extract_sections(self, content: str, format_type: str = "markdown") -> list[dict[str, Any]]:
        """
        Extract sections from parsed content.

        Args:
            content: Parsed content string
            format_type: Format of content (markdown or text)

        Returns:
            List of sections with titles and content
        """
        sections = []

        if format_type == "markdown":
            # Split by markdown headers (# Header, ## Header, etc.)
            lines = content.split("\n")
            current_section = {"title": "Introduction", "content": "", "level": 0}

            for line in lines:
                if line.startswith("#"):
                    # Save previous section if it has content
                    if current_section["content"].strip():
                        sections.append(current_section)

                    # Start new section
                    level = len(line) - len(line.lstrip("#"))
                    title = line.lstrip("#").strip()
                    current_section = {"title": title, "content": "", "level": level}
                else:
                    current_section["content"] += line + "\n"

            # Add last section
            if current_section["content"].strip():
                sections.append(current_section)

        else:
            # Simple section detection for plain text
            # Look for common section headers in medical papers
            section_keywords = [
                "abstract",
                "introduction",
                "methods",
                "methodology",
                "results",
                "discussion",
                "conclusion",
                "references",
                "background",
                "materials and methods",
                "experimental",
            ]

            lines = content.split("\n")
            current_section = {"title": "Body", "content": ""}

            for line in lines:
                line_lower = line.lower().strip()
                is_section_header = any(
                    keyword == line_lower or line_lower.startswith(keyword)
                    for keyword in section_keywords
                )

                if is_section_header and len(line.strip()) < 100:
                    # Save previous section
                    if current_section["content"].strip():
                        sections.append(current_section)

                    # Start new section
                    current_section = {"title": line.strip(), "content": ""}
                else:
                    current_section["content"] += line + "\n"

            # Add last section
            if current_section["content"].strip():
                sections.append(current_section)

        return sections

    def parse_pdf(self, pdf_path: Path) -> PDFDocument | None:
        """
        Parse a single PDF file with structure preservation.

        Args:
            pdf_path: Path to PDF file

        Returns:
            PDFDocument object or None if parsing failed
        """
        logger.info(f"Parsing PDF: {pdf_path.name}")

        # Extract metadata first
        metadata = self.extract_metadata(pdf_path)

        # Try pymupdf4llm first (better structure)
        parsed = self.parse_with_pymupdf4llm(pdf_path)

        # Fallback to pymupdf if needed
        if not parsed:
            logger.info(f"Using fallback parser for {pdf_path.name}")
            parsed = self.parse_with_pymupdf(pdf_path)

        if not parsed:
            logger.error(f"Failed to parse {pdf_path.name}")
            return None

        # Extract sections
        sections = self.extract_sections(parsed["content"], parsed["format"])

        # Try to extract title from metadata or first section
        title = metadata.get("title")
        if not title and sections:
            # Use first section title if available
            title = sections[0]["title"] if sections[0]["title"] != "Introduction" else None

        if not title:
            title = pdf_path.stem  # Use filename as fallback

        # Create PDFDocument
        doc = PDFDocument(
            file_path=str(pdf_path),
            file_name=pdf_path.name,
            title=title,
            num_pages=metadata.get("num_pages", 0),
            content=parsed["content"],
            metadata=metadata,
            sections=sections,
        )

        logger.info(
            f"Successfully parsed {pdf_path.name}: {len(sections)} sections, {doc.num_pages} pages"
        )
        return doc

    def parse_all(self, save_json: bool = True) -> list[PDFDocument]:
        """
        Parse all PDFs in the configured folder.

        Args:
            save_json: Whether to save parsed documents as JSON

        Returns:
            List of successfully parsed PDFDocument objects
        """
        pdf_files = self.get_pdf_files()

        if not pdf_files:
            logger.warning("No PDF files found to parse")
            return []

        documents = []
        for pdf_path in tqdm(pdf_files, desc="Parsing PDFs"):
            try:
                doc = self.parse_pdf(pdf_path)
                if doc:
                    documents.append(doc)
            except Exception as e:
                logger.error(f"Unexpected error parsing {pdf_path.name}: {e}")

        logger.info(f"Successfully parsed {len(documents)}/{len(pdf_files)} PDFs")

        # Save to JSON if requested
        if save_json and documents:
            output_path = settings.data_folder / "parsed_documents.json"
            settings.data_folder.mkdir(parents=True, exist_ok=True)

            with open(output_path, "w", encoding="utf-8") as f:
                json.dump([doc.to_dict() for doc in documents], f, indent=2, ensure_ascii=False)
            logger.info(f"Saved parsed documents to {output_path}")

        return documents


if __name__ == "__main__":
    # Test the parser
    parser = PDFParser()
    docs = parser.parse_all()
    print(f"\nParsed {len(docs)} documents")
    for doc in docs:
        print(f"  - {doc.title} ({doc.num_pages} pages, {len(doc.sections)} sections)")
