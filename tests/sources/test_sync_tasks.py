"""Tests for connection hub fallback sync tasks (sources/tasks.py)."""

from __future__ import annotations

from emerald.sources.tasks import _run_sync_all
from tests.sources.fake_hub import FakeBindingStore, FakeHub, patch_binding_store


async def test_sync_all_resolves_external_id_before_ingestion(monkeypatch):
    """P1-1: the sweep must pass the entity's external_id to the pipeline.

    ``sync_all_bindings_task`` is the fallback path when webhook events are
    missed; it must use the same external_id convention as the pipeline.
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

    async def _sink(*, content, content_type, entity_id, metadata=None):
        captured.append({"content": content, "entity_id": entity_id})

    import emerald.sources.adapter as adapter_mod

    monkeypatch.setattr(adapter_mod, "default_content_cb", lambda: _sink)
    monkeypatch.setattr(
        "emerald.sources.tasks.get_hub", lambda: hub
    )

    result = await _run_sync_all(None)

    assert result["synced"] == 1
    assert captured[0]["entity_id"] == "user_1"
    assert captured[0]["entity_id"] != internal_uuid


async def test_sync_all_missing_entity_records_error_not_crash(monkeypatch):
    """A binding whose entity is gone must not abort the sweep."""
    store = FakeBindingStore()
    await store.upsert(
        entity_id="550e8400-e29b-41d4-a716-446655440001",
        provider="googledrive",
        hub_account_id="acc_1",
    )
    store.missing_entities.add("550e8400-e29b-41d4-a716-446655440001")
    patch_binding_store(monkeypatch, store)

    import emerald.sources.adapter as adapter_mod

    monkeypatch.setattr(adapter_mod, "default_content_cb", lambda: None)
    monkeypatch.setattr("emerald.sources.tasks.get_hub", lambda: FakeHub())

    result = await _run_sync_all(None)
    assert result["synced"] == 1
    assert "entity for binding not found" in result["results"][0]["error"]
