"""Gmail connector — email sync via Google OAuth and Gmail API v1."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import html as html_module
import re
from datetime import UTC, datetime, timedelta
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
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1"


class GmailConnector(BaseConnector):
    """Syncs emails from Gmail via Google OAuth and Gmail API."""

    provider = "gmail"

    def __init__(self, entity_id: str, sync_metadata: dict | None = None) -> None:
        self.entity_id = entity_id
        self.credentials: ConnectorCredentials | None = None
        self._client: httpx.AsyncClient | None = None
        self._sync_metadata_in: dict | None = sync_metadata
        self._sync_metadata_out: dict | None = None  # Set after sync for caller to persist

    # ---- OAuth ----

    async def get_auth_url(self, redirect_uri: str) -> tuple[str, str]:
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
            "scope": "https://www.googleapis.com/auth/gmail.readonly",
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        auth_url = f"{GOOGLE_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"
        logger.info("gmail.oauth.auth_url_generated", entity_id=self.entity_id, state=state[:8])
        return auth_url, state

    async def handle_callback(self, code: str, state: str) -> ConnectorCredentials:
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
                    "redirect_uri": "",
                },
            )
            response.raise_for_status()
            data = response.json()

        if "error" in data:
            raise RuntimeError(f"Google OAuth error: {data.get('error_description', data['error'])}")

        expires_at = None
        if "expires_in" in data:
            expires_at = datetime.now(UTC) + timedelta(seconds=data["expires_in"])

        creds = ConnectorCredentials(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            token_type=data.get("token_type", "Bearer"),
            expires_at=expires_at,
            scopes=data.get("scope", "").split(" ") if data.get("scope") else [],
        )
        self.credentials = creds
        logger.info("gmail.oauth.token_exchanged", entity_id=self.entity_id)
        return creds

    # ---- Body Extraction ----

    @staticmethod
    def _extract_html_to_text(html: str) -> str:
        """Convert HTML email body to plain text using regex."""
        if not html:
            return ""
        text = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
        text = re.sub(r'</?(p|div|tr|h[1-6]|li)[^>]*>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'<[^>]+>', '', text)
        text = html_module.unescape(text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    @staticmethod
    def _extract_email_body(payload: dict) -> str | None:
        """Extract plain text body from a Gmail message payload (recursive for multipart)."""
        mime = payload.get("mimeType", "")

        # Single-part message
        if mime == "text/plain":
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            return None

        if mime == "text/html":
            data = payload.get("body", {}).get("data", "")
            if data:
                html = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                return GmailConnector._extract_html_to_text(html)
            return None

        # Multipart message
        parts = payload.get("parts", [])
        if not parts:
            return None

        # Prefer text/plain over text/html
        for part in parts:
            result = GmailConnector._extract_email_body(part)
            if result and part.get("mimeType") == "text/plain":
                return result

        # Fallback to first text/html
        for part in parts:
            result = GmailConnector._extract_email_body(part)
            if result:
                return result

        return None

    # ---- Sync ----

    async def sync(self, mode: SyncMode = SyncMode.INCREMENTAL) -> SyncResult:
        if not self.credentials:
            raise RuntimeError("Gmail credentials not available")

        client = self._get_api_client()
        result = SyncResult(provider="gmail")
        new_history_id: str | None = None

        try:
            if mode == SyncMode.INCREMENTAL:
                new_history_id = await self._sync_incremental(client, result)
            else:
                new_history_id = await self._sync_full(client, result)

            # Persist historyId for caller to store in DB
            if new_history_id:
                self._sync_metadata_out = {"lastHistoryId": new_history_id}
        except Exception as exc:
            logger.error("gmail.sync.failed", error=str(exc))
            result.errors.append(str(exc))
        finally:
            await client.aclose()

        return result

    def get_sync_metadata(self) -> dict | None:
        """Return updated sync metadata for persistence after sync completes."""
        return self._sync_metadata_out

    async def _sync_full(self, client: httpx.AsyncClient, result: SyncResult) -> str | None:
        """Full sync — last 30 days of messages. Returns the latest historyId."""
        page_token: str | None = None
        processed_ids: set[str] = set()

        while True:
            params: dict[str, Any] = {
                "maxResults": 100,
                "q": "newer_than:30d",
            }
            if page_token:
                params["pageToken"] = page_token

            response = await client.get("/users/me/messages", params=params)
            response.raise_for_status()
            data = response.json()

            for msg in data.get("messages", []):
                msg_id = msg["id"]
                if msg_id in processed_ids:
                    continue
                processed_ids.add(msg_id)

                try:
                    synced = await self._sync_message(client, msg_id)
                    if synced:
                        result.files_synced += 1
                    else:
                        result.files_skipped += 1
                except Exception as exc:
                    logger.warning("gmail.sync.message_failed", msg_id=msg_id, error=str(exc))
                    result.files_failed += 1
                    result.errors.append(f"msg {msg_id}: {exc}")

                await _rate_limit_sleep()

            page_token = data.get("nextPageToken")
            if not page_token:
                break

        # Capture historyId AFTER sync completes, so we don't miss
        # messages that arrived during a long sync.
        profile_resp = await client.get("/users/me/profile")
        profile_resp.raise_for_status()
        latest_history_id = str(profile_resp.json().get("historyId", ""))

        logger.info("gmail.sync.full_complete", entity_id=self.entity_id, synced=result.files_synced)
        return latest_history_id

    # Note: processed_ids is session-local dedup. Cross-session dedup happens at
    # the pipeline layer via document_id ("gmail:{messageId}").

    async def _sync_incremental(self, client: httpx.AsyncClient, result: SyncResult) -> str | None:
        """Incremental sync — changes since last historyId. Returns updated historyId."""
        last_history_id = (self._sync_metadata_in or {}).get("lastHistoryId")
        if not last_history_id:
            logger.info("gmail.sync.no_history_id_fallback", entity_id=self.entity_id)
            return await self._sync_full(client, result)

        page_token: str | None = None
        while True:
            params: dict[str, Any] = {"startHistoryId": last_history_id, "maxResults": 100}
            if page_token:
                params["pageToken"] = page_token

            response = await client.get("/users/me/history", params=params)
            response.raise_for_status()
            data = response.json()

            for history_item in data.get("history", []):
                for msg_added in history_item.get("messagesAdded", []):
                    msg_id = msg_added["message"]["id"]
                    try:
                        synced = await self._sync_message(client, msg_id)
                        if synced:
                            result.files_synced += 1
                    except Exception as exc:
                        logger.warning("gmail.sync.message_failed", msg_id=msg_id, error=str(exc))
                        result.files_failed += 1
                        result.errors.append(f"msg {msg_id}: {exc}")

                    await _rate_limit_sleep()

            if data.get("historyId"):
                last_history_id = data["historyId"]

            page_token = data.get("nextPageToken")
            if not page_token:
                break

        logger.info("gmail.sync.incremental_complete", entity_id=self.entity_id, synced=result.files_synced)
        return last_history_id

    async def _sync_message(self, client: httpx.AsyncClient, msg_id: str) -> bool:
        """Fetch and ingest a single email. Returns True if ingested."""
        from emerald.pipeline.orchestrator import PipelineOrchestrator

        response = await client.get(f"/users/me/messages/{msg_id}", params={"format": "full"})
        response.raise_for_status()
        msg = response.json()

        body = self._extract_email_body(msg.get("payload", {}))
        if not body:
            return False

        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        metadata = {
            "subject": headers.get("subject", "(no subject)"),
            "participants": headers.get("from", ""),
            "thread_id": msg.get("threadId", ""),
            "labels": msg.get("labelIds", []),
        }

        orchestrator = PipelineOrchestrator()
        await orchestrator.process_async(
            content=body.encode("utf-8") if isinstance(body, str) else body,
            content_type="text",
            entity_id=self.entity_id,
            document_id=f"gmail:{msg_id}",
            metadata=metadata,
        )
        return True

    # ---- Webhook ----

    async def handle_webhook(self, payload: dict, signature: str) -> bool:
        return False

    # ---- Lifecycle ----

    async def revoke(self) -> None:
        if self.credentials:
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://oauth2.googleapis.com/revoke",
                    params={"token": self.credentials.access_token},
                )
            self.credentials = None
        logger.info("gmail.revoked", entity_id=self.entity_id)

    async def status(self) -> ConnectorStatus:
        connected = self.credentials is not None
        return ConnectorStatus(
            provider="gmail",
            connected=connected,
            sync_status="active" if connected else "inactive",
            last_synced_at=None,
        )

    # ---- Helpers ----

    def _get_api_client(self) -> httpx.AsyncClient:
        if not self.credentials:
            raise RuntimeError("Credentials not available")
        return httpx.AsyncClient(
            base_url=GMAIL_API_BASE,
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
    def decrypt(cls, encrypted: bytes, entity_id: str) -> "GmailConnector":
        connector = cls(entity_id=entity_id)
        connector.credentials = decrypt_credentials(encrypted)
        return connector


async def _rate_limit_sleep():
    await asyncio.sleep(0.2)
