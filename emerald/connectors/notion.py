"""Notion connector — page and database sync via Notion OAuth."""

from __future__ import annotations

import asyncio
import base64
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

NOTION_OAUTH_AUTHORIZE_URL = "https://api.notion.com/v1/oauth/authorize"
NOTION_OAUTH_TOKEN_URL = "https://api.notion.com/v1/oauth/token"
NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

_TEXT_BLOCK_TYPES = frozenset({
    "paragraph", "heading_1", "heading_2", "heading_3",
    "bulleted_list_item", "numbered_list_item", "toggle",
    "quote", "callout",
})

_CONTAINER_BLOCK_TYPES = frozenset({
    "table", "column_list", "column", "synced_block",
})

_SKIP_BLOCK_TYPES = frozenset({
    "divider", "table_of_contents", "breadcrumb", "link_preview",
    "link_to_page", "template", "embed", "bookmark",
    "image", "file", "video", "pdf",
})


class NotionConnector(BaseConnector):
    """Syncs Notion pages and databases via Notion OAuth."""

    provider = "notion"

    def __init__(self, entity_id: str, sync_metadata: dict | None = None) -> None:
        self.entity_id = entity_id
        self.credentials: ConnectorCredentials | None = None
        self._client: httpx.AsyncClient | None = None
        self._sync_metadata_in: dict | None = sync_metadata
        self._sync_metadata_out: dict | None = None

    # ---- OAuth ----

    async def get_auth_url(self, redirect_uri: str) -> tuple[str, str]:
        settings = get_settings()
        if not settings.notion_client_id:
            raise RuntimeError("Notion client ID not configured")

        state = hashlib.sha256(
            f"{self.entity_id}:{datetime.now(UTC).isoformat()}".encode()
        ).hexdigest()[:32]

        params = {
            "client_id": settings.notion_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "owner": "user",
            "state": state,
        }
        auth_url = f"{NOTION_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"
        logger.info("notion.oauth.auth_url_generated", entity_id=self.entity_id, state=state[:8])
        return auth_url, state

    async def handle_callback(self, code: str, state: str, redirect_uri: str = "") -> ConnectorCredentials:
        settings = get_settings()
        if not settings.notion_client_secret:
            raise RuntimeError("Notion client secret not configured")

        import base64 as _base64
        auth_header = base64.b64encode(
            f"{settings.notion_client_id}:{settings.notion_client_secret}".encode()
        ).decode()

        async with httpx.AsyncClient() as client:
            response = await client.post(
                NOTION_OAUTH_TOKEN_URL,
                headers={
                    "Authorization": f"Basic {auth_header}",
                    "Content-Type": "application/json",
                },
                json={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
            )
            response.raise_for_status()
            data = response.json()

        if "error" in data:
            raise RuntimeError(f"Notion OAuth error: {data.get('error_description', data['error'])}")

        creds = ConnectorCredentials(
            access_token=data["access_token"],
            token_type=data.get("token_type", "Bearer"),
            scopes=[],
        )
        self.credentials = creds

        self._workspace_name = data.get("workspace_name", "")
        self._workspace_id = data.get("workspace_id", "")

        logger.info(
            "notion.oauth.token_exchanged",
            entity_id=self.entity_id,
            workspace=self._workspace_name,
        )
        return creds

    # ---- Rich Text / Block Extraction ----

    @staticmethod
    def _extract_rich_text(rich_text: list[dict]) -> str:
        return "".join(t.get("plain_text", "") for t in rich_text)

    @staticmethod
    def _get_block_text(block: dict) -> str:
        block_type = block.get("type", "")
        block_data = block.get(block_type, {})

        if block_type in _TEXT_BLOCK_TYPES:
            text = NotionConnector._extract_rich_text(block_data.get("rich_text", []))
            if not text:
                return ""
            if block_type.startswith("heading_"):
                level = int(block_type.split("_")[1])
                return f"{'#' * level} {text}\n\n"
            if block_type == "bulleted_list_item":
                return f"- {text}\n"
            if block_type == "numbered_list_item":
                return f"1. {text}\n"
            return f"{text}\n\n"

        if block_type == "code":
            language = block_data.get("language", "")
            code_text = NotionConnector._extract_rich_text(block_data.get("rich_text", []))
            return f"```{language}\n{code_text}\n```\n\n"

        if block_type == "equation":
            return block_data.get("expression", "") + "\n"

        if block_type in ("child_page", "child_database"):
            return ""

        return ""

    # ---- Sync ----

    async def sync(self, mode: SyncMode = SyncMode.INCREMENTAL) -> SyncResult:
        if not self.credentials:
            raise RuntimeError("Notion credentials not available")

        client = self._get_api_client()
        result = SyncResult(provider="notion")

        incremental_since = None
        if mode == SyncMode.INCREMENTAL:
            incremental_since = (self._sync_metadata_in or {}).get("last_synced_at")

        try:
            cursor: str | None = None
            while True:
                body: dict[str, Any] = {
                    "page_size": 100,
                    "sort": {"direction": "descending", "timestamp": "last_edited_time"},
                }
                if cursor:
                    body["start_cursor"] = cursor

                response = await client.post("/search", json=body)
                if response.status_code == 429:
                    await _notion_rate_limit_sleep()
                    continue
                response.raise_for_status()
                data = response.json()

                for item in data.get("results", []):
                    if incremental_since and item.get("last_edited_time", "") <= incremental_since:
                        logger.info("notion.sync.incremental_caught_up", entity_id=self.entity_id)
                        self._sync_metadata_out = {"last_synced_at": datetime.now(UTC).isoformat()}
                        return result

                    try:
                        obj_type = item.get("object", "")
                        if obj_type == "page":
                            synced = await self._sync_page(client, item)
                        elif obj_type == "database":
                            synced = await self._sync_database(client, item)
                        else:
                            continue

                        if synced:
                            result.files_synced += 1
                    except Exception as exc:
                        logger.warning(
                            "notion.sync.item_failed",
                            item_id=item.get("id"),
                            error=str(exc),
                        )
                        result.files_failed += 1
                        result.errors.append(f"{item.get('id')}: {exc}")

                cursor = data.get("next_cursor")
                if not cursor:
                    break

            self._sync_metadata_out = {"last_synced_at": datetime.now(UTC).isoformat()}
            logger.info(
                "notion.sync.complete",
                entity_id=self.entity_id,
                synced=result.files_synced,
                failed=result.files_failed,
            )
        except Exception as exc:
            logger.error("notion.sync.failed", error=str(exc))
            result.errors.append(str(exc))
        finally:
            await client.aclose()

        return result

    def get_sync_metadata(self) -> dict | None:
        return self._sync_metadata_out

    async def _sync_page(self, client: httpx.AsyncClient, page: dict) -> bool:
        from emerald.pipeline.orchestrator import PipelineOrchestrator

        page_id = page["id"]
        last_edited = page.get("last_edited_time", "")

        content = await self._extract_page_blocks(client, page_id, depth=0)

        if not content:
            return False

        title = _extract_page_title(page)

        metadata = {
            "title": title,
            "url": page.get("url", ""),
            "parent_type": page.get("parent", {}).get("type", ""),
            "last_edited_time": last_edited,
        }

        orchestrator = PipelineOrchestrator()
        await orchestrator.process_async(
            content=content.encode("utf-8"),
            content_type="text",
            entity_id=self.entity_id,
            document_id=f"notion:{page_id}",
            metadata=metadata,
        )
        return True

    async def _sync_database(self, client: httpx.AsyncClient, database: dict) -> bool:
        from emerald.pipeline.orchestrator import PipelineOrchestrator

        db_id = database["id"]
        db_title = _extract_page_title(database)
        orchestrator = PipelineOrchestrator()
        synced_any = False
        cursor: str | None = None

        while True:
            body: dict[str, Any] = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor

            response = await client.post(f"/databases/{db_id}/query", json=body)
            if response.status_code == 429:
                await _notion_rate_limit_sleep()
                continue
            response.raise_for_status()
            data = response.json()

            for row in data.get("results", []):
                row_id = row["id"]
                row_text = _extract_database_row(row)
                if not row_text:
                    continue

                await orchestrator.process_async(
                    content=row_text.encode("utf-8"),
                    content_type="text",
                    entity_id=self.entity_id,
                    document_id=f"notion:db:{db_id}:{row_id}",
                    metadata={"database_title": db_title, "database_id": db_id},
                )
                synced_any = True

            cursor = data.get("next_cursor")
            if not cursor:
                break

        return synced_any

    async def _extract_page_blocks(self, client: httpx.AsyncClient, block_id: str,
                                    depth: int = 0) -> str:
        if depth > 10:
            logger.warning("notion.extract.too_deep", block_id=block_id, depth=depth)
            return ""

        text_parts = []
        cursor: str | None = None

        while True:
            params: dict[str, Any] = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor

            response = await client.get(f"/blocks/{block_id}/children", params=params)
            if response.status_code == 429:
                await _notion_rate_limit_sleep()
                continue
            response.raise_for_status()
            data = response.json()

            for block in data.get("results", []):
                block_type = block.get("type", "")

                if block_type in _SKIP_BLOCK_TYPES:
                    continue

                if block_type in ("child_page", "child_database"):
                    child_id = block["id"]
                    child_text = await self._extract_page_blocks(client, child_id, depth + 1)
                    text_parts.append(child_text)
                    continue

                if block_type in _CONTAINER_BLOCK_TYPES:
                    if block.get("has_children", False):
                        child_text = await self._extract_page_blocks(client, block["id"], depth + 1)
                        text_parts.append(child_text)
                    continue

                block_text = self._get_block_text(block)
                text_parts.append(block_text)

            cursor = data.get("next_cursor")
            if not cursor:
                break

        return "".join(text_parts)

    # ---- Webhook ----

    async def handle_webhook(self, payload: dict, signature: str) -> bool:
        return False

    # ---- Lifecycle ----

    async def revoke(self) -> None:
        if self.credentials:
            self.credentials = None
        logger.info("notion.revoked", entity_id=self.entity_id)

    async def status(self) -> ConnectorStatus:
        connected = self.credentials is not None
        return ConnectorStatus(
            provider="notion",
            connected=connected,
            sync_status="active" if connected else "inactive",
            last_synced_at=None,
        )

    # ---- Helpers ----

    def _get_api_client(self) -> httpx.AsyncClient:
        if not self.credentials:
            raise RuntimeError("Credentials not available")
        return httpx.AsyncClient(
            base_url=NOTION_API_BASE,
            headers={
                "Authorization": f"Bearer {self.credentials.access_token}",
                "Notion-Version": NOTION_VERSION,
            },
            follow_redirects=True,
        )

    # ---- Credential persistence ----

    def encrypt(self) -> bytes | None:
        if self.credentials:
            return encrypt_credentials(self.credentials)
        return None

    @classmethod
    def decrypt(cls, encrypted: bytes, entity_id: str) -> "NotionConnector":
        connector = cls(entity_id=entity_id)
        connector.credentials = decrypt_credentials(encrypted)
        return connector


# ---- Module-level helpers ----

async def _notion_rate_limit_sleep():
    await asyncio.sleep(0.35)


def _extract_page_title(page_or_db: dict) -> str:
    props = page_or_db.get("properties", {})
    for key, prop in props.items():
        if prop.get("type") == "title" and prop.get("title"):
            return "".join(t.get("plain_text", "") for t in prop["title"])
    for key, prop in props.items():
        if prop.get("type") == "rich_text" and prop.get("rich_text"):
            return "".join(t.get("plain_text", "") for t in prop["rich_text"])
    return page_or_db.get("id", "Untitled")[:8]


def _extract_database_row(row: dict) -> str:
    props = row.get("properties", {})
    parts = []
    for name, prop in props.items():
        value = _extract_property_value(prop)
        if value:
            parts.append(f"{name}: {value}")
    return " | ".join(parts)


def _extract_property_value(prop: dict) -> str:
    prop_type = prop.get("type", "")
    if prop_type == "title":
        return "".join(t.get("plain_text", "") for t in prop.get("title", []))
    if prop_type == "rich_text":
        return "".join(t.get("plain_text", "") for t in prop.get("rich_text", []))
    if prop_type == "select":
        return prop.get("select", {}).get("name", "")
    if prop_type == "multi_select":
        return ", ".join(o.get("name", "") for o in prop.get("multi_select", []))
    if prop_type == "date":
        d = prop.get("date", {})
        if d:
            return d.get("start", "") + (f" → {d['end']}" if d.get("end") else "")
        return ""
    if prop_type == "number":
        return str(prop.get("number", ""))
    if prop_type == "checkbox":
        return "✓" if prop.get("checkbox") else "✗"
    if prop_type == "url":
        return prop.get("url", "")
    if prop_type == "email":
        return prop.get("email", "")
    if prop_type == "phone_number":
        return prop.get("phone_number", "")
    if prop_type == "formula":
        f = prop.get("formula", {})
        return str(f.get(f.get("type", ""), ""))
    if prop_type == "status":
        return prop.get("status", {}).get("name", "")
    if prop_type == "people":
        people = prop.get("people", [])
        return ", ".join(p.get("name", "") for p in people)
    if prop_type == "files":
        files = prop.get("files", [])
        return ", ".join(f.get("name", "(unnamed)") for f in files)
    return ""
