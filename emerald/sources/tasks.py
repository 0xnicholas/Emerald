"""Connection hub fallback sync tasks (ADR-0004).

Webhook events drive incremental ingestion; these tasks are the
scheduled safety net so a missed event self-heals on the next sweep.
"""

from __future__ import annotations

import structlog
from celery import shared_task

from emerald.async_utils import run_async
from emerald.sources import binding_store
from emerald.sources.factory import get_hub

logger = structlog.get_logger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_all_bindings_task(self) -> dict:
    """Sweep every active binding and run an incremental sync.

    Runs on a schedule (e.g. hourly); dedup by etag keeps repeat
    sweeps cheap. Per-account failures are isolated and recorded on
    the binding, not raised.
    """
    try:
        return run_async(_run_sync_all)(self)
    except Exception as exc:
        logger.exception("sync_all_bindings_failed")
        raise self.retry(exc=exc) from exc


async def _run_sync_all(_task) -> dict:
    from emerald.sources.adapter import HubAdapter, default_content_cb

    bindings = await binding_store.list_all_bindings()
    hub = get_hub()
    adapter = HubAdapter(hub)
    content_cb = default_content_cb()
    results: list[dict[str, object]] = []
    for binding in bindings:
        # Bindings store the entity's internal UUID; the pipeline resolves
        # by external_id (P1-1). Skip bindings whose entity is gone.
        external_id = await binding_store.get_entity_external_id(binding.entity_id)
        if external_id is None:
            results.append(
                {
                    "account_id": binding.hub_account_id,
                    "provider": binding.provider,
                    "error": "entity for binding not found",
                }
            )
            continue
        try:
            result = await adapter.ingest_account(
                account_id=binding.hub_account_id,
                provider=binding.provider,
                entity_id=external_id,
                content_cb=content_cb,
            )
            results.append(
                {
                    "account_id": result.account_id,
                    "provider": result.provider,
                    "ingested": result.ingested,
                    "skipped": result.skipped,
                    "failed": result.failed,
                    "errors": result.errors[:3],
                }
            )
        except Exception as exc:  # noqa: BLE001 - one account must not block the sweep
            logger.warning(
                "binding_sync_failed",
                account_id=binding.hub_account_id,
                error=str(exc),
            )
            results.append(
                {
                    "account_id": binding.hub_account_id,
                    "provider": binding.provider,
                    "error": str(exc),
                }
            )
    return {"synced": len(results), "results": results}
