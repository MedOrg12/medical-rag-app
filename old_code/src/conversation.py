"""
Conversation memory management for multi-turn dialogue.
Tracks conversation history and provides context-aware responses.
"""

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.logger import logger


@dataclass
class ConversationTurn:
    """Represents a single turn in the conversation."""

    question: str
    answer: str
    sources: list[dict[str, Any]]
    timestamp: str
    turn_number: int

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


class ConversationMemory:
    """
    Manages conversation history for multi-turn dialogues.
    Provides context from previous exchanges.
    """

    def __init__(self, max_history: int = 10, save_path: Path | None = None):
        """
        Initialize conversation memory.

        Args:
            max_history: Maximum number of turns to remember
            save_path: Optional path to save conversation history
        """
        self.max_history = max_history
        self.save_path = save_path
        self.history: list[ConversationTurn] = []
        self.turn_counter = 0

        logger.info(f"Initialized conversation memory (max_history={max_history})")

    def add_turn(self, question: str, answer: str, sources: list[dict[str, Any]]) -> None:
        """
        Add a conversation turn to history.

        Args:
            question: User question
            answer: System answer
            sources: List of source documents used
        """
        self.turn_counter += 1

        turn = ConversationTurn(
            question=question,
            answer=answer,
            sources=sources,
            timestamp=datetime.now().isoformat(),
            turn_number=self.turn_counter,
        )

        self.history.append(turn)

        # Keep only recent history
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history :]

        logger.info(f"Added turn #{self.turn_counter} to conversation history")

        # Auto-save if path specified
        if self.save_path:
            self.save()

    def get_context(self, num_turns: int = 3) -> str:
        """
        Get conversation context for the last N turns.

        Args:
            num_turns: Number of recent turns to include

        Returns:
            Formatted conversation context
        """
        if not self.history:
            return ""

        recent_turns = self.history[-num_turns:]

        context_parts = []
        for turn in recent_turns:
            context_parts.append(
                f"Previous Question: {turn.question}\n" f"Previous Answer: {turn.answer}"
            )

        context = "\n\n".join(context_parts)

        logger.debug(f"Retrieved context from last {len(recent_turns)} turns")
        return context

    def get_recent_topics(self, num_turns: int = 5) -> list[str]:
        """
        Extract topics from recent conversation.

        Args:
            num_turns: Number of recent turns to analyze

        Returns:
            List of discussed topics/keywords
        """
        if not self.history:
            return []

        recent_turns = self.history[-num_turns:]

        # Extract key terms from questions (simple approach)
        topics = set()
        for turn in recent_turns:
            # Extract meaningful words (>3 chars, not common words)
            common_words = {
                "what",
                "when",
                "where",
                "who",
                "why",
                "how",
                "the",
                "is",
                "are",
                "was",
                "were",
                "be",
                "been",
                "have",
                "has",
                "had",
                "do",
                "does",
                "did",
            }

            words = turn.question.lower().split()
            for word in words:
                word = word.strip("?,.")
                if len(word) > 3 and word not in common_words:
                    topics.add(word)

        return list(topics)

    def get_full_history(self) -> list[dict[str, Any]]:
        """
        Get complete conversation history.

        Returns:
            List of conversation turns as dictionaries
        """
        return [turn.to_dict() for turn in self.history]

    def clear(self) -> None:
        """Clear conversation history."""
        self.history = []
        self.turn_counter = 0
        logger.info("Cleared conversation history")

    def save(self, path: Path | None = None) -> None:
        """
        Save conversation history to file.

        Args:
            path: File path to save to (uses self.save_path if not provided)
        """
        save_path = path or self.save_path

        if not save_path:
            logger.warning("No save path specified, skipping save")
            return

        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)

        history_data = {"turn_counter": self.turn_counter, "history": self.get_full_history()}

        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(history_data, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved conversation history to {save_path}")

    def load(self, path: Path | None = None) -> None:
        """
        Load conversation history from file.

        Args:
            path: File path to load from (uses self.save_path if not provided)
        """
        load_path = path or self.save_path

        if not load_path:
            logger.warning("No load path specified, skipping load")
            return

        load_path = Path(load_path)

        if not load_path.exists():
            logger.warning(f"History file not found: {load_path}")
            return

        try:
            with open(load_path, encoding="utf-8") as f:
                history_data = json.load(f)

            self.turn_counter = history_data.get("turn_counter", 0)

            self.history = []
            for turn_dict in history_data.get("history", []):
                turn = ConversationTurn(**turn_dict)
                self.history.append(turn)

            logger.info(f"Loaded {len(self.history)} turns from {load_path}")

        except Exception as e:
            logger.error(f"Error loading conversation history: {e}")

    def get_summary(self) -> str:
        """
        Get a summary of the conversation.

        Returns:
            Text summary of conversation
        """
        if not self.history:
            return "No conversation history."

        return (
            f"Conversation: {len(self.history)} turns\n"
            f"Topics: {', '.join(self.get_recent_topics())}\n"
            f"Started: {self.history[0].timestamp}\n"
            f"Last turn: {self.history[-1].timestamp}"
        )


if __name__ == "__main__":
    # Test conversation memory
    memory = ConversationMemory(max_history=5)

    # Simulate conversation
    memory.add_turn(
        question="What are stroke risk factors?",
        answer="The main risk factors are hypertension, diabetes, and age.",
        sources=[{"file": "study1.pdf", "page": 5}],
    )

    memory.add_turn(
        question="Tell me more about hypertension",
        answer="Hypertension is high blood pressure...",
        sources=[{"file": "study2.pdf", "page": 3}],
    )

    # Get context
    print("\nConversation Context:")
    print(memory.get_context(num_turns=2))

    print("\nRecent Topics:")
    print(memory.get_recent_topics())

    print("\nSummary:")
    print(memory.get_summary())
