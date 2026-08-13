"""Tests for SemanticTextChunker."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from emerald.pipeline.chunking.fact_extractor import Fact
from emerald.pipeline.chunking.text import SemanticTextChunker

# Sample text that produces multiple chunks via TextChunker's paragraph logic
MULTI_PARAGRAPH_TEXT = (
    "This is the first paragraph with enough content to be meaningful. "
    "It contains multiple sentences so that it forms a proper chunk.\n\n"
    "This is the second paragraph. It also has its own content here. "
    "And this is another sentence in the second paragraph.\n\n"
    "Third paragraph with its own unique text. More content goes here."
)


class TestSemanticTextChunker:
    """Tests for SemanticTextChunker with mocked FactExtractor."""

    # ---- helpers ----

    @staticmethod
    def _mock_extractor(facts: list[Fact] | None = None) -> AsyncMock:
        """Build an AsyncMock FactExtractor that returns the given facts."""
        mock = AsyncMock()
        mock.extract = AsyncMock(return_value=(facts or []))
        return mock

    @staticmethod
    def _mock_extractor_raises() -> AsyncMock:
        """Build an AsyncMock FactExtractor that raises."""
        mock = AsyncMock()
        mock.extract = AsyncMock(side_effect=Exception("LLM error"))
        return mock

    # ---- tests ----

    @pytest.mark.asyncio
    async def test_with_fact_extractor_produces_typed_chunks(self):
        extractor = self._mock_extractor(
            [
                Fact(text="Alex works at Stripe", memory_type="fact", confidence=0.9, summary="Job at Stripe"),
                Fact(text="Alex prefers morning meetings", memory_type="preference", confidence=0.85, summary="Morning preference"),
            ]
        )
        chunker = SemanticTextChunker(fact_extractor=extractor)

        chunks = await chunker.chunk("Alex works at Stripe and prefers morning meetings.")

        assert len(chunks) == 2
        assert chunks[0].text == "Alex works at Stripe"
        assert chunks[0].memory_type == "fact"
        assert chunks[0].confidence == 0.9
        assert chunks[0].summary == "Job at Stripe"
        assert chunks[0].content_type == "text"
        assert chunks[1].text == "Alex prefers morning meetings"
        assert chunks[1].memory_type == "preference"
        assert chunks[1].confidence == 0.85
        assert chunks[1].summary == "Morning preference"
        assert chunks[1].content_type == "text"

    @pytest.mark.asyncio
    async def test_empty_facts_falls_back_to_parent(self):
        extractor = self._mock_extractor([])
        chunker = SemanticTextChunker(fact_extractor=extractor)

        chunks = await chunker.chunk(MULTI_PARAGRAPH_TEXT)

        # Fallback to parent TextChunker should produce chunks from paragraphs
        assert len(chunks) >= 1
        for c in chunks:
            assert c.content_type == "text"
            # parent TextChunker uses defaults
            assert c.memory_type == "fact"
            assert c.confidence == 0.8

    @pytest.mark.asyncio
    async def test_without_fact_extractor_delegates_to_parent(self):
        chunker = SemanticTextChunker(fact_extractor=None)

        chunks = await chunker.chunk(MULTI_PARAGRAPH_TEXT)

        assert len(chunks) >= 1
        for c in chunks:
            assert c.content_type == "text"
            # parent TextChunker produces chunks with default metadata
            assert c.memory_type == "fact"
            assert c.confidence == 0.8

    @pytest.mark.asyncio
    async def test_fact_extractor_exception_falls_back(self):
        extractor = self._mock_extractor_raises()
        chunker = SemanticTextChunker(fact_extractor=extractor)

        # Should not raise, should fall back to parent
        chunks = await chunker.chunk(MULTI_PARAGRAPH_TEXT)

        assert len(chunks) >= 1
        for c in chunks:
            assert c.content_type == "text"

    @pytest.mark.asyncio
    async def test_empty_text_returns_empty(self):
        extractor = self._mock_extractor(
            [Fact(text="ignored", memory_type="fact", confidence=0.5, summary="s")]
        )
        chunker = SemanticTextChunker(fact_extractor=extractor)

        chunks = await chunker.chunk("")

        assert chunks == []
        # Extractor should not be called for empty text
        extractor.extract.assert_not_called()

    @pytest.mark.asyncio
    async def test_fact_chunks_have_correct_indices(self):
        extractor = self._mock_extractor(
            [
                Fact(text="Fact A", memory_type="fact", confidence=0.8, summary="A"),
                Fact(text="Fact B", memory_type="fact", confidence=0.7, summary="B"),
                Fact(text="Fact C", memory_type="episodic", confidence=0.6, summary="C"),
            ]
        )
        chunker = SemanticTextChunker(fact_extractor=extractor)

        chunks = await chunker.chunk("some text")

        assert len(chunks) == 3
        assert chunks[0].index == 0
        assert chunks[1].index == 1
        assert chunks[2].index == 2
        assert chunks[2].memory_type == "episodic"


    @pytest.mark.asyncio
    async def test_fact_mentions_propagate_to_chunks(self):
        """LLM-extracted mentions land on the semantic chunks (B3 NER)."""
        from emerald.core.mentions import Mention

        extractor = self._mock_extractor(
            [
                Fact(
                    text="Alex works at Stripe",
                    memory_type="fact",
                    confidence=0.9,
                    summary="Job",
                    mentions=[
                        Mention("Stripe", "Stripe", "organization", 0.95),
                        Mention("Alex", "Alex", "person", 0.9),
                    ],
                ),
            ]
        )
        chunker = SemanticTextChunker(fact_extractor=extractor)
        chunks = await chunker.chunk("Alex works at Stripe.")
        assert len(chunks) == 1
        assert [m.canonical_form for m in chunks[0].mentions] == ["Stripe", "Alex"]
        assert chunks[0].mentions[0].type == "organization"
