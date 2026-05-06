"""
Metadata extraction module for enhanced chunk information.
Extracts document type, keywords, citations, and other metadata.
"""

import re
from datetime import datetime
from typing import Any

from src.config import settings
from src.logger import logger


class MetadataExtractor:
    """Extract enhanced metadata from text chunks and documents."""

    # Document type patterns
    DOCUMENT_TYPES = {
        "clinical_trial": [
            r"randomized controlled trial",
            r"\bRCT\b",
            r"phase \d+ trial",
            r"clinical trial registration",
            r"trial protocol",
        ],
        "systematic_review": [
            r"systematic review",
            r"meta-analysis",
            r"search strategy",
            r"prisma",
            r"cochrane",
        ],
        "guideline": [
            r"guideline",
            r"recommendation",
            r"consensus statement",
            r"practice parameter",
            r"best practice",
        ],
        "observational_study": [
            r"cohort study",
            r"case-control",
            r"cross-sectional",
            r"prospective study",
            r"retrospective",
        ],
        "case_report": [r"case report", r"case series", r"case presentation"],
        "review": [r"literature review", r"narrative review", r"scoping review"],
    }

    # Medical keywords to extract
    MEDICAL_TERMS = {
        "treatment": [
            "treatment",
            "therapy",
            "intervention",
            "medication",
            "drug",
            "surgery",
            "procedure",
        ],
        "diagnosis": ["diagnosis", "diagnostic", "screening", "test", "biomarker", "imaging"],
        "outcome": ["outcome", "mortality", "morbidity", "survival", "prognosis", "complication"],
        "population": ["patient", "participants", "cohort", "population", "sample", "subjects"],
    }

    def classify_document_type(self, content: str, title: str = "") -> str:
        """
        Classify document type based on content.

        Args:
            content: Document or chunk content
            title: Document title

        Returns:
            Document type classification
        """
        content_lower = (content + " " + title).lower()

        # Check each document type
        type_scores = {}
        for doc_type, patterns in self.DOCUMENT_TYPES.items():
            score = sum(
                1 for pattern in patterns if re.search(pattern, content_lower, re.IGNORECASE)
            )
            if score > 0:
                type_scores[doc_type] = score

        if type_scores:
            # Return type with highest score
            return max(type_scores, key=type_scores.get)

        return "research_article"  # Default

    def extract_year(self, content: str, metadata: dict[str, Any]) -> int | None:
        """
        Extract publication year from content or metadata.

        Args:
            content: Text content
            metadata: Document metadata

        Returns:
            Publication year or None
        """
        # Check metadata first
        if "year" in metadata:
            return int(metadata["year"])

        if "creationDate" in metadata:
            try:
                date_str = metadata["creationDate"]
                # Parse various date formats
                year = int(date_str[:4])
                if 1900 <= year <= datetime.now().year:
                    return year
            except:
                pass

        # Look for year in content (e.g., "2024", "published 2023")
        year_pattern = r"\b(19|20)\d{2}\b"
        years = re.findall(year_pattern, content[: settings.metadata_check_chars])

        if years:
            # Return most recent plausible year
            valid_years = [int(y) for y in years if 1990 <= int(y) <= datetime.now().year]
            if valid_years:
                return max(valid_years)

        return None

    def extract_keywords(self, content: str, max_keywords: int = 10) -> list[str]:
        """
        Extract medical keywords from content.

        Args:
            content: Text content
            max_keywords: Maximum number of keywords to extract

        Returns:
            List of extracted keywords
        """
        content_lower = content.lower()
        found_keywords = set()

        # Extract predefined medical terms
        for category, terms in self.MEDICAL_TERMS.items():
            for term in terms:
                if term in content_lower:
                    found_keywords.add(term)

        # Extract capitalized terms (likely important)
        # Pattern: 2+ capitalized words in a row
        cap_pattern = r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b"
        capitalized = re.findall(cap_pattern, content)
        for term in capitalized[:5]:  # Limit capitalized terms
            if len(term.split()) <= 3:  # Max 3 words
                found_keywords.add(term.lower())

        # Return top keywords (sorted by frequency in content)
        keyword_freq = {kw: content_lower.count(kw) for kw in found_keywords}

        sorted_keywords = sorted(keyword_freq.items(), key=lambda x: x[1], reverse=True)

        return [kw for kw, _ in sorted_keywords[:max_keywords]]

    def count_citations(self, content: str) -> int:
        """
        Count number of citations in content.

        Args:
            content: Text content

        Returns:
            Number of citations found
        """
        # Common citation patterns
        patterns = [
            r"\[\d+\]",  # [1], [23]
            r"\(\d{4}\)",  # (2024)
            r"et al\.",  # et al.
            r"\b[A-Z][a-z]+\s+et\s+al\.",  # Smith et al.
        ]

        total_citations = 0
        for pattern in patterns:
            matches = re.findall(pattern, content)
            total_citations += len(matches)

        return total_citations

    def extract_statistical_significance(self, content: str) -> list[str]:
        """
        Extract statistical significance values (p-values, confidence intervals).

        Args:
            content: Text content

        Returns:
            List of statistical findings
        """
        findings = []

        # P-value patterns
        p_pattern = r"p\s*[<>=]\s*0?\.\d+"
        p_values = re.findall(p_pattern, content, re.IGNORECASE)
        findings.extend(p_values[:5])  # Limit to 5

        # Confidence interval patterns
        ci_pattern = r"\d+%\s*(?:CI|confidence interval)"
        cis = re.findall(ci_pattern, content, re.IGNORECASE)
        findings.extend(cis[:3])

        return findings

    def extract_sample_size(self, content: str) -> int | None:
        """
        Extract sample size from content.

        Args:
            content: Text content

        Returns:
            Sample size (n) if found
        """
        # Pattern: n = 123, N = 456, sample size of 789
        patterns = [
            r"[nN]\s*=\s*(\d+)",
            r"sample size of (\d+)",
            r"(\d+)\s+patients",
            r"(\d+)\s+participants",
            r"cohort of (\d+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, content)
            if match:
                size = int(match.group(1))
                # Sanity check (reasonable sample size)
                if 1 <= size <= 1000000:
                    return size

        return None

    def enhance_chunk_metadata(
        self,
        content: str,
        existing_metadata: dict[str, Any],
        document_title: str = "",
        section_title: str = "",
    ) -> dict[str, Any]:
        """
        Add enhanced metadata to chunk.

        Args:
            content: Chunk content
            existing_metadata: Current metadata
            document_title: Document title
            section_title: Section title

        Returns:
            Enhanced metadata dictionary
        """
        enhanced = existing_metadata.copy()

        # Document type
        enhanced["document_type"] = self.classify_document_type(
            content + " " + section_title, document_title
        )

        # Publication year
        year = self.extract_year(content, existing_metadata)
        if year:
            enhanced["year"] = year

        # Keywords
        enhanced["keywords"] = self.extract_keywords(content)

        # Citations count
        enhanced["citations_count"] = self.count_citations(content)

        # Statistical findings
        stats = self.extract_statistical_significance(content)
        if stats:
            enhanced["statistical_findings"] = stats

        # Sample size
        sample_size = self.extract_sample_size(content)
        if sample_size:
            enhanced["sample_size"] = sample_size

        # Section type (from section title)
        section_lower = section_title.lower() if section_title else ""
        section_types = {
            "abstract": ["abstract"],
            "introduction": ["introduction", "background"],
            "methods": ["method", "material", "patient"],
            "results": ["result", "finding"],
            "discussion": ["discussion", "conclusion"],
            "references": ["reference", "bibliography"],
        }

        for sec_type, keywords in section_types.items():
            if any(kw in section_lower for kw in keywords):
                enhanced["section_type"] = sec_type
                break
        else:
            enhanced["section_type"] = "other"

        logger.debug(
            f"Enhanced metadata: type={enhanced['document_type']}, "
            f"year={enhanced.get('year', 'N/A')}, "
            f"keywords={len(enhanced['keywords'])}"
        )

        return enhanced


if __name__ == "__main__":
    # Test metadata extraction
    extractor = MetadataExtractor()

    test_content = """
    This randomized controlled trial enrolled 245 patients with hypertension.
    The primary outcome was reduction in systolic blood pressure at 12 weeks.
    Results showed a significant reduction (p < 0.001, 95% CI: 8-12 mmHg).
    Published in 2024.
    """

    metadata = extractor.enhance_chunk_metadata(
        content=test_content,
        existing_metadata={},
        document_title="Hypertension Treatment Trial",
        section_title="Results",
    )

    print("Enhanced Metadata:")
    for key, value in metadata.items():
        print(f"  {key}: {value}")
