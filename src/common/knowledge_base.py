"""Knowledge Base — store and retrieve agent experiences and fixes.

Two backends:
- JsonKnowledgeBase: file-based, lightweight, no dependencies (default)
- ChromaKnowledgeBase: vector-based, requires chromadb (optional, for production)

Usage:
    kb = JsonKnowledgeBase(path="./kb_data")
    await kb.store(entry={"requirement": "Todo API", "solution": "..."})
    results = await kb.search("Todo API", top_k=3)
"""

from abc import ABC, abstractmethod
from typing import Optional


class KnowledgeEntry:
    """A single knowledge entry stored in the knowledge base."""

    def __init__(
        self,
        requirement: str,
        solution: str,
        language: str = "",
        entry_type: str = "code_gen",
        metadata: Optional[dict] = None,
        entry_id: Optional[str] = None,
    ):
        self.requirement = requirement
        self.solution = solution
        self.language = language
        self.entry_type = entry_type
        self.metadata = metadata or {}
        self.entry_id = entry_id

    def to_dict(self) -> dict:
        return {
            "requirement": self.requirement,
            "solution": self.solution,
            "language": self.language,
            "entry_type": self.entry_type,
            "metadata": self.metadata,
            "entry_id": self.entry_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "KnowledgeEntry":
        return cls(
            requirement=data["requirement"],
            solution=data["solution"],
            language=data.get("language", ""),
            entry_type=data.get("entry_type", "code_gen"),
            metadata=data.get("metadata", {}),
            entry_id=data.get("entry_id"),
        )


class BaseKnowledgeBase(ABC):
    """Abstract knowledge base interface."""

    @abstractmethod
    async def store(self, entry: KnowledgeEntry) -> str:
        """Store an entry. Returns entry_id."""
        ...

    @abstractmethod
    async def search(
        self, query: str, top_k: int = 5, entry_type: Optional[str] = None
    ) -> list[KnowledgeEntry]:
        """Search for relevant entries."""
        ...

    @abstractmethod
    async def get(self, entry_id: str) -> Optional[KnowledgeEntry]:
        """Retrieve a specific entry by ID."""
        ...

    @abstractmethod
    async def delete(self, entry_id: str) -> bool:
        """Delete an entry by ID."""
        ...
