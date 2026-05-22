"""Connector Celery Beat scheduler — periodic sync and webhook renewal."""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)

# Celery Beat schedule configuration.
# In production, these are loaded into the Celery app config.
# See emerald/pipeline/tasks.py for the Celery app setup.

BEAT_SCHEDULE: dict[str, dict] = {
    "sync-google-drive": {
        "task": "emerald.connectors.tasks.sync_all",
        "schedule": "0 */4 * * *",  # Every 4 hours
        "kwargs": {"provider": "google_drive"},
    },
    "sync-gmail": {
        "task": "emerald.connectors.tasks.sync_all",
        "schedule": "0 */4 * * *",
        "kwargs": {"provider": "gmail"},
    },
    "sync-notion": {
        "task": "emerald.connectors.tasks.sync_all",
        "schedule": "0 */4 * * *",
        "kwargs": {"provider": "notion"},
    },
    "sync-github": {
        "task": "emerald.connectors.tasks.sync_all",
        "schedule": "0 */4 * * *",
        "kwargs": {"provider": "github"},
    },
    "renew-webhooks": {
        "task": "emerald.connectors.tasks.renew_webhooks",
        "schedule": "0 2 * * *",  # Daily at 2 AM
    },
}

# Sync modes
# - INCREMENTAL: delta since last sync (webhook or scheduled)
# - FULL: all content (first connection or manual trigger)
