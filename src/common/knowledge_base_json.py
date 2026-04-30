"""JSON file-based knowledge base — lightweight, zero dependencies, for dev/test."""

import json
import uuid
from pathlib import Path
from typing import Optional

from .knowledge_base import BaseKnowledgeBase, KnowledgeEntry


class JsonKnowledgeBase(BaseKnowledgeBase):
    """File-based knowledge store using JSON for persistence.

    Stores entries as a JSON array. Simple keyword matching for search.
    Intended for development and testing; swap to ChromaKnowledgeBase for production.
    """

    def __init__(self, path: str = "./kb_data"):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self._file = self.path / "kb.json"
        self._entries: dict[str, KnowledgeEntry] = {}
        self._load()

    def _load(self):
        if self._file.exists():
            try:
                data = json.loads(self._file.read_text())
                self._entries = {
                    eid: KnowledgeEntry.from_dict(edata)
                    for eid, edata in data.items()
                }
            except (json.JSONDecodeError, KeyError):
                self._entries = {}

    def _save(self):
        data = {eid: entry.to_dict() for eid, entry in self._entries.items()}
        self._file.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    async def store(self, entry: KnowledgeEntry) -> str:
        entry_id = entry.entry_id or str(uuid.uuid4())
        entry.entry_id = entry_id
        self._entries[entry_id] = entry
        self._save()
        return entry_id

    async def search(
        self, query: str, top_k: int = 5, entry_type: Optional[str] = None
    ) -> list[KnowledgeEntry]:
        """Simple keyword matching search. Orders by relevance score."""
        query_lower = query.lower()
        query_terms = query_lower.split()

        scored: list[tuple[KnowledgeEntry, int]] = []
        for entry in self._entries.values():
            if entry_type and entry.entry_type != entry_type:
                continue

            score = 0
            text = (entry.requirement + " " + entry.solution).lower()
            for term in query_terms:
                score += text.count(term) * 10
            # Boost exact matches in requirement
            if query_lower in entry.requirement.lower():
                score += 50

            if score > 0:
                scored.append((entry, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [entry for entry, _ in scored[:top_k]]

    async def get(self, entry_id: str) -> Optional[KnowledgeEntry]:
        return self._entries.get(entry_id)

    async def delete(self, entry_id: str) -> bool:
        if entry_id in self._entries:
            del self._entries[entry_id]
            self._save()
            return True
        return False

    @property
    def count(self) -> int:
        return len(self._entries)

    async def clear(self):
        self._entries = {}
        self._save()
