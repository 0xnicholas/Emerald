"""Connector Celery tasks — sync and webhook processing."""

from __future__ import annotations

import structlog

from emerald.connectors.base import SyncMode

logger = structlog.get_logger(__name__)


async def sync_all(provider: str) -> None:
    """Sync all active connectors of a given provider type.

    Triggered by Celery Beat on a 4-hour schedule.
    """
    logger.info("connector.sync_all.start", provider=provider)
    # TODO:
    # 1. Query connectors table for active connectors of this provider
    # 2. For each, submit sync_single task
    logger.info("connector.sync_all.done", provider=provider)


async def sync_single(
    entity_id: str, provider: str, mode: SyncMode = SyncMode.INCREMENTAL
) -> None:
    """Sync a single connector for a specific entity.

    Incremental syncs use change-since-timestamp deltas.
    Full syncs re-process all content.
    """
    logger.info(
        "connector.sync_single.start",
        entity_id=entity_id,
        provider=provider,
        mode=mode,
    )
    # TODO:
    # 1. Load connector credentials from DB
    # 2. Refresh token if needed
    # 3. Fetch changed files since last sync
    # 4. Download files, hash-deduplicate
    # 5. Submit to pipeline
    # 6. Update last_synced_at + sync_status
    pass


async def renew_webhooks() -> None:
    """Renew expiring webhook registrations for all active connectors.

    Some providers (Google, Gmail) have webhook channel expiry (7 days).
    This task runs daily to renew before expiry.
    """
    logger.info("connector.renew_webhooks.start")
    # TODO: query active connectors, re-register webhooks
    pass
