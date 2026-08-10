"""HubAdapter — maps hub events/accounts into the Emerald ingestion pipeline.

The adapter is the *only* place where hub concepts (accounts, events,
actions) become Emerald concepts (SourceItems, documents, pipeline jobs).
It depends on the ConnectionHub interface only — swapping the hub never
touches this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

from emerald.sources import binding_store
from emerald.sources.hub import ConnectionHub, HubEvent

logger = structlog.get_logger(__name__)

# ---- Provider profiles: which hub actions produce content we ingest ----
#
# Action names are Totem's registry names (totem consumption standard §7;
# machine contract: GET {TOTEM_URL}/openapi.json). v1 upstream is Feishu
# Docs only. Totem has no list-all action — search_docs is the only scan
# primitive (title search), so the list call sends a broad query and etag
# dedup keeps rescan cheap; tune the query in one place here.


@dataclass(frozen=True)
class ProviderProfile:
    provider: str
    list_action: str  # list items on the account (returns data/next envelope)
    get_action: str  # fetch one item's content by id
    default_content_type: str
    id_arg: str = "id"  # arg name the get_action expects for the item id
    list_args: dict[str, Any] = field(default_factory=dict)


PROVIDER_PROFILES: dict[str, ProviderProfile] = {
    # Totem v1 actions (verified against the registry 2026-08-10):
    # search_docs {query, limit} -> {data: [{doc_id,title,doc_type}], next};
    # get_doc_content {doc_id} -> {doc_id, content} (plain text with
    # markdown-style headings preserved).
    "feishu": ProviderProfile(
        provider="feishu",
        list_action="search_docs",
        get_action="get_doc_content",
        default_content_type="text/markdown",
        id_arg="doc_id",
        list_args={"query": " "},  # broadest query the schema accepts (minLength 1)
    ),
}


@dataclass
class SourceItem:
    """One piece of external content ready for the pipeline."""

    source_id: str  # stable id on the provider
    title: str
    content: str
    content_type: str
    etag: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class IngestResult:
    account_id: str
    provider: str
    ingested: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def _item_from_raw(raw: dict[str, Any], profile: ProviderProfile) -> SourceItem | None:
    """Normalize a hub list/get response item into a SourceItem.

    Hub-specific field names are read tolerantly (id/doc_id/title/content
    are the common shapes); missing identity means the item is unusable.
    """
    source_id = (
        raw.get("id")
        or raw.get("doc_id")
        or raw.get("file_id")
        or raw.get("page_id")
        or raw.get("item_id")
    )
    if not source_id:
        return None
    title = raw.get("title") or raw.get("name") or source_id
    content = (
        raw.get("content") or raw.get("text") or raw.get("body") or raw.get("plain_text") or ""
    )
    content_type = raw.get("content_type") or profile.default_content_type
    return SourceItem(
        source_id=str(source_id),
        title=str(title),
        content=str(content),
        content_type=str(content_type),
        etag=raw.get("etag") or raw.get("updated_at") or raw.get("version"),
        metadata={
            k: v
            for k, v in raw.items()
            if k
            not in (
                "id",
                "doc_id",
                "file_id",
                "page_id",
                "item_id",
                "title",
                "name",
                "content",
                "text",
                "body",
                "plain_text",
                "etag",
                "updated_at",
                "version",
                "content_type",
                "doc_type",
            )
        },
    )


class HubAdapter:
    """Turn hub activity into pipeline ingestion."""

    def __init__(self, hub: ConnectionHub) -> None:
        self.hub = hub

    def _profile_for(self, provider: str) -> ProviderProfile:
        profile = PROVIDER_PROFILES.get(provider)
        if profile is None:
            raise ValueError(
                f"No provider profile for '{provider}'. Known: {list(PROVIDER_PROFILES)}"
            )
        return profile

    async def ingest_account(
        self,
        *,
        account_id: str,
        provider: str,
        entity_id: str,
        content_cb: Any = None,
    ) -> IngestResult:
        """Incremental sync for one account: list → fetch changed → pipeline.

        ``content_cb`` is the ingestion sink; it defaults to the async
        pipeline orchestrator (injected so tests can capture items
        without a database).
        """
        profile = self._profile_for(provider)
        result = IngestResult(account_id=account_id, provider=provider)
        try:
            listing = await self.hub.execute_action(
                account_id=account_id,
                action=profile.list_action,
                query=profile.list_args or None,
            )
        except Exception as exc:  # noqa: BLE001 - per-account isolation
            result.failed += 1
            result.errors.append(f"list failed: {exc}")
            logger.warning("hub_list_failed", account_id=account_id, error=str(exc))
            return result

        # Totem list envelope: {data: [...], next} (standard §7). Older
        # hubs' {results: [...]} shape is tolerated for symmetry.
        items = listing.get("data") or listing.get("results") or []
        if isinstance(items, dict):
            items = items.get("results", [])
        if not isinstance(items, list):
            logger.warning("unexpected_list_shape", account_id=account_id, provider=provider)
            return result

        # Load dedup state: seen[source_id] -> etag
        binding = await binding_store.get_binding_by_account(account_id)
        seen: dict[str, str] = {}
        if binding and binding.sync_metadata:
            seen = binding.sync_metadata.get("seen", {})

        for raw in items:
            item = _item_from_raw(raw, profile)
            if item is None:
                result.skipped += 1
                continue
            # Dedup key: the hub's version field when present, else the
            # source id itself (Totem v1 search_docs carries no version;
            # id-presence is the only change signal a rescan can use).
            etag_key = item.etag or item.source_id
            if seen.get(item.source_id) == etag_key:
                result.skipped += 1
                continue

            try:
                if item.content:
                    fetched = item
                else:
                    fetched_raw = await self.hub.execute_action(
                        account_id=account_id,
                        action=profile.get_action,
                        query={profile.id_arg: item.source_id},
                    )
                    fetched = _item_from_raw(fetched_raw, profile) or item
                    if not fetched.content and isinstance(fetched_raw, dict):
                        nested = fetched_raw.get("data")
                        fetched.content = str(
                            fetched_raw.get("content")
                            or fetched_raw.get("text")
                            or (nested.get("content", "") if isinstance(nested, dict) else "")
                        )

                if content_cb is not None:
                    await content_cb(
                        content=fetched.content,
                        content_type=fetched.content_type,
                        entity_id=entity_id,
                        metadata={
                            "source": "connection_hub",
                            "hub_account_id": account_id,
                            "provider": provider,
                            "source_id": fetched.source_id,
                            "source_title": fetched.title,
                            **fetched.metadata,
                        },
                    )
                seen[item.source_id] = etag_key
                result.ingested += 1
            except Exception as exc:  # noqa: BLE001 - one bad item must not block the rest
                result.failed += 1
                result.errors.append(f"{item.source_id}: {exc}")
                logger.warning(
                    "hub_item_failed",
                    account_id=account_id,
                    source_id=item.source_id,
                    error=str(exc),
                )

        if binding:
            await binding_store.update_sync_state(
                binding,
                metadata={"seen": seen},
                last_synced_at=datetime.now(UTC),
                error="; ".join(result.errors[:5]) or None,
            )
        return result

    async def handle_event(self, event: HubEvent, content_cb: Any = None) -> IngestResult:
        """Route a verified hub event to the right account sync."""
        binding = await binding_store.get_binding_by_account(event.account_id)
        if binding is None:
            logger.info(
                "event_for_unknown_account",
                account_id=event.account_id,
                event_type=event.event_type,
            )
            return IngestResult(
                account_id=event.account_id,
                provider=event.provider,
                errors=["no binding for account"],
            )

        # Any content-change event triggers an incremental sync of the
        # account; dedup by etag keeps it cheap. Account lifecycle events
        # (connected/revoked) update the binding status instead. Totem's
        # pre-recorded v2 events (§8.2: connection.created/updated/deleted)
        # and the legacy account.* names are both handled.
        if event.event_type in (
            "account.connected",
            "account.reconnected",
            "connection.created",
            "connection.updated",
        ):
            await binding_store.update_sync_state(binding, status="active")
        elif event.event_type in ("account.revoked", "account.disconnected", "connection.deleted"):
            await binding_store.update_sync_state(binding, status="revoked")
            return IngestResult(
                account_id=event.account_id,
                provider=binding.provider,
                errors=[],
            )

        # The binding stores the entity's internal UUID, but the pipeline
        # resolves entities by external_id — resolve here (P1-1) or every
        # event-driven ingestion fails with "Entity not found".
        external_id = await binding_store.get_entity_external_id(binding.entity_id)
        if external_id is None:
            logger.warning(
                "event_for_missing_entity",
                account_id=event.account_id,
                entity_id=str(binding.entity_id),
                event_type=event.event_type,
            )
            return IngestResult(
                account_id=event.account_id,
                provider=binding.provider,
                errors=["entity for binding not found"],
            )

        return await self.ingest_account(
            account_id=event.account_id,
            provider=binding.provider,
            entity_id=external_id,
            content_cb=content_cb,
        )


def default_content_cb() -> Any:
    """Build the default ingestion sink: the async pipeline orchestrator."""
    from emerald.pipeline.orchestrator import PipelineOrchestrator

    orchestrator = PipelineOrchestrator()

    async def _sink(
        *,
        content: str,
        content_type: str,
        entity_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await orchestrator.process_async(
            content=content,
            content_type=content_type,
            entity_id=entity_id,
            document_id=None,
        )

    return _sink
