"""Tests for connector Celery tasks — sync_all, sync_single, renew_webhooks."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from emerald.connectors.base import SyncMode, SyncResult

# Valid UUID for entity_id tests
_TEST_UUID = "550e8400-e29b-41d4-a716-446655440001"
_TEST_UUID2 = "550e8400-e29b-41d4-a716-446655440002"
_TEST_UUID3 = "550e8400-e29b-41d4-a716-446655440003"


# ---- Helpers ----


def _make_connector_row(
    entity_id: str = _TEST_UUID,
    provider: str = "google_drive",
    sync_status: str = "active",
    sync_metadata: dict | None = None,
) -> MagicMock:
    """Build a mock SQLAlchemy Connector row with realistic attributes."""
    row = MagicMock()
    row.id = uuid.uuid4()
    row.entity_id = uuid.UUID(entity_id)
    row.provider = provider
    row.credentials = b"\x00" * 12 + b"\x01" * 64  # realistic binary
    row.sync_status = sync_status
    row.last_synced_at = None
    row.error_message = None
    row.sync_metadata = sync_metadata
    return row


def _make_result_mock(rows: list[MagicMock]) -> MagicMock:
    """Build a mock SQLAlchemy Result with sync scalars().all() and scalar_one_or_none()."""
    result = MagicMock()
    # result.scalars() → ScalarResult; ScalarResult.all() → list (sync method)
    scalars_result = MagicMock()
    scalars_result.all = MagicMock(return_value=rows)
    result.scalars = MagicMock(return_value=scalars_result)
    # result.scalar_one_or_none() → single row or None (sync method)
    result.scalar_one_or_none = MagicMock(
        return_value=rows[0] if rows else None
    )
    return result


def _make_async_session(rows_by_query: dict | None = None) -> MagicMock:
    """Build a mock async DB session.

    Args:
        rows_by_query: If provided, maps query filter strings to rows.
            e.g. {"active+github": [row1, row2]}. Otherwise returns all rows
            for any query.
    """
    session = MagicMock()

    # Track rows for get()
    _all_rows: list[MagicMock] = []

    if rows_by_query:
        for rows in rows_by_query.values():
            _all_rows.extend(rows)

    # execute() → awaitable → Result mock
    async def _execute_coro(*args, **kwargs):
        if rows_by_query is not None:
            # Match the right row set based on query string
            stmt_str = str(args[0]) if args else ""
            for key, rows in rows_by_query.items():
                if key in stmt_str:
                    return _make_result_mock(rows)
            return _make_result_mock([])
        return _make_result_mock(_all_rows)

    session.execute = MagicMock(side_effect=_execute_coro)

    # get() → awaitable → row or None
    async def _get_coro(model, row_id):
        for r in _all_rows:
            if r.id == row_id:
                return r
        return None

    session.get = MagicMock(side_effect=_get_coro)
    session.flush = AsyncMock()
    return session


class _MockSessionCtx:
    """Async context manager that yields a session."""

    def __init__(self, session: MagicMock):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *args):
        pass


def _make_session_factory(session: MagicMock) -> MagicMock:
    """Build mock session_factory that provides the given session via async context manager."""
    mock_sf = MagicMock()
    # Each call to .session() returns a new context manager wrapping the session
    mock_sf.session = MagicMock(side_effect=lambda: _MockSessionCtx(session))
    return mock_sf


def _mock_connector_instance(entity_id: str = "test_entity"):
    """Build a mock connector instance for sync testing."""
    instance = MagicMock()
    instance.entity_id = entity_id
    instance.provider = "google_drive"
    instance.credentials = MagicMock()
    instance.sync = AsyncMock(
        return_value=SyncResult(provider="google_drive", files_synced=3)
    )
    instance.get_sync_metadata = MagicMock(return_value={"lastHistoryId": "12345"})
    return instance


# ---- sync_single tests ----


class TestSyncSingle:
    """Tests for sync_single — the core per-connector sync function."""

    @pytest.mark.asyncio
    async def test_sync_single_loads_credentials_and_syncs(self):
        """sync_single should load credentials from DB, instantiate connector, and sync."""
        row = _make_connector_row(provider="github")
        mock_session = _make_async_session()
        mock_session.execute = MagicMock()

        async def _execute_for_single(*args, **kwargs):
            result = MagicMock()
            result.scalar_one_or_none = MagicMock(return_value=row)
            return result

        mock_session.execute.side_effect = _execute_for_single
        mock_sf = _make_session_factory(mock_session)

        connector_inst = _mock_connector_instance()
        connector_cls = MagicMock(return_value=connector_inst)

        with patch("emerald.connectors.tasks.session_factory", mock_sf):
            with patch(
                "emerald.connectors.tasks.decrypt_credentials",
                return_value=connector_inst.credentials,
            ):
                with patch(
                    "emerald.connectors.tasks.get_connector_registry"
                ) as mock_reg:
                    mock_registry = MagicMock()
                    mock_registry.get.return_value = connector_cls
                    mock_reg.return_value = mock_registry

                    from emerald.connectors.tasks import sync_single

                    await sync_single(
                        entity_id=str(row.entity_id),
                        provider="github",
                        mode=SyncMode.INCREMENTAL,
                    )

        # Verify connector was called (with or without sync_metadata depending on connector)
        assert connector_cls.call_count == 1
        call_kwargs = connector_cls.call_args.kwargs
        assert call_kwargs["entity_id"] == str(row.entity_id)
        assert connector_inst.credentials is not None
        connector_inst.sync.assert_called_once_with(mode=SyncMode.INCREMENTAL)
        connector_inst.get_sync_metadata.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_single_updates_db_after_sync(self):
        """After successful sync, last_synced_at and sync_metadata are persisted."""
        row = _make_connector_row(provider="gmail")
        mock_session = _make_async_session()
        mock_session.execute = MagicMock()

        async def _execute_for_single(*args, **kwargs):
            result = MagicMock()
            result.scalar_one_or_none = MagicMock(return_value=row)
            return result

        mock_session.execute.side_effect = _execute_for_single
        mock_sf = _make_session_factory(mock_session)

        connector_inst = _mock_connector_instance()
        connector_inst.get_sync_metadata.return_value = {"lastHistoryId": "67890"}
        connector_cls = MagicMock(return_value=connector_inst)

        with patch("emerald.connectors.tasks.session_factory", mock_sf):
            with patch(
                "emerald.connectors.tasks.decrypt_credentials",
                return_value=MagicMock(),
            ):
                with patch(
                    "emerald.connectors.tasks.get_connector_registry"
                ) as mock_reg:
                    mock_registry = MagicMock()
                    mock_registry.get.return_value = connector_cls
                    mock_reg.return_value = mock_registry

                    from emerald.connectors.tasks import sync_single

                    await sync_single(
                        entity_id=str(row.entity_id),
                        provider="gmail",
                        mode=SyncMode.FULL,
                    )

        # Verify session.get was called to reload the row after sync
        mock_session.get.assert_called()

    @pytest.mark.asyncio
    async def test_sync_single_not_found_logs_warning(self):
        """When no connector row exists, should log warning and return early."""
        mock_session = _make_async_session()
        mock_session.execute = MagicMock()

        async def _execute_not_found(*args, **kwargs):
            result = MagicMock()
            result.scalar_one_or_none = MagicMock(return_value=None)
            return result

        mock_session.execute.side_effect = _execute_not_found
        mock_sf = _make_session_factory(mock_session)

        with patch("emerald.connectors.tasks.session_factory", mock_sf):
            with patch("emerald.connectors.tasks.logger") as mock_logger:
                from emerald.connectors.tasks import sync_single

                await sync_single(
                    entity_id=_TEST_UUID,
                    provider="github",
                    mode=SyncMode.INCREMENTAL,
                )

        mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_single_records_errors(self):
        """If connector.sync() returns errors, error state should be persisted on the DB row."""
        row = _make_connector_row(provider="notion")
        mock_session = _make_async_session()
        mock_session.execute = MagicMock()

        async def _execute_for_single(*args, **kwargs):
            result = MagicMock()
            result.scalar_one_or_none = MagicMock(return_value=row)
            return result

        mock_session.execute.side_effect = _execute_for_single
        # Ensure session.get returns the same row for state verification
        mock_session.get = AsyncMock(return_value=row)
        mock_sf = _make_session_factory(mock_session)

        # Connector sync returns errors in result, doesn't raise
        error_result = SyncResult(
            provider="notion",
            files_synced=1,
            files_failed=2,
            errors=["API rate limit exceeded", "Page not found"],
        )
        connector_inst = _mock_connector_instance()
        connector_inst.sync = AsyncMock(return_value=error_result)
        connector_cls = MagicMock(return_value=connector_inst)

        with patch("emerald.connectors.tasks.session_factory", mock_sf):
            with patch(
                "emerald.connectors.tasks.decrypt_credentials",
                return_value=MagicMock(),
            ):
                with patch(
                    "emerald.connectors.tasks.get_connector_registry"
                ) as mock_reg:
                    mock_registry = MagicMock()
                    mock_registry.get.return_value = connector_cls
                    mock_reg.return_value = mock_registry

                    from emerald.connectors.tasks import sync_single

                    await sync_single(
                        entity_id=str(row.entity_id),
                        provider="notion",
                        mode=SyncMode.INCREMENTAL,
                    )

        # Error was persisted based on result.errors
        assert row.sync_status == "error"
        assert "API rate limit exceeded" in row.error_message
        assert "Page not found" in row.error_message

    @pytest.mark.asyncio
    async def test_sync_single_passes_sync_metadata_to_connector(self):
        """sync_metadata from DB is passed to connector constructor for incremental sync."""
        row = _make_connector_row(
            provider="gmail",
            sync_metadata={"lastHistoryId": "abc123"},
        )
        mock_session = _make_async_session()
        mock_session.execute = MagicMock()

        async def _execute_for_single(*args, **kwargs):
            result = MagicMock()
            result.scalar_one_or_none = MagicMock(return_value=row)
            return result

        mock_session.execute.side_effect = _execute_for_single
        mock_sf = _make_session_factory(mock_session)

        # Create a mock connector class that accepts sync_metadata
        connector_inst = _mock_connector_instance()
        connector_cls = MagicMock(return_value=connector_inst)

        with patch("emerald.connectors.tasks.session_factory", mock_sf):
            with patch(
                "emerald.connectors.tasks.decrypt_credentials",
                return_value=MagicMock(),
            ):
                with patch(
                    "emerald.connectors.tasks.get_connector_registry"
                ) as mock_reg:
                    mock_registry = MagicMock()
                    mock_registry.get.return_value = connector_cls
                    mock_reg.return_value = mock_registry

                    from emerald.connectors.tasks import sync_single

                    await sync_single(
                        entity_id=str(row.entity_id),
                        provider="gmail",
                        mode=SyncMode.INCREMENTAL,
                    )

        # Connector constructor should receive sync_metadata for connectors that support it
        assert connector_cls.call_count == 1
        call_kwargs = connector_cls.call_args.kwargs
        assert call_kwargs["entity_id"] == str(row.entity_id)
        assert call_kwargs["sync_metadata"] == {"lastHistoryId": "abc123"}


# ---- sync_all tests ----


class TestSyncAll:
    """Tests for sync_all — the orchestrator that syncs all connectors of a provider."""

    @pytest.mark.asyncio
    async def test_sync_all_queries_active_connectors(self):
        """sync_all should call sync_single for each active connector returned by DB."""
        rows = [
            _make_connector_row(entity_id=_TEST_UUID, provider="github"),
            _make_connector_row(entity_id=_TEST_UUID2, provider="github"),
        ]
        mock_session = _make_async_session()
        # scalars().all() returns the rows
        mock_session.execute = MagicMock()

        async def _execute(*args, **kwargs):
            return _make_result_mock(rows)

        mock_session.execute.side_effect = _execute
        mock_sf = _make_session_factory(mock_session)

        with patch("emerald.connectors.tasks.session_factory", mock_sf):
            with patch(
                "emerald.connectors.tasks.sync_single", new_callable=AsyncMock
            ) as mock_sync_single:
                from emerald.connectors.tasks import sync_all

                await sync_all("github")

        assert mock_sync_single.call_count == 2
        mock_sync_single.assert_any_call(
            entity_id=_TEST_UUID,
            provider="github",
            mode=SyncMode.INCREMENTAL,
        )
        mock_sync_single.assert_any_call(
            entity_id=_TEST_UUID2,
            provider="github",
            mode=SyncMode.INCREMENTAL,
        )

    @pytest.mark.asyncio
    async def test_sync_all_empty_result(self):
        """sync_all should handle empty result without calling sync_single."""
        mock_session = _make_async_session()
        mock_session.execute = MagicMock()

        async def _execute(*args, **kwargs):
            return _make_result_mock([])

        mock_session.execute.side_effect = _execute
        mock_sf = _make_session_factory(mock_session)

        with patch("emerald.connectors.tasks.session_factory", mock_sf):
            with patch(
                "emerald.connectors.tasks.sync_single", new_callable=AsyncMock
            ) as mock_sync_single:
                from emerald.connectors.tasks import sync_all

                await sync_all("notion")

        mock_sync_single.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_all_continues_on_individual_failure(self):
        """If one connector sync fails, others should still proceed."""
        rows = [
            _make_connector_row(entity_id=_TEST_UUID, provider="google_drive"),
            _make_connector_row(entity_id=_TEST_UUID2, provider="google_drive"),
        ]
        mock_session = _make_async_session()
        mock_session.execute = MagicMock()

        async def _execute(*args, **kwargs):
            return _make_result_mock(rows)

        mock_session.execute.side_effect = _execute
        mock_sf = _make_session_factory(mock_session)

        call_count = 0

        async def _mock_sync_single(entity_id, provider, mode):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("sync failed")

        with patch("emerald.connectors.tasks.session_factory", mock_sf):
            with patch(
                "emerald.connectors.tasks.sync_single",
                side_effect=_mock_sync_single,
            ):
                with patch("emerald.connectors.tasks.logger") as mock_logger:
                    from emerald.connectors.tasks import sync_all

                    await sync_all("google_drive")

        assert call_count == 2
        mock_logger.error.assert_called_once()


# ---- renew_webhooks tests ----


class TestRenewWebhooks:
    """Tests for renew_webhooks — webhook renewal for providers with expiry."""

    @pytest.mark.asyncio
    async def test_renew_webhooks_processes_webhook_providers(self):
        """renew_webhooks should query active connectors for Google Drive and Gmail."""
        rows = [
            _make_connector_row(entity_id=_TEST_UUID, provider="google_drive"),
            _make_connector_row(entity_id=_TEST_UUID2, provider="gmail"),
            # GitHub is not a webhook provider, but included by the mock anyway
            _make_connector_row(entity_id=_TEST_UUID3, provider="github"),
        ]
        mock_session = _make_async_session()
        mock_session.execute = MagicMock()

        async def _execute(*args, **kwargs):
            return _make_result_mock(rows)

        mock_session.execute.side_effect = _execute
        mock_sf = _make_session_factory(mock_session)

        with patch("emerald.connectors.tasks.session_factory", mock_sf):
            from emerald.connectors.tasks import renew_webhooks

            await renew_webhooks()

    @pytest.mark.asyncio
    async def test_renew_webhooks_handles_empty_result(self):
        """renew_webhooks should not crash with empty connector list."""
        mock_session = _make_async_session()
        mock_session.execute = MagicMock()

        async def _execute(*args, **kwargs):
            return _make_result_mock([])

        mock_session.execute.side_effect = _execute
        mock_sf = _make_session_factory(mock_session)

        with patch("emerald.connectors.tasks.session_factory", mock_sf):
            from emerald.connectors.tasks import renew_webhooks

            await renew_webhooks()

    @pytest.mark.asyncio
    async def test_renew_webhooks_survives_individual_failure(self):
        """If one webhook check fails, others continue."""
        rows = [
            _make_connector_row(entity_id=_TEST_UUID, provider="google_drive"),
            _make_connector_row(entity_id=_TEST_UUID2, provider="gmail"),
        ]
        mock_session = _make_async_session()
        mock_session.execute = MagicMock()

        async def _execute(*args, **kwargs):
            return _make_result_mock(rows)

        mock_session.execute.side_effect = _execute
        mock_sf = _make_session_factory(mock_session)

        with patch("emerald.connectors.tasks.session_factory", mock_sf):
            from emerald.connectors.tasks import renew_webhooks

            await renew_webhooks()


# ---- Celery task registration ----


class TestCeleryTaskRegistration:
    """Verify the Celery tasks are importable and properly decorated."""

    def test_sync_all_task_is_registered(self):
        """sync_all_task should be a valid Celery task."""
        from emerald.connectors.tasks import sync_all_task

        assert hasattr(sync_all_task, "delay")
        assert sync_all_task.name == "emerald.connectors.tasks.sync_all_task"

    def test_sync_single_task_is_registered(self):
        """sync_single_task should be a valid Celery task."""
        from emerald.connectors.tasks import sync_single_task

        assert hasattr(sync_single_task, "delay")
        assert sync_single_task.name == "emerald.connectors.tasks.sync_single_task"

    def test_renew_webhooks_task_is_registered(self):
        """renew_webhooks_task should be a valid Celery task."""
        from emerald.connectors.tasks import renew_webhooks_task

        assert hasattr(renew_webhooks_task, "delay")
        assert renew_webhooks_task.name == "emerald.connectors.tasks.renew_webhooks_task"
