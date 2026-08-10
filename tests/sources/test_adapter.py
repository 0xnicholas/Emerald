"""HubAdapter tests — event → ingestion pipeline with a FakeHub."""

from __future__ import annotations

from emerald.sources.adapter import HubAdapter
from emerald.sources.hub import HubEvent
from tests.sources.fake_hub import FakeBindingStore, FakeHub, patch_binding_store


def _capture_sink(items: list[dict]):
    async def _sink(*, content, content_type, entity_id, metadata=None):
        items.append(
            {
                "content": content,
                "content_type": content_type,
                "entity_id": entity_id,
                "metadata": metadata or {},
            }
        )

    return _sink


def _drive_listing():
    return [
        {"id": "f1", "title": "notes.md", "etag": "v1"},
        {"id": "f2", "title": "roadmap.md", "etag": "v1"},
    ]


async def test_ingest_account_lists_fetches_and_pushes(monkeypatch):
    hub = FakeHub()
    hub.listings["acc_1"] = _drive_listing()
    hub.contents["acc_1:f1"] = {"id": "f1", "content": "## Notes body"}
    hub.contents["acc_1:f2"] = {"id": "f2", "content": "## Roadmap body"}

    store = FakeBindingStore()
    await store.upsert(entity_id="user_1", provider="googledrive", hub_account_id="acc_1")
    patch_binding_store(monkeypatch, store)

    captured: list[dict] = []
    adapter = HubAdapter(hub)
    result = await adapter.ingest_account(
        account_id="acc_1",
        provider="googledrive",
        entity_id="user_1",
        content_cb=_capture_sink(captured),
    )

    assert result.ingested == 2
    assert result.skipped == 0
    assert [c["content"] for c in captured] == ["## Notes body", "## Roadmap body"]
    assert all(c["entity_id"] == "user_1" for c in captured)
    assert captured[0]["metadata"]["source"] == "connection_hub"
    assert captured[0]["metadata"]["provider"] == "googledrive"
    # Dedup state persisted
    assert (await store.get_by_account("acc_1")).sync_metadata["seen"] == {
        "f1": "v1",
        "f2": "v1",
    }


async def test_ingest_account_dedupes_by_etag(monkeypatch):
    hub = FakeHub()
    hub.listings["acc_1"] = _drive_listing()
    hub.contents["acc_1:f1"] = {"id": "f1", "content": "## Notes body"}
    hub.contents["acc_1:f2"] = {"id": "f2", "content": "## Roadmap body"}

    store = FakeBindingStore()
    binding = await store.upsert(
        entity_id="user_1", provider="googledrive", hub_account_id="acc_1"
    )
    binding.sync_metadata = {"seen": {"f1": "v1", "f2": "v1"}}
    patch_binding_store(monkeypatch, store)

    captured: list[dict] = []
    adapter = HubAdapter(hub)
    result = await adapter.ingest_account(
        account_id="acc_1",
        provider="googledrive",
        entity_id="user_1",
        content_cb=_capture_sink(captured),
    )

    assert result.ingested == 0
    assert result.skipped == 2
    assert captured == []


async def test_ingest_account_changed_etag_reingests(monkeypatch):
    hub = FakeHub()
    hub.listings["acc_1"] = [{"id": "f1", "title": "notes.md", "etag": "v2"}]
    hub.contents["acc_1:f1"] = {"id": "f1", "content": "## Updated"}

    store = FakeBindingStore()
    binding = await store.upsert(
        entity_id="user_1", provider="googledrive", hub_account_id="acc_1"
    )
    binding.sync_metadata = {"seen": {"f1": "v1"}}
    patch_binding_store(monkeypatch, store)

    captured: list[dict] = []
    adapter = HubAdapter(hub)
    result = await adapter.ingest_account(
        account_id="acc_1",
        provider="googledrive",
        entity_id="user_1",
        content_cb=_capture_sink(captured),
    )

    assert result.ingested == 1
    assert captured[0]["content"] == "## Updated"


