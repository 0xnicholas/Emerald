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
    "sync-source-bindings": {
        "task": "emerald.sources.tasks.sync_all_bindings_task",
        "schedule": 3600.0,  # Every hour: fallback sweep, webhook events are primary
    },
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
    "renew-webhooks": {
        "task": "emerald.connectors.tasks.renew_webhooks_task",
        "schedule": 86400.0,  # Daily
    },
    "sync-google-drive": {
        "task": "emerald.connectors.tasks.sync_all_task",
        "schedule": 14400.0,  # Every 4 hours
        "kwargs": {"provider": "google_drive"},
    },
    "sync-gmail": {
        "task": "emerald.connectors.tasks.sync_all_task",
        "schedule": 14400.0,
        "kwargs": {"provider": "gmail"},
    },
    "sync-notion": {
        "task": "emerald.connectors.tasks.sync_all_task",
        "schedule": 14400.0,
        "kwargs": {"provider": "notion"},
    },
    "sync-github": {
        "task": "emerald.connectors.tasks.sync_all_task",
        "schedule": 14400.0,
        "kwargs": {"provider": "github"},
    },
    "reconcile-index": {
        "task": "emerald.pipeline.tasks.reconcile_index_task",
        "schedule": 1800.0,  # Every 30 minutes
    },
}

# Auto-discover tasks in pipeline and connectors
celery_app.autodiscover_tasks(
    ["emerald.pipeline", "emerald.connectors"], force=True
)


# ---- Worker lifecycle signals ----
# Celery tasks execute their async helpers in a fresh event loop per task
# (run_async -> asyncio.run).  Loop-bound resources (asyncpg pool, Redis
# client, Neo4j driver) must therefore be (re)created inside each task's
# own loop — see _dispose_db_pool_before_task, ensure_redis_for_loop and
# the per-task init_neo4j() calls in emerald/pipeline/tasks.py.


@celery_signals.worker_process_init.connect
def _init_worker_process(**kwargs) -> None:
    """Prepare loop-independent worker state after fork.

    - Flag worker mode so any SQLAlchemy engine built from now on uses
      NullPool (no cross-event-loop connection reuse).
    - Rebuild an engine that may already exist (imported before the fork)
      with the same non-pooling semantics.
    """
    import os

    os.environ["EMERALD_CELERY_WORKER"] = "1"

    from emerald.db.session import session_factory

    session_factory.rebuild_for_worker()


@celery_signals.task_prerun.connect
def _dispose_db_pool_before_task(**kwargs) -> None:
    """Dispose the shared PostgreSQL pool before each task.

    Defence in depth alongside the worker's NullPool engine: if a pooled
    engine ever reaches a task (e.g. the FastAPI process engine in eager
    mode), disposing before the task prevents handing the task an asyncpg
    connection created in a previous task's event loop.
    """
    from emerald.db.session import session_factory

    asyncio.run(session_factory.engine.dispose())


@celery_signals.worker_process_shutdown.connect
def _close_neo4j_on_worker_shutdown(**kwargs) -> None:
    from emerald.db.neo4j import close_neo4j

    asyncio.run(close_neo4j())
