"""Tests for PipelineOrchestrator."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from emerald.pipeline.orchestrator import PipelineOrchestrator


@pytest.fixture
def orchestrator():
    from emerald.pipeline.extraction.registry import ExtractorRegistry
    from emerald.pipeline.extraction.text import TextExtractor
    from emerald.pipeline.chunking.registry import ChunkerRegistry
    from emerald.pipeline.chunking.text import TextChunker

    extractors = ExtractorRegistry()
    extractors.register("text", TextExtractor())
    chunkers = ChunkerRegistry()
    chunkers.register("text", TextChunker())

    return PipelineOrchestrator(
        extractor_registry=extractors,
        chunker_registry=chunkers,
        use_db=False,
    )


@pytest.mark.asyncio
async def test_process_sync_returns_memory_ids(orchestrator):
    """process_sync returns memory IDs for text content."""
    result = await orchestrator.process_sync(
        "用户喜欢 TypeScript",
        content_type="text",
        entity_id="user_123",
    )
    assert isinstance(result, list)
    assert len(result) > 0
    # Each item should be a hex-like memory ID
    assert all(isinstance(mid, str) and len(mid) > 0 for mid in result)


@pytest.mark.asyncio
async def test_process_sync_with_metadata(orchestrator):
    """process_sync accepts metadata."""
    result = await orchestrator.process_sync(
        "测试内容",
        content_type="text",
        entity_id="user_123",
        metadata={"source": "test"},
    )
    assert len(result) > 0


@pytest.mark.asyncio
async def test_process_async_entity_not_found(orchestrator):
    """process_async raises when entity does not exist in PG."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    with patch("emerald.pipeline.orchestrator.session_factory") as mock_factory:
        mock_factory.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.session.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(ValueError, match="Entity 'unknown' not found"):
            await orchestrator.process_async(
                content="test",
                content_type="text",
                entity_id="unknown",
            )


@pytest.mark.asyncio
async def test_process_async_submits_pipeline(orchestrator):
    """process_async writes PipelineJob and submits Celery chain."""
    from uuid import uuid4

    fake_entity = MagicMock()
    fake_entity.id = uuid4()

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = fake_entity
    mock_session.execute.return_value = mock_result

    with patch("emerald.pipeline.orchestrator.session_factory") as mock_factory:
        mock_factory.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.session.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("emerald.pipeline.orchestrator.chain") as mock_chain:
            mock_chain.return_value.apply_async = MagicMock()

            pipeline_id = await orchestrator.process_async(
                content="test content",
                content_type="text",
                entity_id="user_123",
                document_id=str(uuid4()),
            )

    assert isinstance(pipeline_id, str)
    assert len(pipeline_id) == 32  # hex uuid without dashes
    mock_session.add.assert_called_once()
    mock_session.commit.assert_called_once()
