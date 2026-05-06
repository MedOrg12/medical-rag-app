"""
Question type classification and adaptive retrieval module.
Classifies questions by intent and adjusts retrieval strategy accordingly.
"""

import re
from enum import Enum

import ollama

from src.config import settings
from src.logger import logger


class QuestionType(Enum):
    """Types of questions users can ask."""

    FACTUAL = "factual"  # What is X? Define Y. Describe Z.
    COMPARISON = "comparison"  # Compare X and Y. What's the difference?
    CAUSAL = "causal"  # Why does X? What causes Y? How does Z work?
    PROCEDURAL = "procedural"  # How to X? What steps? What is the protocol?
    SUMMARY = "summary"  # Summarize X. Overview of Y. Review Z.
    NUMERICAL = "numerical"  # How many? What percentage? Statistics?
    EVIDENCE = "evidence"  # What evidence? What studies show? Is there proof?
    OPINION = "opinion"  # What do experts think? Consensus? Recommendations?


class QuestionClassifier:
    """
    Classifies questions by type and adjusts retrieval parameters.
    """

    # Keywords for each question type
    TYPE_PATTERNS = {
        QuestionType.FACTUAL: {
            "keywords": ["what is", "define", "describe", "explain"],
            "patterns": [r"^what\s+is\b", r"^define\b", r"^describe\b", r"^explain\b"],
        },
        QuestionType.COMPARISON: {
            "keywords": ["compare", "difference", "versus", "vs", "contrast", "distinguish"],
            "patterns": [r"compare\b", r"difference\s+between", r"\bvs\.?\b", r"versus\b"],
        },
        QuestionType.CAUSAL: {
            "keywords": ["why", "cause", "reason", "lead to", "result in", "mechanism"],
            "patterns": [r"^why\b", r"what\s+causes?", r"why\s+does", r"how\s+does.*work"],
        },
        QuestionType.PROCEDURAL: {
            "keywords": ["how to", "steps", "procedure", "protocol", "process", "method"],
            "patterns": [r"how\s+to\b", r"what\s+steps", r"protocol\s+for", r"procedure\b"],
        },
        QuestionType.SUMMARY: {
            "keywords": [
                "summarize",
                "overview",
                "summary",
                "review",
                "main points",
                "key findings",
            ],
            "patterns": [r"summarize\b", r"overview\s+of", r"^review\b", r"main\s+findings"],
        },
        QuestionType.NUMERICAL: {
            "keywords": ["how many", "how much", "percentage", "rate", "number", "statistics"],
            "patterns": [r"how\s+many", r"how\s+much", r"what\s+percentage", r"\d+%"],
        },
        QuestionType.EVIDENCE: {
            "keywords": ["evidence", "studies show", "research shows", "proven", "demonstrated"],
            "patterns": [r"what\s+evidence", r"studies\s+show", r"is\s+there\s+proof"],
        },
        QuestionType.OPINION: {
            "keywords": ["recommendation", "guideline", "expert", "consensus", "best practice"],
            "patterns": [r"recommend", r"guideline", r"what\s+do\s+experts", r"consensus\b"],
        },
    }

    def __init__(self, use_llm: bool = False, model: str = None):
        """
        Initialize question classifier.

        Args:
            use_llm: Whether to use LLM for classification (more accurate, slower)
            model: Ollama model to use for LLM classification
        """
        self.use_llm = use_llm
        self.model = model or settings.ollama_model

    def classify_rule_based(self, question: str) -> QuestionType:
        """
        Classify question using rule-based patterns.

        Args:
            question: User question

        Returns:
            QuestionType
        """
        question_lower = question.lower().strip()

        # Score each type
        type_scores = {}

        for qtype, patterns in self.TYPE_PATTERNS.items():
            score = 0

            # Check keywords
            for keyword in patterns["keywords"]:
                if keyword in question_lower:
                    score += 1

            # Check regex patterns (weighted higher)
            for pattern in patterns["patterns"]:
                if re.search(pattern, question_lower):
                    score += 2

            if score > 0:
                type_scores[qtype] = score

        # Return type with highest score
        if type_scores:
            best_type = max(type_scores, key=type_scores.get)
            logger.info(f"Classified as {best_type.value} (score: {type_scores[best_type]})")
            return best_type

        # Default to factual
        logger.info("No clear classification, defaulting to FACTUAL")
        return QuestionType.FACTUAL

    def classify_llm_based(self, question: str) -> QuestionType:
        """
        Classify question using LLM (more accurate, slower).

        Args:
            question: User question

        Returns:
            QuestionType
        """
        prompt = f"""Classify this question into ONE of these types:

FACTUAL: Asking for definitions, descriptions, or basic facts
COMPARISON: Comparing two or more things
CAUSAL: Asking about causes, reasons, or mechanisms
PROCEDURAL: Asking about how to do something or steps in a process
SUMMARY: Asking for an overview or summary
NUMERICAL: Asking for numbers, statistics, or quantities
EVIDENCE: Asking about research evidence or proof
OPINION: Asking for recommendations or expert consensus

Question: {question}

Respond with ONLY the type name (e.g., "FACTUAL", "COMPARISON", etc.)"""

        try:
            response = ollama.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.0},
            )

            classification = response["message"]["content"].strip().upper()

            # Map to QuestionType
            for qtype in QuestionType:
                if qtype.value.upper() == classification:
                    logger.info(f"LLM classified as {qtype.value}")
                    return qtype

        except Exception as e:
            logger.warning(f"Error in LLM classification: {e}, falling back to rule-based")

        # Fallback to rule-based
        return self.classify_rule_based(question)

    def classify(self, question: str) -> QuestionType:
        """
        Classify question using configured method.

        Args:
            question: User question

        Returns:
            QuestionType
        """
        if self.use_llm:
            return self.classify_llm_based(question)
        else:
            return self.classify_rule_based(question)

    def get_retrieval_params(self, question_type: QuestionType) -> dict[str, any]:
        """
        Get optimal retrieval parameters for question type.

        Args:
            question_type: Type of question

        Returns:
            Dictionary of retrieval parameters
        """
        # Default parameters
        params = {
            "top_k": settings.top_k_results,
            "use_hybrid": True,
            "use_reranking": True,
            "use_expansion": False,
            "temperature": settings.temperature,
        }

        # Adjust based on question type
        if question_type == QuestionType.FACTUAL:
            # Precise, focused retrieval
            params["top_k"] = 3
            params["use_hybrid"] = True
            params["use_reranking"] = True
            params["temperature"] = 0.1

        elif question_type == QuestionType.COMPARISON:
            # Need multiple perspectives
            params["top_k"] = 8
            params["use_hybrid"] = True
            params["use_reranking"] = True
            params["temperature"] = 0.2

        elif question_type == QuestionType.CAUSAL:
            # Deep understanding needed
            params["top_k"] = 6
            params["use_hybrid"] = True
            params["use_reranking"] = True
            params["use_expansion"] = True
            params["temperature"] = 0.2

        elif question_type == QuestionType.PROCEDURAL:
            # Step-by-step information
            params["top_k"] = 5
            params["use_hybrid"] = True
            params["use_reranking"] = False  # Preserve order
            params["temperature"] = 0.1

        elif question_type == QuestionType.SUMMARY:
            # Broad coverage needed
            params["top_k"] = 10
            params["use_hybrid"] = False  # Semantic breadth
            params["use_reranking"] = True
            params["use_expansion"] = True
            params["temperature"] = 0.3

        elif question_type == QuestionType.NUMERICAL:
            # Precision critical
            params["top_k"] = 3
            params["use_hybrid"] = True
            params["use_reranking"] = True
            params["temperature"] = 0.0  # Very factual

        elif question_type == QuestionType.EVIDENCE:
            # Multiple sources important
            params["top_k"] = 8
            params["use_hybrid"] = True
            params["use_reranking"] = True
            params["use_expansion"] = True
            params["temperature"] = 0.1

        elif question_type == QuestionType.OPINION:
            # Guidelines and recommendations
            params["top_k"] = 6
            params["use_hybrid"] = True
            params["use_reranking"] = True
            params["temperature"] = 0.2

        logger.info(
            f"Retrieval params for {question_type.value}: "
            f"top_k={params['top_k']}, temp={params['temperature']}"
        )

        return params

    def get_generation_prompt(self, question_type: QuestionType) -> str:
        """
        Get type-specific generation instructions.

        Args:
            question_type: Type of question

        Returns:
            Additional prompt instructions
        """
        prompts = {
            QuestionType.FACTUAL: "Provide a clear, concise definition or description.",
            QuestionType.COMPARISON: "Compare the items systematically, highlighting key similarities and differences.",
            QuestionType.CAUSAL: "Explain the mechanism, causes, or reasons clearly, citing supporting evidence.",
            QuestionType.PROCEDURAL: "Describe the steps or procedure in order, being specific and actionable.",
            QuestionType.SUMMARY: "Provide a comprehensive overview covering the main points and key findings.",
            QuestionType.NUMERICAL: "Provide specific numbers, statistics, or quantitative data with sources.",
            QuestionType.EVIDENCE: "Cite specific studies and evidence, including sample sizes and findings.",
            QuestionType.OPINION: "Summarize expert recommendations and consensus, noting any disagreements.",
        }

        return prompts.get(question_type, "")


