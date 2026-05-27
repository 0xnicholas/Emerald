"""Tests for ConversationChunker with Markdown bold speaker labels.

Per the plan: ConversationChunker previously only matched plain-text speaker labels
(User:). It did not recognize Pandaria's Markdown bold format (**User**:). The regex
has been updated to match both — these tests verify correct behavior.

Covers: **User**:, **Assistant**:, **System**:, **AI**:, **Human**:, **Bot**:
in both plain and bold variants, and mixed transcripts.
"""

import pytest

from emerald.pipeline.chunking.conversation import ConversationChunker


@pytest.fixture
def chunker():
    return ConversationChunker()


# ── Markdown bold format: basic recognition ──────────────────────────────


def test_chunk_splits_by_markdown_bold_speaker(chunker):
    """**User**: and **Assistant**: turn markers are recognized and split correctly."""
    text = (
        "**User**: 你好，我想了解一下 TypeScript\n"
        "**Assistant**: TypeScript 是一种强类型编程语言\n"
        "**User**: 它和 JavaScript 有什么区别？\n"
        "**Assistant**: TypeScript 是 JavaScript 的超集"
    )
    chunks = chunker.chunk(text)
    assert len(chunks) == 4


def test_markdown_bold_preserves_speaker_identity(chunker):
    """Speaker extracted from **Speaker**: format is correct (no asterisks in name)."""
    text = "**User**: 我叫张三\n**Assistant**: 你好张三"
    chunks = chunker.chunk(text)
    assert len(chunks) == 2
    assert chunks[0].metadata["speaker"] == "User"
    assert chunks[1].metadata["speaker"] == "Assistant"


def test_markdown_bold_system_speaker(chunker):
    """**System**: turn marker is recognized."""
    text = "**System**: 初始化上下文\n**User**: 开始对话"
    chunks = chunker.chunk(text)
    assert len(chunks) == 2
    assert chunks[0].metadata["speaker"] == "System"
    assert chunks[1].metadata["speaker"] == "User"


def test_markdown_bold_ai_human_bot_speakers(chunker):
    """**AI**:, **Human**:, **Bot**: variants are all recognized."""
    text = (
        "**Human**: Hello\n"
        "**AI**: Hi there\n"
        "**Bot**: How can I help?\n"
        "**Human**: I need assistance"
    )
    chunks = chunker.chunk(text)
    assert len(chunks) == 4
    speakers = [c.metadata["speaker"] for c in chunks]
    assert speakers == ["Human", "AI", "Bot", "Human"]


def test_markdown_bold_single_turn(chunker):
    """A single **User**: turn creates exactly one chunk."""
    text = "**User**: 这是唯一的消息"
    chunks = chunker.chunk(text)
    assert len(chunks) == 1
    assert chunks[0].metadata["speaker"] == "User"


# ── Mixed plain and bold speakers ────────────────────────────────────────


def test_mixed_plain_and_bold_speakers(chunker):
    """Transcripts mixing plain Speaker: and **Speaker**: are handled correctly."""
    text = (
        "User: 你好\n"
        "**Assistant**: 你好！有什么我可以帮助你的吗？\n"
        "User: 今天天气怎么样？\n"
        "**Assistant**: 抱歉，我没有天气信息"
    )
    chunks = chunker.chunk(text)
    assert len(chunks) == 4
    # All speakers should be extracted correctly (no ** in the name)
    for c in chunks:
        assert "**" not in c.metadata["speaker"]


def test_mixed_all_variants(chunker):
    """All bold/plain combinations across all speaker labels."""
    text = (
        "Human: 问题一\n"
        "**AI**: 回答一\n"
        "User: 问题二\n"
        "**Assistant**: 回答二\n"
        "Bot: 系统消息\n"
        "**System**: 内部提示"
    )
    chunks = chunker.chunk(text)
    assert len(chunks) == 6
    expected_speakers = ["Human", "AI", "User", "Assistant", "Bot", "System"]
    assert [c.metadata["speaker"] for c in chunks] == expected_speakers


# ── Content integrity ────────────────────────────────────────────────────


def test_markdown_bold_content_not_mangled(chunker):
    """The turn content after **Speaker**: is not mangled or truncated."""
    text = (
        "**User**: 我想了解关于 TypeScript 泛型的用法，特别是在函数重载场景下。\n"
        "**Assistant**: TypeScript 泛型允许你创建可复用的组件，这些组件可以支持多种类型。"
    )
    chunks = chunker.chunk(text)
    assert len(chunks) == 2
    assert "泛型的用法" in chunks[0].text
    assert "可复用的组件" in chunks[1].text


def test_markdown_bold_content_preserves_markdown(chunker):
    """Content after **Speaker**: that also contains markdown is preserved as-is."""
    text = (
        "**User**: 请解释 `const x: number = 42;` 的含义\n"
        "**Assistant**: 这是 TypeScript 的类型注解语法。`const` 声明一个常量，`number` 是类型。"
    )
    chunks = chunker.chunk(text)
    assert len(chunks) == 2
    assert "`const x: number = 42;`" in chunks[0].text
    assert "`const`" in chunks[1].text


