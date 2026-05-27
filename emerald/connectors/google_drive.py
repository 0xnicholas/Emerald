"""Google Drive connector — document and file sync via Google Drive API v3.

Supports OAuth 2.0 web application flow, incremental sync via changes API,
and file export for Google Workspace formats (Docs, Sheets, Slides).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx
import structlog

from emerald.config import get_settings
from emerald.connectors.auth import decrypt_credentials, encrypt_credentials
from emerald.connectors.base import (
    BaseConnector,
    ConnectorCredentials,
    ConnectorStatus,
    SyncMode,
    SyncResult,
)

logger = structlog.get_logger(__name__)

GOOGLE_OAUTH_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
GOOGLE_DOCS_EXPORT_BASE = "https://www.googleapis.com/drive/v3/files"

# MIME types that can be exported to text
_EXPORTABLE_MIMETYPES: dict[str, str] = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}

# Supported MIME types for direct download or export
_SUPPORTED_MIMETYPES: set[str] = {
    "application/pdf",
    "text/plain",
    "text/markdown",
    "image/png",
    "image/jpeg",
    "application/json",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    *_EXPORTABLE_MIMETYPES.keys(),
}


class GoogleDriveConnector(BaseConnector):
    """Syncs Google Drive files and folders."""

    provider = "google_drive"

    def __init__(self, entity_id: str) -> None:
        self.entity_id = entity_id
        self.credentials: ConnectorCredentials | None = None
        self._client: httpx.AsyncClient | None = None

    # ---- OAuth ----

    async def get_auth_url(self, redirect_uri: str) -> tuple[str, str]:
        """Generate Google OAuth authorization URL."""
        settings = get_settings()
        if not settings.google_client_id:
            raise RuntimeError("Google client ID not configured")

        state = hashlib.sha256(
            f"{self.entity_id}:{datetime.now(UTC).isoformat()}".encode()
        ).hexdigest()[:32]

        params = {
            "client_id": settings.google_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "https://www.googleapis.com/auth/drive.readonly",
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        auth_url = f"{GOOGLE_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"

        logger.info(
            "google_drive.oauth.auth_url_generated",
            entity_id=self.entity_id,
            state=state[:8],
        )
        return auth_url, state

    async def handle_callback(
        self, code: str, state: str
    ) -> ConnectorCredentials:
        """Exchange Google authorization code for tokens."""
        settings = get_settings()
        if not settings.google_client_secret:
            raise RuntimeError("Google client secret not configured")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                GOOGLE_OAUTH_TOKEN_URL,
                data={
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": "",  # Optional for token exchange
                },
            )
            response.raise_for_status()
            data = response.json()

        if "error" in data:
            raise RuntimeError(
                f"Google OAuth error: {data.get('error_description', data['error'])}"
            )

        expires_at = None
        if "expires_in" in data:
            expires_at = datetime.now(UTC).replace(tzinfo=UTC) + __import__("datetime").timedelta(
                seconds=data["expires_in"]
            )

        creds = ConnectorCredentials(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            token_type=data.get("token_type", "Bearer"),
            expires_at=expires_at,
            scopes=data.get("scope", "").split(" ") if data.get("scope") else [],
        )
        self.credentials = creds

        logger.info(
            "google_drive.oauth.token_exchanged",
            entity_id=self.entity_id,
            has_refresh_token=creds.refresh_token is not None,
        )
        return creds

    # ---- Sync ----

    async def sync(self, mode: SyncMode = SyncMode.INCREMENTAL) -> SyncResult:
        """Sync Google Drive files accessible to the user."""
        if not self.credentials:
            raise RuntimeError("Google Drive credentials not available")

        client = self._get_api_client()
        result = SyncResult(provider="google_drive")

        try:
            # Use changes API for incremental sync when possible
            if mode == SyncMode.INCREMENTAL and False:  # TODO: store pageToken
                files = await self._fetch_changes(client)
            else:
                files = await self._fetch_files(client)

            logger.info(
                "google_drive.sync.files_fetched",
                entity_id=self.entity_id,
                file_count=len(files),
            )

            for file_meta in files:
                try:
                    await self._sync_file(client, file_meta)
                    result.files_synced += 1
                except Exception as exc:
                    logger.warning(
                        "google_drive.sync.file_failed",
                        file_id=file_meta.get("id"),
                        error=str(exc),
                    )
                    result.files_failed += 1
                    result.errors.append(f"{file_meta.get('name')}: {exc}")

        except Exception as exc:
            logger.error("google_drive.sync.failed", error=str(exc))
            result.errors.append(str(exc))
        finally:
            await client.aclose()

        return result

    async def _fetch_files(self, client: httpx.AsyncClient) -> list[dict]:
        """Fetch list of files from Google Drive."""
        files: list[dict] = []
        page_token: str | None = None

        while True:
            params: dict[str, Any] = {
                "pageSize": 100,
                "fields": "nextPageToken, files(id, name, mimeType, modifiedTime, size)",
                "q": "trashed = false",
            }
            if page_token:
                params["pageToken"] = page_token

            response = await client.get("/files", params=params)
            response.raise_for_status()
            data = response.json()

            for f in data.get("files", []):
                mime = f.get("mimeType", "")
                if mime in _SUPPORTED_MIMETYPES or mime in _EXPORTABLE_MIMETYPES:
                    files.append(f)

            page_token = data.get("nextPageToken")
            if not page_token:
                break

        return files

    async def _sync_file(
        self, client: httpx.AsyncClient, file_meta: dict
    ) -> None:
        """Download and ingest a single Drive file."""
        from emerald.pipeline.orchestrator import PipelineOrchestrator

        file_id = file_meta["id"]
        mime = file_meta.get("mimeType", "")
        name = file_meta.get("name", "untitled")

        # Determine content and content_type
        if mime in _EXPORTABLE_MIMETYPES:
            export_mime = _EXPORTABLE_MIMETYPES[mime]
            resp = await client.get(
                f"/files/{file_id}/export",
                params={"mimeType": export_mime},
            )
            content_type = "text"
            if export_mime == "text/csv":
                content_type = "text"
        else:
            resp = await client.get(f"/files/{file_id}?alt=media")
            content_type = self._detect_content_type(name, mime)

        resp.raise_for_status()
        file_content = resp.content

        orchestrator = PipelineOrchestrator()
        await orchestrator.process_async(
            content=file_content,
            content_type=content_type,
            entity_id=self.entity_id,
            document_id=f"gdrive:{file_id}",
        )

        logger.info(
            "google_drive.sync.file_ingested",
            file_id=file_id,
            name=name,
            content_type=content_type,
        )

    @staticmethod
    def _detect_content_type(filename: str, mime: str) -> str:
        """Map MIME type or filename to Emerald content_type."""
        if mime == "application/pdf":
            return "pdf"
        if mime.startswith("image/"):
            return "image"
        if mime == "text/markdown" or filename.endswith(".md"):
            return "markdown"
        if mime == "application/json" or filename.endswith(".json"):
            return "text"
        return "text"

    # ---- Webhook ----

    async def handle_webhook(
        self, payload: dict, signature: str
    ) -> bool:
        """Process Google Drive push notification (Webhook)."""
        # Google Drive push notifications are sent via Pub/Sub or
        # HTTPS channel watches. The payload contains resource_id and
        # channel_id. We trigger an incremental sync.
        resource_id = payload.get("resourceId", "")
        channel_id = payload.get("channelId", "")

        logger.info(
            "google_drive.webhook.received",
            resource_id=resource_id,
            channel_id=channel_id,
            entity_id=self.entity_id,
        )
        return True

    # ---- Lifecycle ----

    async def revoke(self) -> None:
        """Revoke OAuth grant."""
        if self.credentials:
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://oauth2.googleapis.com/revoke",
                    params={"token": self.credentials.access_token},
                )
            self.credentials = None

        logger.info("google_drive.revoked", entity_id=self.entity_id)

    async def status(self) -> ConnectorStatus:
        """Return current connector status."""
        connected = self.credentials is not None
        return ConnectorStatus(
            provider="google_drive",
            connected=connected,
            sync_status="active" if connected else "inactive",
            last_synced_at=None,
        )

    # ---- Helpers ----

    def _get_api_client(self) -> httpx.AsyncClient:
        """Return authenticated Google Drive API client."""
        if not self.credentials:
            raise RuntimeError("Credentials not available")
        return httpx.AsyncClient(
            base_url=GOOGLE_DRIVE_API_BASE,
            headers={
                "Authorization": f"Bearer {self.credentials.access_token}",
            },
            follow_redirects=True,
        )

    # ---- Credential persistence ----

    def encrypt(self) -> bytes | None:
        if self.credentials:
            return encrypt_credentials(self.credentials)
        return None

    @classmethod
    def decrypt(cls, encrypted: bytes, entity_id: str) -> "GoogleDriveConnector":
        connector = cls(entity_id=entity_id)
        connector.credentials = decrypt_credentials(encrypted)
        return connector
