"""Chroma vector-based knowledge base — for production use with semantic search."""

import os
import uuid
from typing import Optional

import chromadb
from chromadb.config import Settings

from .knowledge_base import BaseKnowledgeBase, KnowledgeEntry


class ChromaKnowledgeBase(BaseKnowledgeBase):
    """ChromaDB-backed knowledge store with semantic search.

    Uses vector embeddings for similarity search.
    Requires chromadb installed. Falls back to JsonKnowledgeBase if unavailable.

    Usage:
        kb = ChromaKnowledgeBase(path="./chroma_data")
        eid = await kb.store(KnowledgeEntry(requirement="...", solution="..."))
        results = await kb.search("similar query")
    """

    def __init__(self, path: str = "./chroma_data", collection_name: str = "agent_experience"):
        self.path = path
        os.makedirs(path, exist_ok=True)

        self._client = chromadb.PersistentClient(
            path=path,
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    async def store(self, entry: KnowledgeEntry) -> str:
        """Store an entry. Entry is stored synchronously (Chroma is sync)."""
        entry_id = entry.entry_id or str(uuid.uuid4())
        entry.entry_id = entry_id

        # Combine requirement and solution as the document text
        doc_text = f"{entry.requirement}\n\n{entry.solution}"

        self._collection.add(
            documents=[doc_text],
            metadatas=[{
                "requirement": entry.requirement,
                "solution": entry.solution,
                "language": entry.language,
                "entry_type": entry.entry_type,
            }],
            ids=[entry_id],
        )
        return entry_id

    async def search(
        self, query: str, top_k: int = 5, entry_type: Optional[str] = None
    ) -> list[KnowledgeEntry]:
        """Search for relevant entries using vector similarity."""
        where = None
        if entry_type:
            where = {"entry_type": entry_type}

        results = self._collection.query(
            query_texts=[query],
            n_results=min(top_k, 100),
            where=where,
        )

        entries = []
        if results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                entry = KnowledgeEntry(
                    requirement=metadata.get("requirement", ""),
                    solution=metadata.get("solution", ""),
                    language=metadata.get("language", ""),
                    entry_type=metadata.get("entry_type", "code_gen"),
                    entry_id=doc_id,
                )
                entries.append(entry)

        return entries

    async def get(self, entry_id: str) -> Optional[KnowledgeEntry]:
        """Retrieve a specific entry by ID."""
        try:
            result = self._collection.get(ids=[entry_id])
            if result["ids"] and result["ids"][0]:
                meta = (result["metadatas"][0] if result["metadatas"] else {}) or {}
                return KnowledgeEntry(
                    requirement=meta.get("requirement", ""),
                    solution=meta.get("solution", ""),
                    language=meta.get("language", ""),
                    entry_type=meta.get("entry_type", "code_gen"),
                    entry_id=entry_id,
                )
        except Exception:
            pass
        return None

    async def delete(self, entry_id: str) -> bool:
        try:
            self._collection.delete(ids=[entry_id])
            return True
        except Exception:
            return False

    async def clear(self):
        """Delete all entries in the collection."""
        all_ids = self._collection.get()["ids"]
        if all_ids:
            self._collection.delete(ids=all_ids)

    @property
    def count(self) -> int:
        return self._collection.count()