async def test_handle_event_syncs_for_change_event(monkeypatch):
    hub = FakeHub()
    hub.listings["acc_1"] = _drive_listing()
    hub.contents["acc_1:f1"] = {"id": "f1", "content": "## Notes body"}
    hub.contents["acc_1:f2"] = {"id": "f2", "content": "## Roadmap body"}

    store = FakeBindingStore()
    await store.upsert(entity_id="user_1", provider="googledrive", hub_account_id="acc_1")
    patch_binding_store(monkeypatch, store)

    captured: list[dict] = []
    adapter = HubAdapter(hub)
    event = HubEvent(
        event_type="file.changed",
        provider="googledrive",
        account_id="acc_1",
    )
    result = await adapter.handle_event(event, content_cb=_capture_sink(captured))

    assert result.ingested == 2
    assert result.provider == "googledrive"


async def test_handle_event_resolves_internal_uuid_to_external_id(monkeypatch):
    """P1-1: handle_event must pass the entity's external_id to the pipeline.

    The binding stores the internal UUID (FK to entities.id); the pipeline
    resolves entities by external_id. Passing the UUID caused
    ``Entity not found`` for every event-driven ingestion.
    """
    hub = FakeHub()
    hub.listings["acc_1"] = [{"id": "f1", "title": "notes.md", "etag": "v1"}]
    hub.contents["acc_1:f1"] = {"id": "f1", "content": "## Notes body"}

    store = FakeBindingStore()
    internal_uuid = "550e8400-e29b-41d4-a716-446655440000"
    await store.upsert(
        entity_id=internal_uuid, provider="googledrive", hub_account_id="acc_1"
    )
    store.entity_external[internal_uuid] = "user_1"
    patch_binding_store(monkeypatch, store)

    captured: list[dict] = []
    adapter = HubAdapter(hub)
    event = HubEvent(
        event_type="file.changed",
        provider="googledrive",
        account_id="acc_1",
    )
    result = await adapter.handle_event(event, content_cb=_capture_sink(captured))

    assert result.ingested == 1
    assert captured[0]["entity_id"] == "user_1"
    assert captured[0]["entity_id"] != internal_uuid


async def test_handle_event_unknown_entity_returns_error(monkeypatch):
    """When the binding's entity no longer exists, fail soft, don't crash."""
    hub = FakeHub()
    store = FakeBindingStore()
    await store.upsert(
        entity_id="550e8400-e29b-41d4-a716-446655440001",
        provider="googledrive",
        hub_account_id="acc_1",
    )
    store.missing_entities.add("550e8400-e29b-41d4-a716-446655440001")
    patch_binding_store(monkeypatch, store)

    adapter = HubAdapter(hub)
    event = HubEvent(
        event_type="file.changed",
        provider="googledrive",
        account_id="acc_1",
    )
    result = await adapter.handle_event(event, content_cb=_capture_sink([]))
    assert result.ingested == 0
    assert result.errors


async def test_handle_event_unknown_account_returns_error(monkeypatch):
    hub = FakeHub()
    store = FakeBindingStore()
    patch_binding_store(monkeypatch, store)

    adapter = HubAdapter(hub)
    event = HubEvent(
        event_type="file.changed",
        provider="googledrive",
        account_id="ghost",
    )
    result = await adapter.handle_event(event, content_cb=_capture_sink([]))
    assert result.ingested == 0
    assert result.errors == ["no binding for account"]


async def test_handle_event_connected_marks_binding_active(monkeypatch):
    hub = FakeHub()
    store = FakeBindingStore()
    binding = await store.upsert(
        entity_id="user_1", provider="googledrive", hub_account_id="acc_1"
    )
    binding.sync_status = "revoked"
    patch_binding_store(monkeypatch, store)

    adapter = HubAdapter(hub)
    event = HubEvent(
        event_type="account.connected",
        provider="googledrive",
        account_id="acc_1",
    )
    result = await adapter.handle_event(event, content_cb=None)
    assert result.ingested == 0
    assert (await store.get_by_account("acc_1")).sync_status == "active"


async def test_unknown_provider_raises():
    import pytest

    hub = FakeHub()
    adapter = HubAdapter(hub)
    with pytest.raises(ValueError, match="slack"):
        await adapter.ingest_account(
            account_id="acc_1", provider="slack", entity_id="user_1"
        )
