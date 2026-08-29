"""Structured data (JSON/CSV) ingestion — engine-level seam tests.

Agreed seam (spec issue #1): ``MemoryEngine.add`` with default registries,
in-memory stores, and a deterministic embedder. Only external behavior is
asserted — the memories that land in the graph — never chunker internals.
"""

from __future__ import annotations

import json

import pytest

from emerald.core.embedder import MockEmbeddingProvider
from emerald.core.engine import MemoryEngine
from emerald.core.graph import GraphStore
from emerald.core.vector import VectorStore


@pytest.fixture
def engine():
    """MemoryEngine with default registries + in-memory stores (no DB)."""
    return MemoryEngine(
        embedder=MockEmbeddingProvider(dimension=128),
        graph=GraphStore(use_db=False),
        vector=VectorStore(use_db=False),
        use_db=False,
    )


async def _contents(engine, memory_ids: list[str]) -> list[str]:
    """Fetch stored memory contents for the given IDs."""
    return [
        (await engine.graph.get_memory(mid))["content"]
        for mid in memory_ids
    ]


# ---- JSON: auto-detection + structural chunking ----

@pytest.mark.asyncio
async def test_json_array_auto_detected_large_records_chunked_per_record(engine):
    """A JSON array added without content_type is sniffed and chunked per record.

    Records larger than the batch budget must each become their own memory.
    """
    records = [
        {"name": "张三", "team": "支付基础设施", "note": "记录" * 1200},
        {"name": "李四", "team": "认证团队", "note": "记录" * 1200},
        {"name": "王五", "team": "图谱团队", "note": "记录" * 1200},
    ]
    result = await engine.add(json.dumps(records, ensure_ascii=False), entity_id="user_123")

    assert result.pipeline_status == "done"
    assert len(result.memory_ids) == 3, "large records must not be batched together"

    contents = await _contents(engine, result.memory_ids)
    for record in records:
        # Each memory holds exactly one record's data.
        assert any(record["name"] in c and record["team"] in c for c in contents)
        for c in contents:
            assert c.count(record["name"]) <= 1


@pytest.mark.asyncio
async def test_json_array_small_records_batched_into_bounded_chunks(engine):
    """Small records are merged into bounded batches, not one chunk per record."""
    records = [{"id": i, "note": "短记录"} for i in range(50)]
    result = await engine.add(json.dumps(records, ensure_ascii=False), entity_id="user_123")

    assert result.pipeline_status == "done"
    assert result.memory_ids, "records must not be lost"
    assert len(result.memory_ids) < 50, "small records must be batched"

    contents = "".join(await _contents(engine, result.memory_ids))
    for i in range(50):
        assert f'"id": {i}' in contents, f"record {i} must survive ingestion"


@pytest.mark.asyncio
async def test_json_object_chunked_by_top_level_key(engine):
    """A JSON object is chunked per top-level key — each key is a memory."""
    payload = {"用户": "张三", "项目": "Emerald", "组织": "示例公司"}
    result = await engine.add(json.dumps(payload, ensure_ascii=False), entity_id="user_123")

    assert result.pipeline_status == "done"
    assert len(result.memory_ids) == 3

    contents = await _contents(engine, result.memory_ids)
    keys = set()
    for c in contents:
        parsed = json.loads(c)
        assert isinstance(parsed, dict) and len(parsed) == 1
        keys.update(parsed.keys())
    assert keys == {"用户", "项目", "组织"}


# ---- CSV: auto-detection + header-preserving chunking ----

@pytest.mark.asyncio
async def test_csv_auto_detected_header_preserved(engine):
    """CSV added without content_type is sniffed; header stays with its rows."""
    csv_text = "季度,营收,利润\nQ1,100,20\nQ2,150,30\nQ3,200,40"
    result = await engine.add(csv_text, entity_id="user_123")

    assert result.pipeline_status == "done"
    assert len(result.memory_ids) == 1
    content = (await _contents(engine, result.memory_ids))[0]
    assert content.startswith("季度,营收,利润")
    assert "Q3,200,40" in content


@pytest.mark.asyncio
async def test_csv_many_rows_each_chunk_carries_header(engine):
    """Large CSVs split into multiple chunks; every chunk keeps the header."""
    header = "季度,营收,利润,备注"
    rows = "\n".join(f"Q{i},{i * 10},{i * 2},{'x' * 50}" for i in range(1, 61))
    result = await engine.add(header + "\n" + rows, entity_id="user_123")

    assert result.pipeline_status == "done"
    assert len(result.memory_ids) >= 2, "large CSV must split into multiple chunks"

    contents = await _contents(engine, result.memory_ids)
    assert all(c.startswith(header) for c in contents), "every chunk must carry the header"
    joined = "".join(contents)
    assert "Q60,600,120" in joined, "all rows must survive ingestion"


