"""HubAdapter tests — event → ingestion pipeline with a FakeHub.

Contract under test: the feishu provider profile (Totem v1 upstream) —
search_docs list envelope {data, next}, get_doc_content by doc_id,
connection lifecycle events in the §8.2 shape.
"""

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


def _feishu_listing():
    """search_docs output shape: doc_id/title/doc_type entries."""
    return [
        {"doc_id": "dox1", "title": "Q3 规划", "doc_type": "docx", "updated_at": "v1"},
        {"doc_id": "dox2", "title": "Roadmap", "doc_type": "docx", "updated_at": "v1"},
    ]


async def test_ingest_account_lists_fetches_and_pushes(monkeypatch):
    hub = FakeHub()
    hub.listings["conn_1"] = _feishu_listing()
    hub.contents["conn_1:dox1"] = {"doc_id": "dox1", "content": "## 正文"}
    hub.contents["conn_1:dox2"] = {"doc_id": "dox2", "content": "## Roadmap body"}

    store = FakeBindingStore()
    await store.upsert(entity_id="user_1", provider="feishu", hub_account_id="conn_1")
    patch_binding_store(monkeypatch, store)

    captured: list[dict] = []
    adapter = HubAdapter(hub)
    result = await adapter.ingest_account(
        account_id="conn_1",
        provider="feishu",
        entity_id="user_1",
        content_cb=_capture_sink(captured),
    )

    assert result.ingested == 2
    assert result.skipped == 0
    assert [c["content"] for c in captured] == ["## 正文", "## Roadmap body"]
    assert all(c["entity_id"] == "user_1" for c in captured)
    assert captured[0]["metadata"]["source"] == "connection_hub"
    assert captured[0]["metadata"]["provider"] == "feishu"
    assert captured[0]["metadata"]["source_id"] == "dox1"
    # Dedup state persisted (keyed by doc_id)
    assert (await store.get_by_account("conn_1")).sync_metadata["seen"] == {
        "dox1": "v1",
        "dox2": "v1",
    }


async def test_ingest_account_fetches_via_doc_id_arg(monkeypatch):
    """The get action must be called with doc_id (Totem's id arg), not id."""
    hub = FakeHub()
    hub.listings["conn_1"] = [
        {"doc_id": "dox9", "title": "Empty", "doc_type": "docx", "updated_at": "v1"}
    ]
    hub.contents["conn_1:dox9"] = {"doc_id": "dox9", "content": "content here"}

    store = FakeBindingStore()
    await store.upsert(entity_id="user_1", provider="feishu", hub_account_id="conn_1")
    patch_binding_store(monkeypatch, store)

    captured: list[dict] = []
    adapter = HubAdapter(hub)
    result = await adapter.ingest_account(
        account_id="conn_1",
        provider="feishu",
        entity_id="user_1",
        content_cb=_capture_sink(captured),
    )
    assert result.ingested == 1
    get_calls = [c for c in hub.action_calls if c["action"] == "get_doc_content"]
    assert get_calls == [
        {"account_id": "conn_1", "action": "get_doc_content", "query": {"doc_id": "dox9"}}
    ]


async def test_ingest_account_dedupes_by_etag(monkeypatch):
    hub = FakeHub()
    hub.listings["conn_1"] = _feishu_listing()
    hub.contents["conn_1:dox1"] = {"doc_id": "dox1", "content": "## 正文"}
    hub.contents["conn_1:dox2"] = {"doc_id": "dox2", "content": "## Roadmap body"}

    store = FakeBindingStore()
    binding = await store.upsert(entity_id="user_1", provider="feishu", hub_account_id="conn_1")
    binding.sync_metadata = {"seen": {"dox1": "v1", "dox2": "v1"}}
    patch_binding_store(monkeypatch, store)

    captured: list[dict] = []
    adapter = HubAdapter(hub)
    result = await adapter.ingest_account(
        account_id="conn_1",
        provider="feishu",
        entity_id="user_1",
        content_cb=_capture_sink(captured),
    )

    assert result.ingested == 0
    assert result.skipped == 2
    assert captured == []


async def test_ingest_account_changed_etag_reingests(monkeypatch):
    hub = FakeHub()
    hub.listings["conn_1"] = [
        {"doc_id": "dox1", "title": "Q3 规划", "doc_type": "docx", "updated_at": "v2"}
    ]
    hub.contents["conn_1:dox1"] = {"doc_id": "dox1", "content": "## 更新后"}

    store = FakeBindingStore()
    binding = await store.upsert(entity_id="user_1", provider="feishu", hub_account_id="conn_1")
    binding.sync_metadata = {"seen": {"dox1": "v1"}}
    patch_binding_store(monkeypatch, store)

    captured: list[dict] = []
    adapter = HubAdapter(hub)
    result = await adapter.ingest_account(
        account_id="conn_1",
        provider="feishu",
        entity_id="user_1",
        content_cb=_capture_sink(captured),
    )

    assert result.ingested == 1
    assert captured[0]["content"] == "## 更新后"


