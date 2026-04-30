"""Tests for JsonKnowledgeBase."""

import pytest

from src.common.knowledge_base import KnowledgeEntry
from src.common.knowledge_base_json import JsonKnowledgeBase


class TestKnowledgeEntry:
    def test_to_dict_roundtrip(self):
        entry = KnowledgeEntry(
            requirement="Build a Todo API",
            solution="print('hello')",
            language="python",
            entry_type="code_gen",
            metadata={"version": 1},
        )
        data = entry.to_dict()
        restored = KnowledgeEntry.from_dict(data)
        assert restored.requirement == "Build a Todo API"
        assert restored.solution == "print('hello')"
        assert restored.language == "python"


class TestJsonKnowledgeBase:
    @pytest.fixture
    def kb(self, tmp_path):
        return JsonKnowledgeBase(path=str(tmp_path / "kb_test"))

    @pytest.mark.asyncio
    async def test_store_and_get(self, kb):
        entry_id = await kb.store(
            KnowledgeEntry(requirement="Test", solution="print('ok')")
        )
        assert entry_id is not None

        retrieved = await kb.get(entry_id)
        assert retrieved is not None
        assert retrieved.requirement == "Test"

    @pytest.mark.asyncio
    async def test_store_persists_to_disk(self, tmp_path):
        path = str(tmp_path / "kb_persist")
        kb = JsonKnowledgeBase(path=path)
        await kb.store(KnowledgeEntry(requirement="Persist", solution="ok"))

        # New instance reads same file
        kb2 = JsonKnowledgeBase(path=path)
        assert kb2.count == 1

    @pytest.mark.asyncio
    async def test_search_keyword(self, kb):
        await kb.store(KnowledgeEntry(
            requirement="Create React todo component",
            solution="function Todo() { return <div>todo</div>; }",
            language="typescript",
        ))
        await kb.store(KnowledgeEntry(
            requirement="Build FastAPI health endpoint",
            solution="async def health(): return {'status': 'ok'}",
            language="python",
        ))

        results = await kb.search("React", top_k=5)
        assert len(results) == 1
        assert "React" in results[0].requirement

        results = await kb.search("endpoint", top_k=5)
        assert len(results) == 1
        assert "FastAPI" in results[0].requirement

    @pytest.mark.asyncio
    async def test_search_by_type(self, kb):
        await kb.store(KnowledgeEntry(
            requirement="Code gen task",
            solution="print('a')",
            entry_type="code_gen",
        ))
        await kb.store(KnowledgeEntry(
            requirement="Bug fix task",
            solution="print('b')",
            entry_type="bug_fix",
        ))

        results = await kb.search("task", top_k=5, entry_type="bug_fix")
        assert len(results) == 1
        assert "Bug fix" in results[0].requirement

    @pytest.mark.asyncio
    async def test_delete(self, kb):
        eid = await kb.store(KnowledgeEntry(requirement="Del", solution="x"))
        assert await kb.delete(eid) is True
        assert await kb.get(eid) is None
        assert await kb.delete("nonexistent") is False

    @pytest.mark.asyncio
    async def test_clear(self, kb):
        await kb.store(KnowledgeEntry(requirement="A", solution="1"))
        await kb.store(KnowledgeEntry(requirement="B", solution="2"))
        assert kb.count == 2
        await kb.clear()
        assert kb.count == 0

    @pytest.mark.asyncio
    async def test_search_no_match(self, kb):
        await kb.store(KnowledgeEntry(requirement="Python", solution="print"))
        results = await kb.search("Rust", top_k=5)
        assert results == []
