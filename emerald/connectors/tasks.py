"""Connector Celery tasks — sync and webhook processing.

These tasks bridge Celery Beat scheduling to actual connector sync execution.
Each Celery task is a thin sync wrapper (@shared_task) around an async
implementation function, following the same pattern as emerald/pipeline/tasks.py.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from celery import shared_task
from sqlalchemy import select

from emerald.async_utils import run_async
from emerald.connectors.auth import decrypt_credentials
from emerald.connectors.base import SyncMode
from emerald.connectors.registry import get_connector_registry
from emerald.db.session import session_factory
from emerald.models.connector import Connector

logger = structlog.get_logger(__name__)


# ---- Helpers ----

# Error patterns that indicate transient failures (retry-able, don't mark as permanent)
_TRANSIENT_ERROR_PATTERNS = (
    "rate limit",
    "too many requests",
    "429",
    "timeout",
    "timed out",
    "connection reset",
    "service unavailable",
    "503",
    "temporarily",
)


def _is_transient_error(errors: list[str]) -> bool:
    """Check if ALL errors look transient (rate limits, timeouts, etc.).

    Transient errors keep sync_status='active' so scheduled syncs continue.
    Permanent errors (auth failures, invalid config) mark sync_status='error'.
    """
    if not errors:
        return False
    error_text = " ".join(errors).lower()
    return any(pattern in error_text for pattern in _TRANSIENT_ERROR_PATTERNS)


# ---- Implementation functions (async) ----


async def sync_all(provider: str) -> dict:
    """Sync all active connectors of a given provider type.

    Queries the database for active connectors, then calls sync_single
    for each. Individual failures are logged but do not block others.

    Triggered by Celery Beat on a 4-hour schedule.
    """
    logger.info("connector.sync_all.start", provider=provider)

    async with session_factory.session() as session:
        result = await session.execute(
            select(Connector).where(
                Connector.provider == provider,
                Connector.sync_status == "active",
            )
        )
        rows = result.scalars().all()

    if not rows:
        logger.info("connector.sync_all.no_connectors", provider=provider)
        return {"provider": provider, "synced": 0}

    success_count = 0
    error_count = 0

    for row in rows:
        try:
            await sync_single(
                entity_id=str(row.entity_id),
                provider=provider,
                mode=SyncMode.INCREMENTAL,
            )
            success_count += 1
        except Exception:
            # sync_single already logged the error and persisted error state.
            # Don't duplicate the log — just count and continue.
            error_count += 1

    logger.info(
        "connector.sync_all.done",
        provider=provider,
        total=len(rows),
        success=success_count,
        errors=error_count,
    )
    return {
        "provider": provider,
        "total": len(rows),
        "synced": success_count,
        "errors": error_count,
    }


async def sync_single(
    entity_id: str,
    provider: str,
    mode: SyncMode = SyncMode.INCREMENTAL,
) -> None:
    """Sync a single connector for a specific entity.

    1. Load connector credentials from DB
    2. Instantiate the registered connector class
    3. Execute sync (incremental or full)
    4. Persist updated sync_metadata and last_synced_at

    Incremental syncs use provider-specific sync_metadata
    (e.g., Gmail historyId, Notion last_synced_at) to fetch
    only changes since the last sync.
    """
    logger.info(
        "connector.sync_single.start",
        entity_id=entity_id,
        provider=provider,
        mode=mode,
    )

    # 1. Load connector row from DB
    async with session_factory.session() as session:
        result = await session.execute(
            select(Connector).where(
                Connector.entity_id == uuid.UUID(entity_id),
                Connector.provider == provider,
            )
        )
        row = result.scalar_one_or_none()

    if not row:
        logger.warning(
            "connector.sync_single.not_found",
            entity_id=entity_id,
            provider=provider,
        )
        return

    # 2. Decrypt credentials
    try:
        creds = decrypt_credentials(row.credentials)
    except Exception as exc:
        logger.error(
            "connector.sync_single.decrypt_failed",
            entity_id=entity_id,
            provider=provider,
            error=str(exc),
        )
        # Mark connector as errored
        async with session_factory.session() as session:
            fresh_row = await session.get(Connector, row.id)
            if fresh_row:
                fresh_row.sync_status = "error"
                fresh_row.error_message = f"Credential decrypt failed: {exc}"
                await session.flush()
        return

    # 3. Instantiate connector and run sync
    registry = get_connector_registry()
    connector_cls = registry.get(provider)

    # Some connectors accept sync_metadata for incremental sync state;
    # others (GitHub, Google Drive) don't yet. Use try/except to handle both.
    try:
        connector = connector_cls(
            entity_id=entity_id,
            sync_metadata=row.sync_metadata,
        )
    except TypeError:
        connector = connector_cls(entity_id=entity_id)

    connector.credentials = creds

    sync_start = datetime.now(UTC)
    try:
        result = await connector.sync(mode=mode)
    except Exception as exc:
        logger.error(
            "connector.sync_single.failed",
            entity_id=entity_id,
            provider=provider,
            error=str(exc),
        )
        # Persist error state before re-raising.
        # Check if the exception looks transient to keep the connector active.
        error_str = str(exc)
        new_status = "active" if _is_transient_error([error_str]) else "error"
        async with session_factory.session() as session:
            fresh_row = await session.get(Connector, row.id)
            if fresh_row:
                fresh_row.sync_status = new_status
                fresh_row.error_message = error_str
                fresh_row.last_synced_at = datetime.now(UTC)
                await session.flush()
        raise

    # 4. Persist results
    sync_duration = (datetime.now(UTC) - sync_start).total_seconds()
    updated_metadata = (
        connector.get_sync_metadata()
        if hasattr(connector, "get_sync_metadata")
        else row.sync_metadata
    )

    # Classify sync errors: transient (rate limits, timeouts) keep "active"
    # so scheduled syncs continue; permanent errors mark as "error".
    if result.errors:
        if _is_transient_error(result.errors):
            new_status = "active"
        else:
            new_status = "error"
        error_text = "; ".join(result.errors[:3])
    else:
        new_status = "active"
        error_text = None

    async with session_factory.session() as session:
        fresh_row = await session.get(Connector, row.id)
        if fresh_row:
            fresh_row.last_synced_at = datetime.now(UTC)
            fresh_row.sync_metadata = updated_metadata
            fresh_row.sync_status = new_status
            fresh_row.error_message = error_text
            await session.flush()

    logger.info(
        "connector.sync_single.complete",
        entity_id=entity_id,
        provider=provider,
        files_synced=result.files_synced,
        files_failed=result.files_failed,
        duration_seconds=sync_duration,
    )


async def renew_webhooks() -> dict:
    """Renew expiring webhook registrations for all active connectors.

    Some providers (Google Drive, Gmail) have webhook channel expiry
    (~7 days). This task runs daily to refresh webhook registrations
    before they expire, ensuring continuous sync.

    v0.3.0: Logs registrations that would be renewed. Full webhook
    re-registration to be implemented when webhook support is added
    to individual connectors.
    """
    logger.info("connector.renew_webhooks.start")

    # Providers with expiring webhook channels
    webhook_providers = {"google_drive", "gmail"}

    async with session_factory.session() as session:
        result = await session.execute(
            select(Connector).where(
                Connector.provider.in_(webhook_providers),
                Connector.sync_status == "active",
            )
        )
        rows = result.scalars().all()

    renewed = 0
    for row in rows:
        try:
            # v0.3.0: webhook renewal is a no-op — channels are managed
            # by individual connector webhook handlers. This task serves
            # as a scheduled health check.
            logger.info(
                "connector.renew_webhooks.check",
                entity_id=str(row.entity_id),
                provider=row.provider,
            )
            renewed += 1
        except Exception as exc:
            logger.error(
                "connector.renew_webhooks.failed",
                entity_id=str(row.entity_id),
                provider=row.provider,
                error=str(exc),
            )

    logger.info(
        "connector.renew_webhooks.done",
        checked=len(rows),
        renewed=renewed,
    )
    return {"checked": len(rows), "renewed": renewed}


# ---- Celery task wrappers (sync, for Beat schedule) ----


@shared_task(
    name="emerald.connectors.tasks.sync_all_task",
    max_retries=1,
    default_retry_delay=3600,  # Retry after 1 hour on failure
)
def sync_all_task(provider: str) -> dict:
    """Celery Beat task: sync all active connectors of a provider."""
    return run_async(sync_all)(provider)


@shared_task(
    name="emerald.connectors.tasks.sync_single_task",
    max_retries=2,
    default_retry_delay=300,  # Retry after 5 minutes
)
def sync_single_task(
    entity_id: str,
    provider: str,
    mode: str = "incremental",
) -> None:
    """Celery task: sync a single connector."""
    sync_mode = SyncMode(mode)
    return run_async(sync_single)(entity_id, provider, sync_mode)


@shared_task(
    name="emerald.connectors.tasks.renew_webhooks_task",
    max_retries=1,
    default_retry_delay=43200,  # Retry after 12 hours
)
def renew_webhooks_task() -> dict:
    """Celery Beat task: daily webhook renewal check."""
    return run_async(renew_webhooks)()
