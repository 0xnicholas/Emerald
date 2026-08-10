"""Source Binding persistence (ADR-0004).

Thin async accessors over the ``source_bindings`` table. The binding
stores only the authorization relationship + source identity; sync
state lives in ``sync_metadata`` (e.g. per-item etags for dedup).
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import delete, select

from emerald.db.session import session_factory
from emerald.models.entity import Entity
from emerald.models.source_binding import SourceBinding

logger = structlog.get_logger(__name__)


async def get_entity_external_id(entity_internal_id: uuid.UUID) -> str | None:
    """Resolve an entity's internal UUID to its external_id.

    Bindings store the internal UUID (FK to ``entities.id``); the pipeline
    resolves entities by ``external_id``, so the adapter layer must convert
    before ingestion (P1-1).
    """
    async with session_factory.session() as session:
        result = await session.execute(
            select(Entity.external_id).where(Entity.id == entity_internal_id)
        )
        return result.scalar_one_or_none()


async def upsert_binding(
    *,
    entity_id: str | uuid.UUID,
    provider: str,
    hub_account_id: str,
) -> SourceBinding:
    """Create a binding or restore/refresh it if the account was seen before."""
    if isinstance(entity_id, str):
        entity_id = uuid.UUID(entity_id)
    async with session_factory.session() as session:
        result = await session.execute(
            select(SourceBinding).where(
                SourceBinding.entity_id == entity_id,
                SourceBinding.hub_account_id == hub_account_id,
            )
        )
        binding = result.scalar_one_or_none()
        if binding is None:
            binding = SourceBinding(
                entity_id=entity_id,
                provider=provider,
                hub_account_id=hub_account_id,
                sync_status="active",
            )
            session.add(binding)
            await session.commit()
            await session.refresh(binding)
        return binding


async def get_binding_by_account(hub_account_id: str) -> SourceBinding | None:
    """Return the binding for an account, or None if unbound.

    The same hub account may be bound to more than one entity (each
    connect session is entity-scoped); pick the first deterministically
    instead of raising ``MultipleResultsFound`` (P1-1 companion).
    """
    async with session_factory.session() as session:
        result = await session.execute(
            select(SourceBinding).where(
                SourceBinding.hub_account_id == hub_account_id
            )
        )
        bindings = list(result.scalars().all())
        if len(bindings) > 1:
            logger.warning(
                "binding_account_duplicate",
                hub_account_id=hub_account_id,
                count=len(bindings),
            )
        return bindings[0] if bindings else None


async def list_bindings(entity_id: str | uuid.UUID) -> list[SourceBinding]:
    if isinstance(entity_id, str):
        entity_id = uuid.UUID(entity_id)
    async with session_factory.session() as session:
        result = await session.execute(
            select(SourceBinding)
            .where(SourceBinding.entity_id == entity_id)
            .order_by(SourceBinding.created_at)
        )
        return list(result.scalars().all())


async def list_all_bindings() -> list[SourceBinding]:
    """All bindings across entities (for the fallback sync sweep)."""
    async with session_factory.session() as session:
        result = await session.execute(
            select(SourceBinding).where(SourceBinding.sync_status == "active")
        )
        return list(result.scalars().all())


async def update_sync_state(
    binding: SourceBinding,
    *,
    metadata: dict | None = None,
    last_synced_at: object | None = None,
    error: str | None = None,
    status: str | None = None,
) -> None:
    async with session_factory.session() as session:
        current = await session.get(SourceBinding, binding.id)
        if current is None:
            return
        if metadata is not None:
            current.sync_metadata = metadata
        if last_synced_at is not None:
            current.last_synced_at = last_synced_at
        if error is not None:
            current.error_message = error
        if status is not None:
            current.sync_status = status
        await session.commit()


async def delete_binding(binding_id: uuid.UUID) -> None:
    async with session_factory.session() as session:
        await session.execute(
            delete(SourceBinding).where(SourceBinding.id == binding_id)
        )
        await session.commit()