@pytest.mark.asyncio
async def test_csv_without_header_rows_kept(engine):
    """Headerless CSV data is ingested intact."""
    csv_text = "100,20\n150,30\n200,40"
    result = await engine.add(csv_text, entity_id="user_123")

    assert result.pipeline_status == "done"
    content = "".join(await _contents(engine, result.memory_ids))
    assert "150,30" in content
    assert "200,40" in content


@pytest.mark.asyncio
async def test_prose_with_inconsistent_commas_not_sniffed_as_csv(engine):
    """Prose whose lines have different comma counts must stay text."""
    prose = "hello, world, how are you\nfine, thanks"
    result = await engine.add(prose, entity_id="user_123")

    assert result.pipeline_status == "done"
    assert result.memory_ids, "prose must still be ingested"


@pytest.mark.asyncio
async def test_single_line_with_commas_not_sniffed_as_csv(engine):
    """A single line with commas is not tabular data."""
    result = await engine.add("a, b, c", entity_id="user_123")

    assert result.pipeline_status == "done"
    assert result.memory_ids
    content = (await _contents(engine, result.memory_ids))[0]
    assert content == "a, b, c"


@pytest.mark.asyncio
async def test_csv_semicolon_delimited_detected(engine):
    """Semicolon-delimited tabular data is sniffed as CSV."""
    csv_text = "城市;人口;面积\n北京;2189万;16410\n上海;2487万;6340"
    result = await engine.add(csv_text, entity_id="user_123")

    assert result.pipeline_status == "done"
    content = "".join(await _contents(engine, result.memory_ids))
    assert content.startswith("城市;人口;面积")
    assert "上海;2487万;6340" in content


# ---- Robustness: malformed input, empty payloads, bounded batching ----

@pytest.mark.asyncio
async def test_malformed_json_declared_type_falls_back_to_text(engine):
    """Malformed JSON with an explicit json type must not break the pipeline."""
    result = await engine.add("{这不是合法的 JSON", entity_id="user_123", content_type="json")

    assert result.pipeline_status == "done"
    assert result.memory_ids, "fallback must still index the content"
    content = (await _contents(engine, result.memory_ids))[0]
    assert "这不是合法的 JSON" in content


@pytest.mark.asyncio
async def test_malformed_csv_declared_type_falls_back_to_text(engine):
    """Malformed CSV with an explicit csv type must not break the pipeline."""
    result = await engine.add("只有一行,没有结构\n第二行,但字段,数,不,一致", entity_id="user_123", content_type="csv")

    assert result.pipeline_status == "done"
    assert result.memory_ids


@pytest.mark.asyncio
async def test_csv_inconsistent_fields_falls_back_to_text(engine):
    """CSV whose rows disagree on field count is rejected as malformed and
    falls back to text chunking — no bogus header-prefixed chunks."""
    csv_text = "季度,营收\nQ1,100\nQ2,150,80,多了一个字段"
    result = await engine.add(csv_text, entity_id="user_123", content_type="csv")

    assert result.pipeline_status == "done"
    assert result.memory_ids
    content = "".join(await _contents(engine, result.memory_ids))
    assert "多了一个字段" in content, "fallback must keep all content"


@pytest.mark.asyncio
async def test_prose_with_late_inconsistent_line_not_sniffed_as_csv(engine):
    """Sniffing checks every line: consistent first lines must not mask a
    differing later line (user story 14)."""
    prose = "a, b, c\nd, e, f\ng, h, i\n最后一句话没有逗号"
    result = await engine.add(prose, entity_id="user_123")

    assert result.pipeline_status == "done"
    assert result.memory_ids
    content = (await _contents(engine, result.memory_ids))[0]
    assert "最后一句话没有逗号" in content


@pytest.mark.asyncio
async def test_empty_json_array_yields_no_memories(engine):
    """An empty JSON array is valid structure with nothing to remember."""
    result = await engine.add("[]", entity_id="user_123")

    assert result.pipeline_status == "done"
    assert result.memory_ids == []


