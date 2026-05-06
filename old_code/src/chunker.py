"""
Intelligent text chunking module with section-aware splitting.
Preserves document structure while creating semantically coherent chunks.
"""

import re
from dataclasses import asdict, dataclass
from typing import Any

import tiktoken

from src.config import settings
from src.logger import logger
from src.pdf_parser import PDFDocument


@dataclass
class TextChunk:
    """Represents a chunk of text with metadata."""

    chunk_id: str
    content: str
    source_file: str
    source_title: str
    section_title: str | None
    page_numbers: list[int]
    chunk_index: int
    total_chunks: int
    token_count: int
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)


class IntelligentChunker:
    """
    Intelligent text chunker that preserves document structure.
    Uses section-aware splitting with configurable chunk sizes.
    """

    def __init__(
        self,
        chunk_size: int = None,
        chunk_overlap: int = None,
        min_chunk_size: int = None,
        encoding_name: str = "cl100k_base",
    ):
        """
        Initialize the chunker.

        Args:
            chunk_size: Target chunk size in tokens
            chunk_overlap: Overlap between chunks in tokens
            min_chunk_size: Minimum chunk size in tokens
            encoding_name: Tokenizer encoding to use
        """
        self.chunk_size = chunk_size or settings.chunk_size
        self.chunk_overlap = chunk_overlap or settings.chunk_overlap
        self.min_chunk_size = min_chunk_size or settings.min_chunk_size

        # Initialize tokenizer
        try:
            self.tokenizer = tiktoken.get_encoding(encoding_name)
        except Exception as e:
            logger.warning(
                f"Failed to load tiktoken encoding {encoding_name}: {e}. Using fallback."
            )
            self.tokenizer = None

        logger.info(
            f"Initialized chunker: chunk_size={self.chunk_size}, "
            f"overlap={self.chunk_overlap}, min_size={self.min_chunk_size}"
        )

    def count_tokens(self, text: str) -> int:
        """
        Count tokens in text.

        Args:
            text: Input text

        Returns:
            Number of tokens
        """
        if self.tokenizer:
            return len(self.tokenizer.encode(text))
        else:
            # Fallback: estimate 4 characters per token
            return len(text) // 4

    def extract_page_numbers(self, text: str) -> list[int]:
        """
        Extract page numbers from text that contains [Page N] markers.

        Args:
            text: Input text with page markers

        Returns:
            List of unique page numbers
        """
        pattern = r"\[Page (\d+)\]"
        matches = re.findall(pattern, text)
        return sorted(set(int(m) for m in matches))

    def split_text_by_tokens(self, text: str, metadata: dict[str, Any]) -> list[str]:
        """
        Split text into chunks based on token count.

        Args:
            text: Text to split
            metadata: Metadata for context

        Returns:
            List of text chunks
        """
        # Split into sentences first to avoid breaking mid-sentence
        # Simple sentence splitting (can be improved with NLP libraries)
        sentences = re.split(r"(?<=[.!?])\s+", text)

        chunks = []
        current_chunk = []
        current_token_count = 0

        for sentence in sentences:
            sentence_tokens = self.count_tokens(sentence)

            # If single sentence exceeds chunk size, split it
            if sentence_tokens > self.chunk_size:
                # Save current chunk if it exists
                if current_chunk:
                    chunks.append(" ".join(current_chunk))
                    current_chunk = []
                    current_token_count = 0

                # Split long sentence by words
                words = sentence.split()
                temp_chunk = []
                temp_tokens = 0

                for word in words:
                    word_tokens = self.count_tokens(word + " ")
                    if temp_tokens + word_tokens > self.chunk_size and temp_chunk:
                        chunks.append(" ".join(temp_chunk))
                        # Keep overlap
                        overlap_words = temp_chunk[-max(1, len(temp_chunk) // 10) :]
                        temp_chunk = overlap_words + [word]
                        temp_tokens = self.count_tokens(" ".join(temp_chunk))
                    else:
                        temp_chunk.append(word)
                        temp_tokens += word_tokens

                if temp_chunk:
                    chunks.append(" ".join(temp_chunk))

            # If adding sentence exceeds chunk size, start new chunk
            elif current_token_count + sentence_tokens > self.chunk_size:
                if current_chunk:
                    chunks.append(" ".join(current_chunk))

                # Start new chunk with overlap from previous chunk
                if current_chunk and self.chunk_overlap > 0:
                    # Calculate how many sentences to keep for overlap
                    overlap_sentences = []
                    overlap_tokens = 0

                    for sent in reversed(current_chunk):
                        sent_tokens = self.count_tokens(sent)
                        if overlap_tokens + sent_tokens <= self.chunk_overlap:
                            overlap_sentences.insert(0, sent)
                            overlap_tokens += sent_tokens
                        else:
                            break

                    current_chunk = overlap_sentences + [sentence]
                    current_token_count = self.count_tokens(" ".join(current_chunk))
                else:
                    current_chunk = [sentence]
                    current_token_count = sentence_tokens
            else:
                current_chunk.append(sentence)
                current_token_count += sentence_tokens

        # Add final chunk
        if current_chunk:
            chunks.append(" ".join(current_chunk))

        # Filter out chunks that are too small
        chunks = [c for c in chunks if self.count_tokens(c) >= self.min_chunk_size]

        return chunks

    def chunk_section(
        self, section: dict[str, Any], doc: PDFDocument, section_index: int
    ) -> list[TextChunk]:
        """
        Chunk a single section of a document.

        Args:
            section: Section dictionary with title and content
            doc: Parent PDFDocument
            section_index: Index of this section in the document

        Returns:
            List of TextChunk objects
        """
        section_title = section.get("title", "Untitled Section")
        section_content = section.get("content", "")

        # Skip empty sections
        if not section_content.strip():
            return []

        # Split section into chunks
        text_chunks = self.split_text_by_tokens(
            section_content, {"section": section_title, "document": doc.title}
        )

        # Page-tracking state. The parser injects [Page N] markers per page,
        # but only the chunk(s) that happen to contain a marker would otherwise
        # know their own page. Chunks that sit mid-page have no marker — they
        # need to inherit the last-seen page from the chunks before them.
        # Seed with the first marker that appears anywhere in the section so
        # the very first chunk(s) start on the right page even when that
        # marker got pulled into a later chunk.
        section_first_match = re.search(r"\[Page (\d+)\]", section_content)
        running_page = int(section_first_match.group(1)) if section_first_match else 0

        # Create TextChunk objects
        chunks = []
        for i, chunk_text in enumerate(text_chunks):
            # Find any markers inside this chunk
            chunk_pages = self.extract_page_numbers(chunk_text)

            if chunk_pages:
                # This chunk contains its own marker(s) — use them and update
                # running_page to the last marker so subsequent marker-less
                # chunks inherit the right page.
                page_numbers = chunk_pages
                running_page = chunk_pages[-1]
            else:
                # No marker — inherit the page we were last on.
                page_numbers = [running_page] if running_page else [0]

            # Remove page markers from content for cleaner text
            clean_content = re.sub(r"\[Page \d+\]\n?", "", chunk_text)

            chunk = TextChunk(
                chunk_id=f"{doc.file_name}::section_{section_index}::chunk_{i}",
                content=clean_content.strip(),
                source_file=doc.file_name,
                source_title=doc.title,
                section_title=section_title,
                page_numbers=page_numbers,
                chunk_index=i,
                total_chunks=len(text_chunks),
                token_count=self.count_tokens(clean_content),
                metadata={
                    "file_path": doc.file_path,
                    "section_index": section_index,
                    "num_pages": doc.num_pages,
                    **doc.metadata,
                },
            )
            chunks.append(chunk)

        return chunks

    def chunk_document(self, doc: PDFDocument) -> list[TextChunk]:
        """
        Chunk an entire document while preserving section structure.

        Args:
            doc: PDFDocument to chunk

        Returns:
            List of TextChunk objects
        """
        all_chunks = []

        if doc.sections:
            # Process each section separately
            for section_idx, section in enumerate(doc.sections):
                section_chunks = self.chunk_section(section, doc, section_idx)
                all_chunks.extend(section_chunks)

            logger.info(
                f"Chunked {doc.file_name}: {len(doc.sections)} sections → "
                f"{len(all_chunks)} chunks"
            )
        else:
            # No sections detected, chunk entire content
            logger.warning(f"No sections found in {doc.file_name}, chunking entire content")

            text_chunks = self.split_text_by_tokens(doc.content, {"document": doc.title})

            # Same page-inheritance logic as chunk_section — see comments there.
            doc_first_match = re.search(r"\[Page (\d+)\]", doc.content)
            running_page = int(doc_first_match.group(1)) if doc_first_match else 0

            for i, chunk_text in enumerate(text_chunks):
                chunk_pages = self.extract_page_numbers(chunk_text)
                if chunk_pages:
                    page_numbers = chunk_pages
                    running_page = chunk_pages[-1]
                else:
                    page_numbers = [running_page] if running_page else [0]
                clean_content = re.sub(r"\[Page \d+\]\n?", "", chunk_text)

                chunk = TextChunk(
                    chunk_id=f"{doc.file_name}::chunk_{i}",
                    content=clean_content.strip(),
                    source_file=doc.file_name,
                    source_title=doc.title,
                    section_title=None,
                    page_numbers=page_numbers,
                    chunk_index=i,
                    total_chunks=len(text_chunks),
                    token_count=self.count_tokens(clean_content),
                    metadata={
                        "file_path": doc.file_path,
                        "num_pages": doc.num_pages,
                        **doc.metadata,
                    },
                )
                all_chunks.append(chunk)

        return all_chunks

    def chunk_documents(self, documents: list[PDFDocument]) -> list[TextChunk]:
        """
        Chunk multiple documents.

        Args:
            documents: List of PDFDocument objects

        Returns:
            List of all TextChunk objects
        """
        all_chunks = []

        for doc in documents:
            try:
                chunks = self.chunk_document(doc)
                all_chunks.extend(chunks)
            except Exception as e:
                logger.error(f"Error chunking document {doc.file_name}: {e}")

        logger.info(f"Created {len(all_chunks)} total chunks from {len(documents)} documents")

        # Log statistics
        if all_chunks:
            avg_tokens = sum(c.token_count for c in all_chunks) / len(all_chunks)
            logger.info(f"Average chunk size: {avg_tokens:.1f} tokens")

        return all_chunks


if __name__ == "__main__":
    # Test the chunker
    from src.pdf_parser import PDFParser

    parser = PDFParser()
    docs = parser.parse_all(save_json=False)

    if docs:
        chunker = IntelligentChunker()
        chunks = chunker.chunk_documents(docs)

        print(f"\nCreated {len(chunks)} chunks")
        if chunks:
            print(f"Sample chunk:\n{chunks[0].content[:200]}...")
