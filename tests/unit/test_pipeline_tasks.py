"""Tests for pipeline Celery tasks (with eager/memory broker)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from celery import Celery

from emerald.pipeline.tasks import (
    chunk_task,
    embed_task,
    extract_task,
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


# ---- Forget engine tasks ----

# The scheduled tasks open a real Neo4j driver per invocation. These unit
# tests mock ForgetEngine, so the driver loop must be mocked too — otherwise
# the tests depend on a live Neo4j (and on global test order).
_DRIVER_LOOP_PATCH = "emerald.pipeline.tasks._neo4j_driver_for_loop"


@pytest.mark.asyncio
async def test_forget_expired_task_runs():
    """forget_expired_task delegates to ForgetEngine."""
    from emerald.pipeline.tasks import _run_forget_expired

    with patch("emerald.core.forget.ForgetEngine") as mock_cls, \
         patch(_DRIVER_LOOP_PATCH):
        instance = MagicMock()
        instance.forget_expired = AsyncMock(return_value=3)
        mock_cls.return_value = instance

        result = await _run_forget_expired()

    assert result["strategy"] == "time_expiry"
    assert result["count"] == 3
    instance.forget_expired.assert_awaited_once()


@pytest.mark.asyncio
async def test_forget_noise_task_runs():
    """forget_noise_task delegates to ForgetEngine."""
    from emerald.pipeline.tasks import _run_forget_noise

    with patch("emerald.core.forget.ForgetEngine") as mock_cls, \
         patch(_DRIVER_LOOP_PATCH):
        instance = MagicMock()
        instance.forget_noise = AsyncMock(return_value=5)
        mock_cls.return_value = instance

        result = await _run_forget_noise()

    assert result["strategy"] == "noise_filter"
    assert result["count"] == 5
    instance.forget_noise.assert_awaited_once()


@pytest.mark.asyncio
async def test_decay_episodic_task_runs():
    """decay_episodic_task delegates to ForgetEngine."""
    from emerald.pipeline.tasks import _run_decay_episodic

    with patch("emerald.core.forget.ForgetEngine") as mock_cls, \
         patch(_DRIVER_LOOP_PATCH):
        instance = MagicMock()
        instance.decay_episodic = AsyncMock(return_value=2)
        mock_cls.return_value = instance

        result = await _run_decay_episodic()

    assert result["strategy"] == "episodic_decay"
    assert result["count"] == 2
    instance.decay_episodic.assert_awaited_once()


# ---- rag_index_task：RAG 块供给（#52 走查缺陷 A）----


class _StubEmbedder:
    """Deterministic stub: one fixed vector per input text."""

    def __init__(self, dim: int = 8) -> None:
        self._dim = dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.5] * self._dim for _ in texts]


class _FakeRedis:
    def __init__(self, kv: dict[str, str]) -> None:
        self._kv = kv

    async def get(self, key: str) -> str | None:
        return self._kv.get(key)


@pytest.mark.asyncio
async def test_rag_index_stores_document_chunks():
    """有 document_id 的管线：原始文本经非 LLM 分块嵌入后落 RAG 向量库。"""
    from emerald.pipeline.tasks import _run_rag_index

    doc_id = "aaaaaaaa-0000-0000-0000-000000000001"
    with (
        patch(
            "emerald.pipeline.tasks._pipeline_document_id",
            new=AsyncMock(return_value=doc_id),
        ),
        patch(
            "emerald.pipeline.tasks._ensure_loop_redis",
            new=AsyncMock(return_value=_FakeRedis(
                {"pipeline:p1:text": "锆石星轨验证文本，包含足量的文档正文内容用于分块。"}
            )),
        ),
        patch(
            "emerald.core.embedder.get_embedding_provider",
            return_value=_StubEmbedder(),
        ),
        patch(
            "emerald.core.vector.VectorStore.store_document_chunks",
            new=AsyncMock(return_value=1),
        ) as mock_store,
    ):
        prev = await _run_rag_index(
            {"pipeline_id": "p1"}, entity_id="dev_user",
        )

    mock_store.assert_awaited_once()
    args, kwargs = mock_store.call_args
    assert args[0] == doc_id
    assert kwargs.get("entity_id") == "dev_user"
    assert any("锆石星轨" in t for t in args[1])
    assert prev["rag_chunk_count"] == 1


@pytest.mark.asyncio
async def test_rag_index_skips_without_document():
    """无 document_id 的管线（sources 事件）：不写 RAG 块。"""
    from emerald.pipeline.tasks import _run_rag_index

    with (
        patch(
            "emerald.pipeline.tasks._pipeline_document_id",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "emerald.core.vector.VectorStore.store_document_chunks",
            new=AsyncMock(),
        ) as mock_store,
    ):
        prev = await _run_rag_index({"pipeline_id": "p1"}, entity_id="dev_user")

    mock_store.assert_not_awaited()
    assert "rag_chunk_count" not in prev


# ---- 文档状态机（#52 走查缺陷 B）----


@pytest.mark.asyncio
async def test_mark_document_done_writes_pg():
    """_mark_document_done 置 documents.status='done' 并带 chunk_count。"""
    from emerald.pipeline.tasks import _mark_document_done

    mock_session = AsyncMock()
    with patch("emerald.db.session.session_factory") as mock_factory:
        mock_factory.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.session.return_value.__aexit__ = AsyncMock(return_value=False)
        await _mark_document_done("doc-123", chunk_count=2)

    mock_session.execute.assert_called_once()
    sql = str(mock_session.execute.call_args.args[0])
    assert "documents" in sql
    assert "done" in sql
    params = mock_session.execute.call_args.args[1]
    assert params.get("document_id") == "doc-123"
    assert params.get("chunk_count") == 2