class AdaptiveRetriever:
    """
    Retriever that adapts strategy based on question type.
    """

    def __init__(self, rag_pipeline, classifier: QuestionClassifier = None):
        """
        Initialize adaptive retriever.

        Args:
            rag_pipeline: RAG pipeline instance (ConversationalRAG or MedicalRAG)
            classifier: QuestionClassifier instance
        """
        self.rag = rag_pipeline
        self.classifier = classifier or QuestionClassifier(use_llm=False)

    def query_adaptive(self, question: str, force_type: QuestionType | None = None):
        """
        Query with adaptive retrieval based on question type.

        Args:
            question: User question
            force_type: Force a specific question type (for testing)

        Returns:
            RAGResponse with type-specific handling
        """
        # Classify question
        if force_type:
            qtype = force_type
            logger.info(f"Using forced question type: {qtype.value}")
        else:
            qtype = self.classifier.classify(question)

        # Get optimal retrieval parameters
        params = self.classifier.get_retrieval_params(qtype)

        logger.info(f"Adaptive retrieval for {qtype.value} question")

        # Execute query with adaptive parameters
        # Note: This assumes the RAG pipeline supports these parameters
        try:
            response = self.rag.query(
                question=question, top_k=params["top_k"], return_context=False
            )

            # Add question type to metadata
            response.question_type = qtype.value

            return response

        except Exception as e:
            logger.error(f"Error in adaptive retrieval: {e}")
            # Fallback to standard query
            return self.rag.query(question)


if __name__ == "__main__":
    # Test question classifier
    classifier = QuestionClassifier(use_llm=False)

    test_questions = [
        "What is stroke?",
        "Compare ischemic and hemorrhagic stroke",
        "Why does hypertension cause stroke?",
        "How to prevent stroke?",
        "Summarize the main risk factors for stroke",
        "How many patients were in the study?",
        "What evidence supports this treatment?",
        "What do guidelines recommend?",
    ]

    print("\nQuestion Classification Tests:\n")

    for question in test_questions:
        qtype = classifier.classify(question)
        params = classifier.get_retrieval_params(qtype)

        print(f"Q: {question}")
        print(f"   Type: {qtype.value}")
        print(f"   Params: top_k={params['top_k']}, temp={params['temperature']}")
        print()
