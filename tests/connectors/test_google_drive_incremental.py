"""Tests for Google Drive incremental sync via changes API."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from emerald.connectors.base import SyncMode, SyncResult


class TestGoogleDriveIncrementalSync:
    """Tests for Google Drive connector incremental sync and sync_metadata support."""

    @pytest.mark.asyncio
    async def test_init_accepts_sync_metadata(self):
        """GoogleDriveConnector should accept sync_metadata in constructor."""
        from emerald.connectors.google_drive import GoogleDriveConnector

        meta = {"pageToken": "abc123", "last_synced_at": "2026-01-01T00:00:00Z"}
        connector = GoogleDriveConnector(entity_id="user_123", sync_metadata=meta)
        assert connector.entity_id == "user_123"
        assert connector._sync_metadata_in == meta

    @pytest.mark.asyncio
    async def test_init_defaults_sync_metadata_to_none(self):
        """sync_metadata should default to None."""
        from emerald.connectors.google_drive import GoogleDriveConnector

        connector = GoogleDriveConnector(entity_id="user_123")
        assert connector._sync_metadata_in is None

    @pytest.mark.asyncio
    async def test_get_sync_metadata_returns_none_before_sync(self):
        """get_sync_metadata should return None before any sync runs."""
        from emerald.connectors.google_drive import GoogleDriveConnector

        connector = GoogleDriveConnector(entity_id="user_123")
        assert connector.get_sync_metadata() is None

    @pytest.mark.asyncio
    async def test_get_sync_metadata_returns_page_token_after_sync(self, monkeypatch):
        """After a sync, get_sync_metadata should return the updated pageToken."""
        from emerald.connectors.google_drive import GoogleDriveConnector
        from emerald.connectors.base import ConnectorCredentials

        monkeypatch.setenv("GOOGLE_CLIENT_ID", "test_id")
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test_secret")
        from emerald.config import get_settings
        get_settings.cache_clear()

        connector = GoogleDriveConnector(entity_id="user_123")
        connector.credentials = ConnectorCredentials(access_token="test_token")

        # Mock the API to return files (no pagination)
        mock_response_files = MagicMock()
        mock_response_files.status_code = 200
        mock_response_files.json.return_value = {
            "files": [
                {
                    "id": "file_1",
                    "name": "test.txt",
                    "mimeType": "text/plain",
                    "modifiedTime": "2026-05-27T10:00:00Z",
                    "size": "100",
                },
            ],
            # No nextPageToken → single page
        }
        mock_response_files.raise_for_status = MagicMock()

        # Also mock file content download
        mock_response_download = MagicMock()
        mock_response_download.status_code = 200
        mock_response_download.content = b"test content"
        mock_response_download.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            # First call: list files, second call: download file
            mock_get.side_effect = [mock_response_files, mock_response_download]

            with patch(
                "emerald.pipeline.orchestrator.PipelineOrchestrator"
            ) as mock_orch_cls:
                mock_orch = MagicMock()
                mock_orch.process_async = AsyncMock()
                mock_orch_cls.return_value = mock_orch

                result = await connector.sync(mode=SyncMode.FULL)

        # Should have synced 1 file
        assert result.files_synced == 1
        # get_sync_metadata should contain last_synced_at (no pageToken for single-page full sync)
        out = connector.get_sync_metadata()
        assert out is not None
        assert "last_synced_at" in out

    @pytest.mark.asyncio
    async def test_incremental_sync_uses_changes_api(self, monkeypatch):
        """Incremental sync should use the changes API with the stored pageToken."""
        from emerald.connectors.google_drive import GoogleDriveConnector
        from emerald.connectors.base import ConnectorCredentials

        monkeypatch.setenv("GOOGLE_CLIENT_ID", "test_id")
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test_secret")
        from emerald.config import get_settings
        get_settings.cache_clear()

        connector = GoogleDriveConnector(
            entity_id="user_123",
            sync_metadata={"pageToken": "stored_token_42"},
        )
        connector.credentials = ConnectorCredentials(access_token="test_token")

        # Mock changes API response
        mock_changes = MagicMock()
        mock_changes.status_code = 200
        mock_changes.json.return_value = {
            "changes": [
                {
                    "fileId": "changed_file_1",
                    "file": {
                        "id": "changed_file_1",
                        "name": "updated.txt",
                        "mimeType": "text/plain",
                        "modifiedTime": "2026-05-27T12:00:00Z",
                    },
                },
            ],
            "newStartPageToken": "new_token_99",
            "nextPageToken": None,
        }
        mock_changes.raise_for_status = MagicMock()

        # Mock file download
        mock_download = MagicMock()
        mock_download.status_code = 200
        mock_download.content = b"updated content"
        mock_download.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = [mock_changes, mock_download]

            with patch(
                "emerald.pipeline.orchestrator.PipelineOrchestrator"
            ) as mock_orch_cls:
                mock_orch = MagicMock()
                mock_orch.process_async = AsyncMock()
                mock_orch_cls.return_value = mock_orch

                result = await connector.sync(mode=SyncMode.INCREMENTAL)

        # Should have synced the changed file
        assert result.files_synced == 1
        # Verify changes API was called with the stored pageToken
        # Check that the first get call had pageToken in params
        first_call_args = mock_get.call_args_list[0]
        params = first_call_args.kwargs.get("params", {})
        assert params.get("pageToken") == "stored_token_42"
        # Updated pageToken should be stored
        out = connector.get_sync_metadata()
        assert out is not None
        assert out["pageToken"] == "new_token_99"

    @pytest.mark.asyncio
    async def test_incremental_falls_back_to_full_when_no_page_token(self, monkeypatch):
        """When sync_metadata has no pageToken, fall back to full sync."""
        from emerald.connectors.google_drive import GoogleDriveConnector
        from emerald.connectors.base import ConnectorCredentials

        monkeypatch.setenv("GOOGLE_CLIENT_ID", "test_id")
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test_secret")
        from emerald.config import get_settings
        get_settings.cache_clear()

        connector = GoogleDriveConnector(
            entity_id="user_123",
            sync_metadata={"last_synced_at": "2026-05-20"},
        )
        connector.credentials = ConnectorCredentials(access_token="test_token")

        # Mock files list (full sync path)
        mock_files = MagicMock()
        mock_files.status_code = 200
        mock_files.json.return_value = {
            "files": [
                {
                    "id": "file_1",
                    "name": "doc.txt",
                    "mimeType": "text/plain",
                    "modifiedTime": "2026-05-27T10:00:00Z",
                    "size": "50",
                },
            ],
            "nextPageToken": None,
        }
        mock_files.raise_for_status = MagicMock()

        mock_download = MagicMock()
        mock_download.status_code = 200
        mock_download.content = b"content"
        mock_download.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = [mock_files, mock_download]

            with patch(
                "emerald.pipeline.orchestrator.PipelineOrchestrator"
            ) as mock_orch_cls:
                mock_orch = MagicMock()
                mock_orch.process_async = AsyncMock()
                mock_orch_cls.return_value = mock_orch

                result = await connector.sync(mode=SyncMode.INCREMENTAL)

        # Should still work (full sync fallback)
        assert result.files_synced == 1
        # First call should be to /files (full sync), not /changes
        first_url = mock_get.call_args_list[0].args[0]
        assert "/files" in first_url
        assert "/changes" not in first_url
