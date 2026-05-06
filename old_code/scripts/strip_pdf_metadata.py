#!/usr/bin/env python3
"""
Strip metadata from all PDFs in the pdfs/ folder, keeping only the title field.
Requires pdf_metadata.json to exist (from extract_pdf_metadata.py).
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


def strip_pdf_metadata(pdf_path: Path, title: str | None) -> bool:
    """
    Strip all metadata from a PDF except the title field.

    Args:
        pdf_path: Path to the PDF file
        title: Title to preserve (or None if no title exists)

    Returns:
        True if successful, False otherwise
    """
    temp_path = None
    try:
        doc = fitz.open(pdf_path)

        # Create new metadata with only title field
        new_metadata = {
            "title": title or "",
            "author": "",
            "subject": "",
            "keywords": "",
            "creator": "",
            "producer": "",
        }

        # Set the new metadata
        doc.set_metadata(new_metadata)

        # Save to a temporary file first
        temp_path = pdf_path.with_suffix(".tmp.pdf")
        doc.save(temp_path, garbage=4, deflate=True)
        doc.close()

        # Replace original file with the cleaned version
        temp_path.replace(pdf_path)

        return True

    except Exception as e:
        print(f"  ERROR: Failed to strip metadata: {e}")
        # Clean up temp file if it exists
        if temp_path and temp_path.exists():
            temp_path.unlink()
        return False


def main():
    """Strip metadata from all PDFs (keeping only title)"""

    # Determine project root (script is in scripts/, project root is parent)
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    pdfs_dir = project_root / "pdfs"
    metadata_file = project_root / "pdf_metadata.json"

    print("=" * 70)
    print("PDF Metadata Stripping")
    print("=" * 70)
    print(f"PDFs directory: {pdfs_dir}")
    print(f"Metadata file: {metadata_file}")
    print()

    # Verify metadata file exists
    if not metadata_file.exists():
        print(f"ERROR: Metadata file not found: {metadata_file}")
        print("Run extract_pdf_metadata.py first to create the metadata backup.")
        sys.exit(1)

    # Load metadata
    try:
        with open(metadata_file, "r", encoding="utf-8") as f:
            all_metadata = json.load(f)
        print(f"✓ Loaded metadata for {len(all_metadata)} PDFs")
    except Exception as e:
        print(f"ERROR: Failed to load metadata file: {e}")
        sys.exit(1)

    print()

    # Check if pdfs directory exists
    if not pdfs_dir.exists():
        print(f"ERROR: PDFs directory not found: {pdfs_dir}")
        sys.exit(1)

    # Process each PDF
    processed = 0
    stripped = 0
    skipped = 0
    failed = 0

    for filename, metadata in all_metadata.items():
        pdf_path = pdfs_dir / filename
        processed += 1

        print(f"[{processed}/{len(all_metadata)}] Processing: {filename}")

        # Check if file exists
        if not pdf_path.exists():
            print(f"  ⚠ WARNING: File not found, skipping")
            skipped += 1
            continue

        # Get title from metadata
        title = metadata.get("title")

        # Warn if no title exists
        if not title:
            print(f"  ⚠ WARNING: No title found in metadata")
            print(f"  → Will strip all metadata fields")

        # Strip metadata
        success = strip_pdf_metadata(pdf_path, title)

        if success:
            if title:
                title_preview = title[:50] + "..." if len(title) > 50 else title
                print(f"  ✓ Metadata stripped (kept title: \"{title_preview}\")")
            else:
                print(f"  ✓ All metadata stripped (no title to preserve)")
            stripped += 1
        else:
            print(f"  ✗ Failed to strip metadata")
            failed += 1

        print()

    # Summary
    print("=" * 70)
    print("Metadata Stripping Complete")
    print("=" * 70)
    print(f"Total PDFs in metadata: {len(all_metadata)}")
    print(f"PDFs processed: {processed}")
    print(f"  ✓ Successfully stripped: {stripped}")
    print(f"  ⚠ Skipped (not found): {skipped}")
    print(f"  ✗ Failed: {failed}")
    print()

    if stripped > 0:
        print(f"✓ Successfully stripped metadata from {stripped} PDF(s)")
        print(f"  Original metadata is preserved in: {metadata_file}")
    else:
        print("⚠ No PDFs were processed")

    print()


if __name__ == "__main__":
    main()