def test_markdown_bold_multiline_content(chunker):
    """Multi-line content within a bold turn is preserved."""
    text = (
        "**User**: 我有三个问题：\n"
        "1. 什么是闭包？\n"
        "2. 如何实现柯里化？\n"
        "3. 函数式编程的核心是什么？\n"
        "**Assistant**: 很好的问题，让我逐一回答。"
    )
    chunks = chunker.chunk(text)
    assert len(chunks) == 2
    user_chunk = chunks[0]
    assert "闭包" in user_chunk.text
    assert "柯里化" in user_chunk.text
    assert "函数式编程" in user_chunk.text


# ── Metadata correctness ─────────────────────────────────────────────────


def test_markdown_bold_turn_index_in_order(chunker):
    """Turn index metadata is sequential for bold-formatted turns."""
    text = (
        "**User**: A\n"
        "**Assistant**: B\n"
        "**User**: C\n"
        "**Assistant**: D\n"
        "**User**: E"
    )
    chunks = chunker.chunk(text)
    assert len(chunks) == 5
    for i, c in enumerate(chunks):
        assert c.metadata["turn_index"] == i


def test_markdown_bold_content_type_conversation(chunker):
    """Content type is always 'conversation' for bold-format transcripts."""
    text = "**User**: Hello\n**Assistant**: Hi"
    chunks = chunker.chunk(text)
    for c in chunks:
        assert c.content_type == "conversation"


def test_markdown_bold_offset_metadata(chunker):
    """char_offset_start and char_offset_end are set correctly for bold turns."""
    text = "**User**: Hello\n**Assistant**: Hi there"
    chunks = chunker.chunk(text)
    for c in chunks:
        assert "char_offset_start" in c.metadata
        assert "char_offset_end" in c.metadata
        assert c.metadata["char_offset_start"] < c.metadata["char_offset_end"]


# ── Edge cases ───────────────────────────────────────────────────────────


def test_bold_empty_turn_content(chunker):
    """A **Speaker**: with no content after it produces a chunk with empty content."""
    text = "**User**: \n**Assistant**: 你好"
    chunks = chunker.chunk(text)
    assert len(chunks) == 2
    # First turn has empty content (only whitespace after ": ")
    assert chunks[0].text.strip() == "User:"


def test_bold_only_asterisks_not_speaker(chunker):
    """Text with ** but not matching the speaker pattern is not treated as a turn."""
    text = "这是一段包含 **加粗** 文字但不是对话的内容"
    chunks = chunker.chunk(text)
    # No speaker labels detected → falls back to size-based chunking
    assert len(chunks) > 0
    # The original text should be preserved in the chunks (not split on **)
    combined = " ".join(c.text for c in chunks)
    assert "加粗" in combined
    for c in chunks:
        assert c.content_type == "conversation"
        # Should NOT have speaker metadata (fallback chunking has no speaker)
        assert c.metadata.get("speaker", "unknown") == "unknown"


def test_bold_no_overlap(chunker):
    """Conversation chunks have no overlap (overlap_size=0), even for bold format."""
    assert chunker.overlap_size == 0


def test_bold_case_insensitive(chunker):
    """**user**:, **USER**:, **User**: are all treated equivalently (case-insensitive)."""
    text = (
        "**user**: lowercase\n"
        "**USER**: uppercase\n"
        "**User**: title case\n"
        "**Assistant**: normal"
    )
    chunks = chunker.chunk(text)
    assert len(chunks) == 4
    assert chunks[0].metadata["speaker"] == "user"
    assert chunks[1].metadata["speaker"] == "USER"
    assert chunks[2].metadata["speaker"] == "User"


# ── Pandaria integration scenario ────────────────────────────────────────


def test_pandaria_conversation_format(chunker):
    """Full Pandaria-style Markdown transcript with bold speakers chunked correctly.

    This is the exact format Pandaria's agent outputs — a Markdown string with
    **User**: / **Assistant**: turn markers wrapping multi-paragraph content.
    """
    transcript = (
        "**User**: 我需要实现一个记忆系统。\n"
        "具体要求：\n"
        "- 支持长期和短期记忆\n"
        "- 自动提取关键事实\n"
        "- 能够处理时序信息\n"
        "\n"
        "**Assistant**: 这是一个很好的需求。我建议采用知识图谱架构。\n"
        "核心设计要点：\n"
        "1. 每个记忆作为图谱中的一个节点\n"
        "2. 通过关系连接相关记忆\n"
        "3. 支持更新、扩展和推导三种关系类型\n"
        "\n"
        "**User**: 图谱和向量数据库如何配合？\n"
        "\n"
        "**Assistant**: 两者互补。图谱处理结构化关系和时序推理，向量数据库处理语义相似性搜索。\n"
        "我们可以在图谱节点上附加向量嵌入，实现混合搜索。"
    )
    chunks = chunker.chunk(transcript)

    assert len(chunks) == 4
    assert chunks[0].metadata["speaker"] == "User"
    assert chunks[1].metadata["speaker"] == "Assistant"
    assert chunks[2].metadata["speaker"] == "User"
    assert chunks[3].metadata["speaker"] == "Assistant"

    # Verify content is complete — the multi-paragraph content should be preserved
    assert "知识图谱架构" in chunks[1].text
    assert "图谱和向量数据库" in chunks[2].text
    assert "混合搜索" in chunks[3].text

    # All chunks have conversation type
    for c in chunks:
        assert c.content_type == "conversation"
