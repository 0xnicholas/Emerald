"""Tests for ConversationChunker."""

import pytest

from emerald.pipeline.chunking.conversation import ConversationChunker


@pytest.fixture
def chunker():
    return ConversationChunker()


def test_chunk_splits_by_speaker(chunker):
    """Each speaker turn becomes its own chunk."""
    text = (
        "User: 你好，我想了解一下 TypeScript\n"
        "Assistant: TypeScript 是一种强类型编程语言\n"
        "User: 它和 JavaScript 有什么区别？\n"
        "Assistant: TypeScript 是 JavaScript 的超集，添加了静态类型系统"
    )
    chunks = chunker.chunk(text)
    assert len(chunks) == 4
    assert "User:" in chunks[0].text
    assert "Assistant:" in chunks[1].text


def test_chunk_preserves_speaker_identity(chunker):
    """Speaker labels are preserved in chunks."""
    text = "User: 我叫张三\nAssistant: 你好张三"
    chunks = chunker.chunk(text)
    assert len(chunks) == 2
    assert chunks[0].metadata.get("speaker") == "User"
    assert chunks[1].metadata.get("speaker") == "Assistant"


def test_chunk_content_type_conversation(chunker):
    """Chunks carry content_type='conversation'."""
    chunks = chunker.chunk("User: Hello\nAssistant: Hi")
    for c in chunks:
        assert c.content_type == "conversation"


def test_chunk_no_overlap(chunker):
    """Conversation chunks should not overlap."""
    assert chunker.overlap_size == 0
    text = ("User: A\nAssistant: B\nUser: C\nAssistant: D\nUser: E\nAssistant: F\n"
            "User: G\nAssistant: H\nUser: I\nAssistant: J\n")
    chunks = chunker.chunk(text)
    # No overlap in conversation — each turn is independent
    assert all(hasattr(c, "metadata") for c in chunks)


def test_chunk_single_speaker(chunker):
    """Single speaker without format still chunked."""
    text = "这是一段没有标注说话人的长文本。" * 50
    chunks = chunker.chunk(text)
    assert len(chunks) > 0


def test_chunk_turn_index_metadata(chunker):
    """Each chunk records its turn index."""
    text = "User: 1\nAssistant: 2\nUser: 3"
    chunks = chunker.chunk(text)
    for i, c in enumerate(chunks):
        assert c.metadata.get("turn_index") == i