@pytest.mark.asyncio
async def test_empty_content_raises_typed_error(engine):
    """Empty/whitespace content is rejected with the established typed error
    (EmptyContentError) — sniffing must resolve to text and not mask it."""
    from emerald.core.exceptions import EmptyContentError

    with pytest.raises(EmptyContentError):
        await engine.add("   \n  ", entity_id="user_123")


# ---- Explicit content_type precedence ----

@pytest.mark.asyncio
async def test_explicit_json_type_ingests_without_error(engine):
    """Explicit content_type=json must never raise UnsupportedContentType."""
    result = await engine.add('{"a": 1, "b": 2}', entity_id="user_123", content_type="json")

    assert result.pipeline_status == "done"
    assert len(result.memory_ids) == 2


@pytest.mark.asyncio
async def test_explicit_csv_type_ingests_without_error(engine):
    """Explicit content_type=csv must never raise UnsupportedContentType."""
    result = await engine.add("a,b\n1,2\n3,4", entity_id="user_123", content_type="csv")

    assert result.pipeline_status == "done"
    assert result.memory_ids


@pytest.mark.asyncio
async def test_explicit_text_never_sniffed(engine):
    """Explicit content_type=text keeps JSON-looking content on the text path."""
    result = await engine.add('{"a": 1, "b": 2}', entity_id="user_123", content_type="text")

    assert result.pipeline_status == "done"
    assert len(result.memory_ids) == 1
    content = (await _contents(engine, result.memory_ids))[0]
    assert content == '{"a": 1, "b": 2}'


@pytest.mark.asyncio
async def test_mime_string_content_type_through_engine(engine):
    """A MIME string content_type (as uploads carry) reaches the json chunker."""
    result = await engine.add(
        '{"a": 1, "b": 2}',
        entity_id="user_123",
        content_type="application/json",
    )

    assert result.pipeline_status == "done"
    assert len(result.memory_ids) == 2


@pytest.mark.asyncio
async def test_mime_string_csv_through_engine(engine):
    """text/csv content_type reaches the csv chunker."""
    result = await engine.add(
        "a,b\n1,2\n3,4",
        entity_id="user_123",
        content_type="text/csv",
    )

    assert result.pipeline_status == "done"
    content = "".join(await _contents(engine, result.memory_ids))
    assert "3,4" in content


# ---- Source provenance (spec req 8): chunk metadata on stored memories ----

@pytest.mark.asyncio
async def test_json_chunk_provenance_persisted_on_memory(engine):
    """Structured chunk source metadata (record index/path) is stored on the
    memory so search results can be traced back to the original record."""
    result = await engine.add(
        '{"用户": "张三", "项目": "Emerald"}',
        entity_id="user_123",
    )
    assert len(result.memory_ids) == 2

    for mid in result.memory_ids:
        memory = await engine.graph.get_memory(mid)
        source = (memory.get("metadata") or {}).get("chunk_source")
        assert source is not None, "structured chunk provenance must be stored"
        assert source["kind"] == "json_object_key"
        assert source["key"] in {"用户", "项目"}


@pytest.mark.asyncio
async def test_csv_chunk_provenance_persisted_on_memory(engine):
    """CSV chunk provenance records the original row range."""
    result = await engine.add(
        "季度,营收\nQ1,100\nQ2,150",
        entity_id="user_123",
    )
    assert result.memory_ids

    memory = await engine.graph.get_memory(result.memory_ids[0])
    source = (memory.get("metadata") or {}).get("chunk_source")
    assert source is not None
    assert source["kind"] == "csv_rows"
    assert source["start_row"] == 2
    assert source["row_count"] == 2


@pytest.mark.asyncio
async def test_caller_metadata_kept_alongside_chunk_source(engine):
    """Caller metadata is preserved when chunk provenance is attached."""
    result = await engine.add(
        '{"a": 1}',
        entity_id="user_123",
        metadata={"session_id": "s1"},
    )

    memory = await engine.graph.get_memory(result.memory_ids[0])
    assert memory["metadata"]["session_id"] == "s1"
    assert "chunk_source" in memory["metadata"]


@pytest.mark.asyncio
async def test_text_memories_keep_plain_metadata(engine):
    """Non-structured content is unaffected: no chunk_source is attached."""
    result = await engine.add(
        "普通文本内容",
        entity_id="user_123",
        metadata={"session_id": "s1"},
    )

    memory = await engine.graph.get_memory(result.memory_ids[0])
    assert memory["metadata"] == {"session_id": "s1"}
