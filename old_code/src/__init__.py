"""
Medical Research RAG Pipeline

A complete local RAG system for medical research papers using:
- PDF parsing with pymupdf4llm (+ enhanced table/figure extraction)
- Intelligent section-aware chunking
- ChromaDB vector storage
- Ollama embeddings (nomic-embed-text)
- Local LLM generation
- Enhanced features: hybrid search, re-ranking, conversation memory, query expansion
- Advanced: question classification, adaptive retrieval
"""

__version__ = "2.1.0"

from src.chunker import IntelligentChunker, TextChunk
from src.config import settings
from src.conversation import ConversationMemory
from src.conversational_rag import ConversationalRAG
from src.embeddings import OllamaEmbeddings
from src.enhanced_pdf_parser import EnhancedPDFParser, FigureData, ReferenceData, TableData
from src.metadata_extractor import MetadataExtractor
from src.pdf_parser import PDFDocument, PDFParser
from src.query_expansion import MultiQueryRetriever, QueryExpander
from src.question_classifier import AdaptiveRetriever, QuestionClassifier, QuestionType
from src.rag_pipeline import MedicalRAG, RAGResponse
from src.reranker import LLMReRanker, SimpleReRanker
from src.vector_db import VectorDatabase

__all__ = [
    "settings",
    "PDFParser",
    "PDFDocument",
    "IntelligentChunker",
    "TextChunk",
    "OllamaEmbeddings",
    "VectorDatabase",
    "MedicalRAG",
    "RAGResponse",
    "ConversationalRAG",
    "LLMReRanker",
    "SimpleReRanker",
    "ConversationMemory",
    "QueryExpander",
    "MultiQueryRetriever",
    "MetadataExtractor",
    "EnhancedPDFParser",
    "TableData",
    "FigureData",
    "ReferenceData",
    "QuestionClassifier",
    "QuestionType",
    "AdaptiveRetriever",
]
