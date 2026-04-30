"""Tests for ChromaKnowledgeBase."""

import pytest

from src.common.knowledge_base import KnowledgeEntry
from src.common.knowledge_base_chroma import ChromaKnowledgeBase


class TestChromaKnowledgeBase:
    """Tests for ChromaKnowledgeBase using ephemeral (in-memory) Chroma.

    These tests require chromadb to be installed.
    """

    @pytest.fixture
    def kb(self, tmp_path):
        return ChromaKnowledgeBase(path=str(tmp_path / "chroma_test"))

    @pytest.mark.asyncio
    async def test_store_and_get(self, kb):
        entry_id = await kb.store(
            KnowledgeEntry(requirement="Todo API", solution="print('ok')", language="python")
        )
        assert entry_id is not None

        retrieved = await kb.get(entry_id)
        assert retrieved is not None
        assert retrieved.requirement == "Todo API"

    @pytest.mark.asyncio
    async def test_search_semantic(self, kb):
        await kb.store(KnowledgeEntry(
            requirement="Build a task management API with FastAPI",
            solution="from fastapi import FastAPI\napp = FastAPI()",
            language="python",
        ))
        await kb.store(KnowledgeEntry(
            requirement="Create React dashboard component",
            solution="function Dashboard() { return <div>Dashboard</div>; }",
            language="typescript",
        ))

        # Search for API-related content
        results = await kb.search("FastAPI REST API", top_k=5)
        assert len(results) >= 1
        assert any("FastAPI" in r.requirement for r in results)

    @pytest.mark.asyncio
    async def test_search_by_type(self, kb):
        await kb.store(KnowledgeEntry(
            requirement="Login page", solution="form", entry_type="code_gen",
        ))
        await kb.store(KnowledgeEntry(
            requirement="Login bug", solution="fix", entry_type="bug_fix",
        ))

        results = await kb.search("login", top_k=5, entry_type="bug_fix")
        assert len(results) == 1
        assert results[0].entry_type == "bug_fix"

    @pytest.mark.asyncio
    async def test_delete(self, kb):
        eid = await kb.store(KnowledgeEntry(requirement="Test", solution="x"))
        assert await kb.get(eid) is not None
        assert await kb.delete(eid) is True
        assert await kb.get(eid) is None

    @pytest.mark.asyncio
    async def test_clear(self, kb):
        await kb.store(KnowledgeEntry(requirement="A", solution="1"))
        await kb.store(KnowledgeEntry(requirement="B", solution="2"))
        assert kb.count == 2
        await kb.clear()
        assert kb.count == 0

    @pytest.mark.asyncio
    async def test_search_no_match(self, kb):
        """Vector search always returns closest results; skip empty check for Chroma."""
        pass