async def test_ingest_account_v1_no_version_falls_back_to_doc_id(monkeypatch):
    """Totem v1 search_docs output carries no version field: without one,
    dedup keys on the doc_id — a changed doc is skipped (known v1
    limitation, re-scan sees the same id)."""
    hub = FakeHub()
    hub.listings["conn_1"] = [{"doc_id": "dox1", "title": "Q3 规划", "doc_type": "docx"}]
    hub.contents["conn_1:dox1"] = {"doc_id": "dox1", "content": "## 正文"}

    store = FakeBindingStore()
    binding = await store.upsert(entity_id="user_1", provider="feishu", hub_account_id="conn_1")
    binding.sync_metadata = {"seen": {"dox1": "dox1"}}
    patch_binding_store(monkeypatch, store)

    captured: list[dict] = []
    adapter = HubAdapter(hub)
    result = await adapter.ingest_account(
        account_id="conn_1",
        provider="feishu",
        entity_id="user_1",
        content_cb=_capture_sink(captured),
    )
    assert result.ingested == 0
    assert result.skipped == 1


async def test_handle_event_syncs_for_change_event(monkeypatch):
    hub = FakeHub()
    hub.listings["conn_1"] = _feishu_listing()
    hub.contents["conn_1:dox1"] = {"doc_id": "dox1", "content": "## 正文"}
    hub.contents["conn_1:dox2"] = {"doc_id": "dox2", "content": "## Roadmap body"}

    store = FakeBindingStore()
    await store.upsert(entity_id="user_1", provider="feishu", hub_account_id="conn_1")
    patch_binding_store(monkeypatch, store)

    captured: list[dict] = []
    adapter = HubAdapter(hub)
    event = HubEvent(
        event_type="doc.changed",
        provider="feishu",
        account_id="conn_1",
    )
    result = await adapter.handle_event(event, content_cb=_capture_sink(captured))

    assert result.ingested == 2
    assert result.provider == "feishu"


async def test_handle_event_resolves_internal_uuid_to_external_id(monkeypatch):
    """P1-1: handle_event must pass the entity's external_id to the pipeline.

    The binding stores the internal UUID (FK to entities.id); the pipeline
    resolves entities by external_id. Passing the UUID caused
    ``Entity not found`` for every event-driven ingestion.
    """
    hub = FakeHub()
    hub.listings["conn_1"] = [
        {"doc_id": "dox1", "title": "Q3 规划", "doc_type": "docx", "updated_at": "v1"}
    ]
    hub.contents["conn_1:dox1"] = {"doc_id": "dox1", "content": "## 正文"}

    store = FakeBindingStore()
    internal_uuid = "550e8400-e29b-41d4-a716-446655440000"
    await store.upsert(entity_id=internal_uuid, provider="feishu", hub_account_id="conn_1")
    store.entity_external[internal_uuid] = "user_1"
    patch_binding_store(monkeypatch, store)

    captured: list[dict] = []
    adapter = HubAdapter(hub)
    event = HubEvent(
        event_type="doc.changed",
        provider="feishu",
        account_id="conn_1",
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
        provider="feishu",
        hub_account_id="conn_1",
    )
    store.missing_entities.add("550e8400-e29b-41d4-a716-446655440001")
    patch_binding_store(monkeypatch, store)

    adapter = HubAdapter(hub)
    event = HubEvent(
        event_type="doc.changed",
        provider="feishu",
        account_id="conn_1",
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
        event_type="doc.changed",
        provider="feishu",
        account_id="ghost",
    )
    result = await adapter.handle_event(event, content_cb=_capture_sink([]))
    assert result.ingested == 0
    assert result.errors == ["no binding for account"]


async def test_handle_event_connected_marks_binding_active(monkeypatch):
    hub = FakeHub()
    store = FakeBindingStore()
    binding = await store.upsert(entity_id="user_1", provider="feishu", hub_account_id="conn_1")
    binding.sync_status = "revoked"
    patch_binding_store(monkeypatch, store)

    adapter = HubAdapter(hub)
    event = HubEvent(
        event_type="connection.created",
        provider="feishu",
        account_id="conn_1",
    )
    result = await adapter.handle_event(event, content_cb=None)
    assert result.ingested == 0
    assert (await store.get_by_account("conn_1")).sync_status == "active"


async def test_handle_event_connection_deleted_marks_binding_revoked(monkeypatch):
    hub = FakeHub()
    store = FakeBindingStore()
    binding = await store.upsert(entity_id="user_1", provider="feishu", hub_account_id="conn_1")
    binding.sync_status = "active"
    patch_binding_store(monkeypatch, store)

    adapter = HubAdapter(hub)
    event = HubEvent(
        event_type="connection.deleted",
        provider="feishu",
        account_id="conn_1",
    )
    result = await adapter.handle_event(event, content_cb=None)
    assert result.ingested == 0
    assert (await store.get_by_account("conn_1")).sync_status == "revoked"


async def test_unknown_provider_raises():
    import pytest

    hub = FakeHub()
    adapter = HubAdapter(hub)
    with pytest.raises(ValueError, match="slack"):
        await adapter.ingest_account(account_id="conn_1", provider="slack", entity_id="user_1")
