"""Unit tests for the B6 duplicate detection + veto guardrail layer (T1, #42).

The seam under test is the pure-function layer: ``select_representative``
and ``decide_pair`` — inputs are memory dicts, precomputed trust scores
and protection features, outputs are verdicts. Per the ticket's
acceptance criteria, tests assert the full veto matrix (profile /
high-importance / contradiction / cross-type / cross-entity / history /
UPDATES-edge pairs are all vetoed), representative selection's
deterministic total order, and input-order independence; they never
touch the graph store or the vector store.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from emerald.core.community import IMPORTANCE_THRESHOLD, MemoryFeatures
from emerald.core.duplicates import (
    DuplicateAction,
    DuplicateCandidate,
    DuplicateConfig,
    DuplicateVerdict,
    decide_pair,
    select_representative,
)

NOW = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


def _mem(
    mid: str,
    *,
    content: str = "用户住在北京",
    entity_id: str = "e1",
    memory_type: str = "fact",
    is_latest: bool = True,
    confidence: float = 0.8,
    created_at: datetime | None = None,
) -> dict:
    """A graph-shaped memory record (in-memory backend shape)."""
    return {
        "id": mid,
        "entity_id": entity_id,
        "content": content,
        "memory_type": memory_type,
        "is_latest": is_latest,
        "confidence": confidence,
        "provenance": "explicit_statement",
        "validation_count": 0,
        "contradiction_detected": False,
        "created_at": created_at if created_at is not None else NOW,
    }


def _feat(profile_referenced: bool = False, importance: float = 0.0) -> MemoryFeatures:
    return MemoryFeatures(profile_referenced=profile_referenced, importance=importance)


def _candidate(
    a: dict,
    b: dict,
    *,
    trust_a: float = 0.8,
    trust_b: float = 0.8,
    contradiction: bool = False,
    has_updates_edge: bool = False,
    features_a: MemoryFeatures | None = None,
    features_b: MemoryFeatures | None = None,
) -> DuplicateCandidate:
    return DuplicateCandidate(
        memory_a=a,
        memory_b=b,
        similarity=1.0,
        features_a=features_a or _feat(),
        features_b=features_b or _feat(),
        trust_a=trust_a,
        trust_b=trust_b,
        has_updates_edge=has_updates_edge,
        contradiction=contradiction,
    )


# ---- representative selection: deterministic total order ----


@pytest.mark.asyncio
async def test_representative_highest_trust_wins():
    """Trust score desc is the primary key."""
    older_high = _mem("a", confidence=0.9, created_at=NOW)
    newer_low = _mem("b", confidence=0.3, created_at=NOW)
    assert select_representative([older_high, newer_low], {"a": 0.9, "b": 0.3}) == "a"


@pytest.mark.asyncio
async def test_representative_newest_wins_on_trust_tie():
    """created_at desc breaks trust ties."""
    old = _mem("a", created_at=datetime(2026, 1, 1, tzinfo=UTC))
    new = _mem("b", created_at=datetime(2026, 8, 1, tzinfo=UTC))
    assert select_representative([old, new], {"a": 0.8, "b": 0.8}) == "b"


@pytest.mark.asyncio
async def test_representative_smallest_id_wins_on_full_tie():
    """id asc breaks the final tie — the total order is complete."""
    a = _mem("a", created_at=NOW)
    b = _mem("b", created_at=NOW)
    assert select_representative([b, a], {"a": 0.8, "b": 0.8}) == "a"


@pytest.mark.asyncio
async def test_representative_order_independent():
    """Input list order never changes the outcome."""
    a = _mem("a", confidence=0.9, created_at=NOW)
    b = _mem("b", confidence=0.7, created_at=NOW)
    trust = {"a": 0.9, "b": 0.7}
    assert select_representative([a, b], trust) == select_representative([b, a], trust) == "a"


@pytest.mark.asyncio
async def test_representative_missing_trust_scores_zero():
    """A memory without a trust score competes as 0.0."""
    a = _mem("a", confidence=0.9, created_at=NOW)
    b = _mem("b", confidence=0.9, created_at=NOW)
    assert select_representative([a, b], {"b": 0.9}) == "b"


@pytest.mark.asyncio
async def test_representative_empty_raises():
    with pytest.raises(ValueError):
        select_representative([], {})


# ---- the veto matrix: every guardrail has a deterministic counter-example ----


@pytest.mark.asyncio
async def test_duplicate_pair_consolidates_with_representative():
    """A clean near-duplicate pair consolidates; the representative is the
    higher-trust memory and the verdict records it."""
    a = _mem("a", confidence=0.9)
    b = _mem("b", confidence=0.7)
    verdict = decide_pair(_candidate(a, b, trust_a=0.9, trust_b=0.7))

    assert verdict.action is DuplicateAction.CONSOLIDATE
    assert verdict.representative_id == "a"
    assert verdict.reason is None


@pytest.mark.asyncio
async def test_profile_referenced_pair_vetoed():
    """Profile-referenced memories are exempt (reuses _is_protected)."""
    a = _mem("a")
    b = _mem("b")
    verdict = decide_pair(_candidate(a, b, features_a=_feat(profile_referenced=True)))

    assert verdict.action is DuplicateAction.EXEMPT_PROFILE
    assert verdict.reason == "protected"
    assert verdict.representative_id is None


@pytest.mark.asyncio
async def test_high_importance_pair_vetoed():
    """Importance at/above the threshold is exempt; below it is not."""
    a = _mem("a")
    b = _mem("b")
    high = decide_pair(_candidate(a, b, features_b=_feat(importance=IMPORTANCE_THRESHOLD)))
    low = decide_pair(_candidate(a, b, features_b=_feat(importance=IMPORTANCE_THRESHOLD - 0.1)))

    assert high.action is DuplicateAction.EXEMPT_PROFILE
    assert low.action is DuplicateAction.CONSOLIDATE


@pytest.mark.asyncio
async def test_importance_threshold_is_configurable():
    """The exemption threshold is a calibration seam (D2)."""
    a = _mem("a")
    b = _mem("b")
    candidate = _candidate(a, b, features_b=_feat(importance=0.6))

    assert decide_pair(candidate, importance_threshold=0.5).action is DuplicateAction.EXEMPT_PROFILE
    assert decide_pair(candidate, importance_threshold=0.9).action is DuplicateAction.CONSOLIDATE


@pytest.mark.asyncio
async def test_contradiction_pair_vetoed():
    """A pair the relationship rules would classify as UPDATES is a
    timeline step, never a duplicate."""
    a = _mem("a")
    b = _mem("b")
    verdict = decide_pair(_candidate(a, b, contradiction=True))

    assert verdict.action is DuplicateAction.EXEMPT_CONTRADICTION
    assert verdict.reason == "contradiction"


@pytest.mark.asyncio
async def test_cross_type_pair_vetoed():
    """Same content in different memory types never merges."""
    a = _mem("a", memory_type="fact")
    b = _mem("b", memory_type="preference")
    verdict = decide_pair(_candidate(a, b))

    assert verdict.action is DuplicateAction.EXEMPT_TYPE
    assert verdict.reason == "memory_type"


@pytest.mark.asyncio
async def test_cross_entity_pair_vetoed():
    """Entity isolation (ADR-0002): a pair from different entities is kept."""
    a = _mem("a", entity_id="e1")
    b = _mem("b", entity_id="e2")
    verdict = decide_pair(_candidate(a, b))

    assert verdict.action is DuplicateAction.KEEP
    assert verdict.reason == "entity_isolation"


@pytest.mark.asyncio
async def test_history_pair_vetoed():
    """A pair where either side is historical (is_latest=false) is kept —
    history never re-enters consolidation."""
    a = _mem("a", is_latest=True)
    b = _mem("b", is_latest=False)
    verdict = decide_pair(_candidate(a, b))

    assert verdict.action is DuplicateAction.KEEP
    assert verdict.reason == "history_participation"


@pytest.mark.asyncio
async def test_updates_edge_pair_vetoed():
    """An existing UPDATES edge marks a temporal chain — merging would
    destroy timeline semantics."""
    a = _mem("a")
    b = _mem("b")
    verdict = decide_pair(_candidate(a, b, has_updates_edge=True))

    assert verdict.action is DuplicateAction.EXEMPT_UPDATES
    assert verdict.reason == "updates_edge"


@pytest.mark.asyncio
async def test_guardrail_priority_is_fixed():
    """The guardrail order follows spec #41 / ADR-0006 (实体隔离 /
    is_latest / memory_type / 画像引用豁免 / 矛盾否决 / UPDATES 边否决):
    type mismatch beats protection, protection beats contradiction."""
    a = _mem("a", memory_type="fact")
    b = _mem("b", memory_type="preference")
    verdict = decide_pair(_candidate(a, b, contradiction=True))
    assert verdict.action is DuplicateAction.EXEMPT_TYPE

    a = _mem("a")
    b = _mem("b")
    verdict = decide_pair(
        _candidate(a, b, contradiction=True, features_a=_feat(profile_referenced=True))
    )
    assert verdict.action is DuplicateAction.EXEMPT_PROFILE

    # Protection also beats the UPDATES-edge veto.
    verdict = decide_pair(
        _candidate(a, b, has_updates_edge=True, features_a=_feat(profile_referenced=True))
    )
    assert verdict.action is DuplicateAction.EXEMPT_PROFILE


# ---- purity / determinism ----


@pytest.mark.asyncio
async def test_decide_pair_is_pure_and_order_independent():
    """Same inputs → same verdict, regardless of which side is 'a'."""
    a = _mem("a", confidence=0.9)
    b = _mem("b", confidence=0.7)

    first = decide_pair(_candidate(a, b, trust_a=0.9, trust_b=0.7))
    second = decide_pair(_candidate(a, b, trust_a=0.9, trust_b=0.7))
    assert first == second

    # Swapping the sides must not change the decision, the representative
    # or the canonical pair order.
    swapped = decide_pair(_candidate(b, a, trust_a=0.7, trust_b=0.9))
    assert swapped.action is first.action
    assert swapped.representative_id == first.representative_id == "a"
    assert swapped.candidate.ids == first.candidate.ids


@pytest.mark.asyncio
async def test_config_rejects_degenerate_values():
    with pytest.raises(ValueError):
        DuplicateConfig(similarity_threshold=0.0)
    with pytest.raises(ValueError):
        DuplicateConfig(similarity_threshold=1.5)
    with pytest.raises(ValueError):
        DuplicateConfig(candidate_top_k=0)
    with pytest.raises(ValueError):
        DuplicateConfig(max_memories=0)
    with pytest.raises(ValueError):
        DuplicateConfig(importance_threshold=-0.1)
    with pytest.raises(ValueError):
        DuplicateConfig(importance_threshold=1.1)


@pytest.mark.asyncio
async def test_verdict_reports_candidate_and_similarity():
    candidate = _candidate(_mem("a"), _mem("b"))
    verdict: DuplicateVerdict = decide_pair(candidate)
    assert verdict.candidate is candidate
    assert verdict.candidate.similarity == 1.0
    assert verdict.candidate.ids == ("a", "b")
