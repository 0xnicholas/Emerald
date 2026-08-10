"""Tests for emerald.sources.binding_store persistence accessors."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock


class _MockSessionCtx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *args):
        return None


def _make_factory(session) -> MagicMock:
    mock_sf = MagicMock()
    mock_sf.session = MagicMock(side_effect=lambda: _MockSessionCtx(session))
    return mock_sf


def _make_binding(entity_id: uuid.UUID, hub_account_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        entity_id=entity_id,
        provider="feishu",
        hub_account_id=hub_account_id,
        sync_status="active",
        sync_metadata=None,
        error_message=None,
        last_synced_at=None,
        created_at=None,
        updated_at=None,
    )


async def test_get_binding_by_account_returns_first_of_duplicates(monkeypatch):
    """P1-1 companion: the same hub account bound to two entities must not
    raise MultipleResultsFound — event ingestion would otherwise crash."""
    first = _make_binding(uuid.UUID("550e8400-e29b-41d4-a716-446655440000"), "acc_1")
    second = _make_binding(uuid.UUID("550e8400-e29b-41d4-a716-446655440001"), "acc_1")
    result = MagicMock()
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[first, second])))
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    mock_sf = _make_factory(session)

    import emerald.sources.binding_store as bs

    monkeypatch.setattr(bs, "session_factory", mock_sf)

    from emerald.sources.binding_store import get_binding_by_account

    binding = await get_binding_by_account("acc_1")
    assert binding is first


async def test_get_binding_by_account_returns_none_when_unbound(monkeypatch):
    result = MagicMock()
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    mock_sf = _make_factory(session)

    import emerald.sources.binding_store as bs

    monkeypatch.setattr(bs, "session_factory", mock_sf)

    from emerald.sources.binding_store import get_binding_by_account

    assert await get_binding_by_account("ghost") is None
