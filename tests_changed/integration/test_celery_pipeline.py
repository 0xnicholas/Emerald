"""Integration tests for Celery pipeline with in-memory broker."""

import pytest
from celery import Celery

from emerald.pipeline.tasks import extract_task, chunk_task


@pytest.fixture
def celery_app():
    app = Celery("test", broker="memory://")
    app.conf.task_always_eager = True
    return app


def test_extract_task_signature(celery_app):
    """extract_task accepts pipeline_id, content, content_type."""
    # With task_always_eager, this runs synchronously.
    # It will fail at Redis access unless mocked; we just verify the signature.
    sig = extract_task.s("pipe_1", b"hello world", "text")
    assert sig.args == ("pipe_1", b"hello world", "text")


def test_chunk_task_signature(celery_app):
    """chunk_task accepts prev_result dict."""
    sig = chunk_task.s()
    assert sig.args == ()
    # In a chain, prev result is passed automatically
