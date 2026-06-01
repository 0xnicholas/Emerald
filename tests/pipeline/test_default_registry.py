"""Integration tests for default extractor/chunker registries.

Verifies that get_default_registry() returns fully populated registries
and that PipelineOrchestrator works out of the box without manual registration.
"""

import pytest

from emerald.pipeline.extraction import get_default_registry as get_default_extractors
from emerald.pipeline.chunking import get_default_registry as get_default_chunkers
from emerald.pipeline.orchestrator import PipelineOrchestrator


# ---- Default registry population ----

def test_default_extractor_registry_has_all_types():
    registry = get_default_extractors()
    expected = {"text", "code", "pdf", "url", "image", "audio", "video"}
    assert set(registry._extractors.keys()) == expected


def test_default_chunker_registry_has_all_types():
    registry = get_default_chunkers()
    expected = {"text", "code", "markdown", "pdf", "conversation"}
    assert set(registry._chunkers.keys()) == expected


# ---- PipelineOrchestrator out-of-the-box ----

@pytest.mark.asyncio
async def test_orchestrator_default_registries_work():
    """PipelineOrchestrator() without args uses default registries."""
    orch = PipelineOrchestrator(use_db=False)
    # Should be able to look up text extractor/chunker
    ext = orch.extractors.get("text")
    chk = orch.chunkers.get("text")
    assert ext.supports("text")
    assert chk.chunk("") == []
