#!/usr/bin/env python3
"""
Extract metadata from all PDFs in the pdfs/ folder and save to pdf_metadata.json
"""

import json
import sys
from pathlib import Path
from typing import Any

try:
    import fitz  # PyMuPDF
except ImportError:
    print("ERROR: PyMuPDF (fitz) is not installed. Install with: pip install pymupdf")
    sys.exit(1)


def extract_pdf_metadata(pdf_path: Path) -> dict[str, Any]:
    """
    Extract metadata from a PDF file.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        Dictionary containing metadata fields (null if field is missing/empty)
    """
    try:
        doc = fitz.open(pdf_path)
        metadata = doc.metadata
        doc.close()

        # Extract standard metadata fields
        result = {
            "title": metadata.get("title") or None,
            "author": metadata.get("author") or None,
            "subject": metadata.get("subject") or None,
            "keywords": metadata.get("keywords") or None,
            "creator": metadata.get("creator") or None,
            "producer": metadata.get("producer") or None,
            "creationDate": metadata.get("creationDate") or None,
            "modDate": metadata.get("modDate") or None,
            "format": metadata.get("format") or None,
            "encryption": metadata.get("encryption") or None,
        }

        return result

    except Exception as e:
        print(f"  ERROR reading {pdf_path.name}: {e}")
        return {
            "title": None,
            "author": None,
            "subject": None,
            "keywords": None,
            "creator": None,
            "producer": None,
            "creationDate": None,
            "modDate": None,
            "format": None,
            "encryption": None,
            "error": str(e)
        }


def main():
    """Extract metadata from all PDFs and save to pdf_metadata.json"""

    # Determine project root (script is in scripts/, project root is parent)
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    pdfs_dir = project_root / "pdfs"
    output_file = project_root / "pdf_metadata.json"

    print("=" * 70)
    print("PDF Metadata Extraction")
    print("=" * 70)
    print(f"PDFs directory: {pdfs_dir}")
    print(f"Output file: {output_file}")
    print()

    # Check if pdfs directory exists
    if not pdfs_dir.exists():
        print(f"ERROR: PDFs directory not found: {pdfs_dir}")
        sys.exit(1)

    # Find all PDF files
    pdf_files = sorted(pdfs_dir.glob("*.pdf"))

    if not pdf_files:
        print(f"ERROR: No PDF files found in {pdfs_dir}")
        sys.exit(1)

    print(f"Found {len(pdf_files)} PDF files")
    print()

    # Extract metadata from each PDF
    all_metadata = {}

    for i, pdf_path in enumerate(pdf_files, 1):
        print(f"[{i}/{len(pdf_files)}] Processing: {pdf_path.name}")
        metadata = extract_pdf_metadata(pdf_path)
        all_metadata[pdf_path.name] = metadata

        # Show a preview of extracted fields
        title = metadata.get("title")
        author = metadata.get("author")
        if title:
            print(f"  ✓ Title: {title[:60]}{'...' if len(title) > 60 else ''}")
        else:
            print(f"  ⚠ Title: (missing)")
        if author:
            print(f"  ✓ Author: {author[:60]}{'...' if len(author) > 60 else ''}")
        else:
            print(f"  ⚠ Author: (missing)")
        print()

    # Save metadata to JSON file
    print(f"Saving metadata to: {output_file}")
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(all_metadata, f, indent=2, ensure_ascii=False)
        print(f"✓ Successfully saved metadata for {len(all_metadata)} PDFs")
    except Exception as e:
        print(f"ERROR: Failed to save metadata file: {e}")
        sys.exit(1)

    print()
    print("=" * 70)
    print("Metadata Extraction Complete")
    print("=" * 70)

    # Statistics
    pdfs_with_title = sum(1 for m in all_metadata.values() if m.get("title"))
    pdfs_with_author = sum(1 for m in all_metadata.values() if m.get("author"))

    print(f"Total PDFs processed: {len(all_metadata)}")
    print(f"PDFs with title: {pdfs_with_title} ({pdfs_with_title/len(all_metadata)*100:.1f}%)")
    print(f"PDFs with author: {pdfs_with_author} ({pdfs_with_author/len(all_metadata)*100:.1f}%)")
    print()
    print(f"✓ Metadata saved to: {output_file}")
    print()


if __name__ == "__main__":
    main()
