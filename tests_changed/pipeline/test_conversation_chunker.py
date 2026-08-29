"""Tests for ConversationChunker."""

from unittest.mock import AsyncMock

import pytest

from emerald.pipeline.chunking.conversation import ConversationChunker
from emerald.pipeline.chunking.fact_extractor import Fact, FactExtractor


@pytest.fixture
def chunker():
    return ConversationChunker()


async def test_chunk_splits_by_speaker(chunker):
    """Each speaker turn becomes its own chunk."""
    text = (
        "User: 你好，我想了解一下 TypeScript\n"
        "Assistant: TypeScript 是一种强类型编程语言\n"
        "User: 它和 JavaScript 有什么区别？\n"
        "Assistant: TypeScript 是 JavaScript 的超集，添加了静态类型系统"
    )
    chunks = await chunker.chunk(text)
    assert len(chunks) == 4
    assert "User:" in chunks[0].text
    assert "Assistant:" in chunks[1].text


async def test_chunk_preserves_speaker_identity(chunker):
    """Speaker labels are preserved in chunks."""
    text = "User: 我叫张三\nAssistant: 你好张三"
    chunks = await chunker.chunk(text)
    assert len(chunks) == 2
    assert chunks[0].metadata.get("speaker") == "User"
    assert chunks[1].metadata.get("speaker") == "Assistant"


async def test_chunk_content_type_conversation(chunker):
    """Chunks carry content_type='conversation'."""
    chunks = await chunker.chunk("User: Hello\nAssistant: Hi")
    for c in chunks:
        assert c.content_type == "conversation"


async def test_chunk_no_overlap(chunker):
    """Conversation chunks should not overlap."""
    assert chunker.overlap_size == 0
    text = ("User: A\nAssistant: B\nUser: C\nAssistant: D\nUser: E\nAssistant: F\n"
            "User: G\nAssistant: H\nUser: I\nAssistant: J\n")
    chunks = await chunker.chunk(text)
    # No overlap in conversation — each turn is independent
    assert all(hasattr(c, "metadata") for c in chunks)


async def test_chunk_single_speaker(chunker):
    """Single speaker without format still chunked."""
    text = "这是一段没有标注说话人的长文本。" * 50
    chunks = await chunker.chunk(text)
    assert len(chunks) > 0


async def test_chunk_turn_index_metadata(chunker):
    """Each chunk records its turn index."""
    text = "User: 1\nAssistant: 2\nUser: 3"
    chunks = await chunker.chunk(text)
    for i, c in enumerate(chunks):
        assert c.metadata.get("turn_index") == i


async def test_fact_extraction_produces_typed_chunks():
    """With FactExtractor, facts become chunks with correct types."""
    mock_extractor = AsyncMock(spec=FactExtractor)
    mock_extractor.extract.return_value = [
        Fact(text="Alex works at Stripe", memory_type="fact", confidence=0.9, summary="Job"),
        Fact(text="Alex prefers mornings", memory_type="preference", confidence=0.85, summary="Preference"),
    ]
    chunker = ConversationChunker(fact_extractor=mock_extractor)
    chunks = await chunker.chunk("Alex works at Stripe and prefers mornings.")
    assert len(chunks) == 2
    assert chunks[0].content_type == "conversation"
    assert chunks[0].memory_type == "fact"
    assert chunks[0].confidence == 0.9
    assert chunks[1].memory_type == "preference"
    assert chunks[0].metadata["speaker"] == "unknown"


async def test_fact_extraction_empty_falls_back_to_turns():
    """When FactExtractor returns empty, fall back to turn-based chunking."""
    mock_extractor = AsyncMock(spec=FactExtractor)
    mock_extractor.extract.return_value = []
    chunker = ConversationChunker(fact_extractor=mock_extractor)
    text = "User: hello\nAssistant: hi"
    chunks = await chunker.chunk(text)
    assert len(chunks) == 2
    assert chunks[0].metadata["speaker"] == "User"


async def test_fact_extraction_exception_falls_back_to_turns():
    """When FactExtractor raises, fall back to turn-based chunking."""
    mock_extractor = AsyncMock(spec=FactExtractor)
    mock_extractor.extract.side_effect = RuntimeError("API down")
    chunker = ConversationChunker(fact_extractor=mock_extractor)
    text = "User: hello\nAssistant: hi"
    chunks = await chunker.chunk(text)
    assert len(chunks) == 2


async def test_no_fact_extractor_uses_turn_based():
    """Without FactExtractor, standard turn-based chunking is used."""
    chunker = ConversationChunker()
    text = "User: hello\nAssistant: hi"
    chunks = await chunker.chunk(text)
    assert len(chunks) == 2


async def test_fact_extraction_propagates_mentions():
    """Mentions extracted by the LLM path land on the conversation chunks."""
    from emerald.core.mentions import Mention

    mock_extractor = AsyncMock(spec=FactExtractor)
    mock_extractor.extract.return_value = [
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
    chunker = ConversationChunker(fact_extractor=mock_extractor)
    chunks = await chunker.chunk("Alex works at Stripe.")
    assert len(chunks) == 1
    assert [m.canonical_form for m in chunks[0].mentions] == ["Stripe", "Alex"]
    assert chunks[0].mentions[0].type == "organization"
