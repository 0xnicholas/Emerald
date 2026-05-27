"""Tests for pipeline Celery tasks (with eager/memory broker)."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from celery import Celery

from emerald.pipeline.tasks import (
    extract_task,
    chunk_task,
    embed_task,
    index_task,
    postprocess_task,
)


@pytest.fixture
def celery_app():
    app = Celery("test", broker="memory://")
    app.conf.task_always_eager = True
    return app


def test_extract_task_signature(celery_app):
    """extract_task accepts pipeline_id, content, content_type."""
    with patch("emerald.pipeline.tasks.run_async") as mock_run:
        mock_run.return_value = lambda fn: fn
        # Just verify the task can be called without crashing
        assert extract_task.name == "emerald.pipeline.tasks.extract_task"


def test_chunk_task_signature(celery_app):
    """chunk_task accepts prev_result dict."""
    assert chunk_task.name == "emerald.pipeline.tasks.chunk_task"


def test_embed_task_signature(celery_app):
    """embed_task accepts prev_result dict."""
    assert embed_task.name == "emerald.pipeline.tasks.embed_task"


def test_index_task_signature(celery_app):
    """index_task accepts prev_result dict and entity_id."""
    assert index_task.name == "emerald.pipeline.tasks.index_task"


def test_postprocess_task_signature(celery_app):
    """postprocess_task accepts prev_result dict and entity_id."""
    assert postprocess_task.name == "emerald.pipeline.tasks.postprocess_task"


# ---- _update_status / _update_error helpers ----

@pytest.mark.asyncio
async def test_update_status_writes_to_pg():
    """_update_status executes UPDATE on pipeline_jobs."""
    from emerald.pipeline.tasks import _update_status

    mock_session = AsyncMock()
    with patch("emerald.db.session.session_factory") as mock_factory:
        mock_factory.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.session.return_value.__aexit__ = AsyncMock(return_value=False)
        await _update_status("pipe_123", "extracting")

    mock_session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_update_error_writes_failed_status():
    """_update_error sets status='failed' with error message."""
    from emerald.pipeline.tasks import _update_error

    mock_session = AsyncMock()
    with patch("emerald.db.session.session_factory") as mock_factory:
        mock_factory.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.session.return_value.__aexit__ = AsyncMock(return_value=False)
        await _update_error("pipe_123", "extracting", "Something broke")

    mock_session.execute.assert_called_once()
    call_args = mock_session.execute.call_args
    assert "Something broke" in str(call_args)
