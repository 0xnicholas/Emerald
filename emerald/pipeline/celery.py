"""Celery application factory."""

from __future__ import annotations

import asyncio

from celery import Celery
from celery import signals as celery_signals

from emerald.config import get_settings

settings = get_settings()

celery_app = Celery(
    "emerald",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Retry defaults
    task_default_retry_delay=60,
    task_max_retries=3,
)

# Beat schedule — scheduled tasks for forget engine and connector sync
celery_app.conf.beat_schedule = {
    "forget-expired-memories": {
        "task": "emerald.pipeline.tasks.forget_expired",
        "schedule": 3600.0,  # Every hour
    },
    "forget-noise-memories": {
        "task": "emerald.pipeline.tasks.forget_noise",
        "schedule": 86400.0,  # Daily (3 AM handled by the task itself)
    },
    "decay-episodic-memories": {
        "task": "emerald.pipeline.tasks.decay_episodic",
        "schedule": 86400.0,  # Daily (4 AM)
    },
    "sync-google-drive": {
        "task": "emerald.connectors.tasks.sync_all",
        "schedule": 14400.0,  # Every 4 hours
        "kwargs": {"provider": "google_drive"},
    },
    "sync-gmail": {
        "task": "emerald.connectors.tasks.sync_all",
        "schedule": 14400.0,
        "kwargs": {"provider": "gmail"},
    },
    "sync-notion": {
        "task": "emerald.connectors.tasks.sync_all",
        "schedule": 14400.0,
        "kwargs": {"provider": "notion"},
    },
    "sync-github": {
        "task": "emerald.connectors.tasks.sync_all",
        "schedule": 14400.0,
        "kwargs": {"provider": "github"},
    },
}

# Auto-discover tasks in pipeline and connectors
celery_app.autodiscover_tasks(
    ["emerald.pipeline", "emerald.connectors"], force=True
)


# ---- Worker lifecycle signals ----
# Neo4j driver is initialized once per worker process and shared across
# all tasks, avoiding per-task connection overhead.

@celery_signals.worker_process_init.connect
def _init_neo4j_on_worker_start(**kwargs) -> None:
    from emerald.db.neo4j import init_neo4j

    asyncio.run(init_neo4j())


@celery_signals.worker_process_shutdown.connect
def _close_neo4j_on_worker_shutdown(**kwargs) -> None:
    from emerald.db.neo4j import close_neo4j

    asyncio.run(close_neo4j())
