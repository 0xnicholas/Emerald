"""Unit tests for the B5 community activity scoring + decision rules (#38).

The seam under test is the pure-function layer: ``score_communities``,
``find_bridge_memories`` and ``decide_communities`` — inputs are a
partition, adjacency and per-memory features, outputs are scores and
per-community verdicts. Per the ticket's acceptance criteria, tests
assert the decision matrix (forget / keep / exempt_bridge /
exempt_profile) and determinism; they never touch the graph store.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from emerald.core.community import (
    ACTIVITY_THRESHOLD,
    IMPORTANCE_THRESHOLD,
    ActivityWeights,
    CommunityAction,
    MemoryFeatures,
    decide_communities,
    find_bridge_memories,
    forgotten_memories,
    score_communities,
)

NOW = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


def _partition(*groups: list[str]) -> dict[str, str]:
    """Build a memory_id → community_id partition from member groups."""
    partition: dict[str, str] = {}
    for index, group in enumerate(groups):
        for mid in group:
            partition[mid] = f"c{index}"
    return partition


def _adj(edges: list[tuple[str, str]]) -> dict[str, set[str]]:
    """Build symmetric adjacency from undirected edge pairs."""
    adjacency: dict[str, set[str]] = {}
    for first, second in edges:
        adjacency.setdefault(first, set()).add(second)
        adjacency.setdefault(second, set()).add(first)
    return adjacency


def _feat(
    confidence: float = 0.8,
    created_at: datetime | None = None,
    last_accessed_at: datetime | None = None,
    profile_referenced: bool = False,
    importance: float = 0.0,
) -> MemoryFeatures:
    return MemoryFeatures(
        confidence=confidence,
        created_at=created_at if created_at is not None else NOW,
        last_accessed_at=last_accessed_at,
        profile_referenced=profile_referenced,
        importance=importance,
    )


# ---- activity scoring ----


@pytest.mark.asyncio
async def test_score_full_strength_community():
    """Recent, dense, fully confident community scores the weighted sum."""
    partition = _partition(["a", "b"])
    adjacency = _adj([("a", "b")])
    features = {"a": _feat(confidence=1.0), "b": _feat(confidence=1.0)}

    score = score_communities(partition, adjacency, features, now=NOW)["c0"]
    # 0.3*1 + 0.3*1 + 0.2*1 + 0.2*0
    assert score == pytest.approx(0.8)


@pytest.mark.asyncio
async def test_score_old_memories_decay():
    """Recency decays exponentially with the newest touch time (30d half-life)."""
    old = NOW - timedelta(days=90)
    partition = _partition(["a", "b"])
    adjacency = _adj([("a", "b")])
    features = {
        "a": _feat(confidence=0.5, created_at=old),
        "b": _feat(confidence=0.5, created_at=old),
    }

    score = score_communities(partition, adjacency, features, now=NOW)["c0"]
    # 0.3*0.5 + 0.3*2**(-3) + 0.2*1 + 0.2*0
    assert score == pytest.approx(0.3 * 0.5 + 0.3 * 0.125 + 0.2)


@pytest.mark.asyncio
async def test_score_singleton_has_no_density_bonus():
    """A singleton community has zero internal edges, hence density 0."""
    partition = _partition(["lonely"])
    features = {"lonely": _feat(confidence=0.8)}

    score = score_communities(partition, {}, features, now=NOW)["c0"]
    # 0.3*0.8 + 0.3*1 + 0.2*0 + 0.2*0
    assert score == pytest.approx(0.24 + 0.3)


@pytest.mark.asyncio
async def test_score_profile_fraction():
    """The profile component is the fraction of referenced members."""
    partition = _partition(["a", "b"])
    adjacency = _adj([("a", "b")])
    features = {
        "a": _feat(confidence=0.5, profile_referenced=True),
        "b": _feat(confidence=0.5),
    }

    score = score_communities(partition, adjacency, features, now=NOW)["c0"]
    # 0.3*0.5 + 0.3*1 + 0.2*1 + 0.2*0.5
    assert score == pytest.approx(0.15 + 0.3 + 0.2 + 0.1)


@pytest.mark.asyncio
async def test_score_last_access_beats_creation():
    """Recency uses the latest of last_accessed_at / created_at."""
    old = NOW - timedelta(days=90)
    partition = _partition(["a"])
    features = {"a": _feat(confidence=0.5, created_at=old, last_accessed_at=NOW)}

    score = score_communities(partition, {}, features, now=NOW)["c0"]
    assert score == pytest.approx(0.3 * 0.5 + 0.3)  # recency 1.0


@pytest.mark.asyncio
async def test_score_custom_weights():
    """Weights are configurable and pure."""
    partition = _partition(["a", "b"])
    adjacency = _adj([("a", "b")])
    features = {"a": _feat(confidence=0.7), "b": _feat(confidence=0.9)}
    weights = ActivityWeights(confidence=1.0, recency=0.0, density=0.0, profile=0.0)

    score = score_communities(partition, adjacency, features, now=NOW, weights=weights)["c0"]
    assert score == pytest.approx(0.8)  # pure mean confidence


@pytest.mark.asyncio
async def test_score_importance_threshold_is_configurable():
    """The protection predicate threshold is shared and overridable."""
    partition = _partition(["a", "b"])
    adjacency = _adj([("a", "b")])
    features = {
        "a": _feat(confidence=0.5, importance=0.6),
        "b": _feat(confidence=0.5),
    }

    strict = score_communities(partition, adjacency, features, now=NOW, importance_threshold=0.9)[
        "c0"
    ]
    lax = score_communities(partition, adjacency, features, now=NOW, importance_threshold=0.5)["c0"]
    assert strict == pytest.approx(0.15 + 0.3 + 0.2)  # no protected member
    assert lax == pytest.approx(0.15 + 0.3 + 0.2 + 0.1)  # half protected

    verdicts = decide_communities(
        partition, adjacency, features, {"c0": 0.1}, importance_threshold=0.5
    )
    assert verdicts["c0"].action is CommunityAction.EXEMPT_PROFILE


@pytest.mark.asyncio
async def test_weights_reject_degenerate_configs():
    with pytest.raises(ValueError):
        ActivityWeights(confidence=-0.1)
    with pytest.raises(ValueError):
        ActivityWeights(confidence=0.0, recency=0.0, density=0.0, profile=0.0)


@pytest.mark.asyncio
async def test_score_empty_partition():
    assert score_communities({}, {}, {}, now=NOW) == {}


# ---- bridge detection ----


@pytest.mark.asyncio
async def test_bridge_spans_two_communities():
    """A memory whose neighbors live in ≥2 distinct communities is a bridge."""
    partition = _partition(["x", "a"], ["b"])
    adjacency = _adj([("x", "a"), ("x", "b")])

    assert find_bridge_memories(partition, adjacency) == {"x"}


@pytest.mark.asyncio
async def test_internal_node_is_not_a_bridge():
    partition = _partition(["x", "a", "b"])
    adjacency = _adj([("x", "a"), ("x", "b"), ("a", "b")])

    assert find_bridge_memories(partition, adjacency) == set()


@pytest.mark.asyncio
async def test_isolated_node_is_not_a_bridge():
    partition = _partition(["x"], ["a", "b"])
    adjacency = _adj([("a", "b")])

    assert find_bridge_memories(partition, adjacency) == set()


@pytest.mark.asyncio
async def test_neighbors_outside_own_community_count():
    """Neighbors in two *other* communities still make a bridge."""
    partition = _partition(["x"], ["a"], ["b"])
    adjacency = _adj([("x", "a"), ("x", "b")])

    assert find_bridge_memories(partition, adjacency) == {"x"}


# ---- decision matrix ----


@pytest.mark.asyncio
async def test_threshold_sides_decide_forget_or_keep():
    partition = _partition(["a"], ["b"])
    adjacency = _adj([("a", "b")])
    features = {"a": _feat(), "b": _feat()}
    scores = {"c0": ACTIVITY_THRESHOLD - 0.01, "c1": ACTIVITY_THRESHOLD + 0.01}

    verdicts = decide_communities(partition, adjacency, features, scores)
    assert verdicts["c0"].action is CommunityAction.FORGET
    assert verdicts["c1"].action is CommunityAction.KEEP


@pytest.mark.asyncio
async def test_threshold_boundary_is_keep():
    partition = _partition(["a"])
    verdicts = decide_communities(partition, {}, {"a": _feat()}, {"c0": ACTIVITY_THRESHOLD})
    assert verdicts["c0"].action is CommunityAction.KEEP


@pytest.mark.asyncio
async def test_bridge_community_exempt_bridge_memory_kept():
    """A low-activity community holding a bridge is not wholly forgotten;
    the bridge is reported, its community partially forgotten."""
    # x ∈ c0 bridges into c1 (sole member c); only x spans two communities.
    partition = _partition(["x", "a"], ["c"])
    adjacency = _adj([("x", "a"), ("x", "c")])
    features = {"x": _feat(), "a": _feat(), "c": _feat()}
    scores = {"c0": 0.1, "c1": 0.1}

    verdicts = decide_communities(partition, adjacency, features, scores)
    assert verdicts["c0"].action is CommunityAction.EXEMPT_BRIDGE
    assert verdicts["c0"].bridge_memory_ids == ("x",)
    assert verdicts["c1"].action is CommunityAction.FORGET

    # The bridge itself survives; only the non-bridge cohort is forgotten.
    assert forgotten_memories(partition, verdicts) == {"a", "c"}


@pytest.mark.asyncio
async def test_profile_referenced_community_exempt():
    partition = _partition(["a", "b"])
    adjacency = _adj([("a", "b")])
    features = {
        "a": _feat(profile_referenced=True),
        "b": _feat(),
    }
    scores = {"c0": 0.1}

    verdicts = decide_communities(partition, adjacency, features, scores)
    assert verdicts["c0"].action is CommunityAction.EXEMPT_PROFILE
    assert verdicts["c0"].protected_memory_ids == ("a",)


@pytest.mark.asyncio
async def test_high_importance_community_exempt_below_not():
    high = _partition(["h"])
    low = _partition(["l"])
    features = {
        "h": _feat(importance=IMPORTANCE_THRESHOLD),
        "l": _feat(importance=IMPORTANCE_THRESHOLD - 0.1),
    }
    scores = {"c0": 0.1, "c1": 0.1}

    verdicts = decide_communities(high, {}, features, scores)
    assert verdicts["c0"].action is CommunityAction.EXEMPT_PROFILE

    verdicts = decide_communities(low, {}, features, scores)
    assert verdicts["c0"].action is CommunityAction.FORGET


@pytest.mark.asyncio
async def test_profile_protection_beats_bridge_exemption():
    """A low community holding both signals reports the profile reason."""
    partition = _partition(["x", "a"], ["b"])
    adjacency = _adj([("x", "a"), ("x", "b")])
    features = {"x": _feat(profile_referenced=True), "a": _feat(), "b": _feat()}
    scores = {"c0": 0.1, "c1": 0.1}

    verdicts = decide_communities(partition, adjacency, features, scores)
    assert verdicts["c0"].action is CommunityAction.EXEMPT_PROFILE
    assert verdicts["c0"].bridge_memory_ids == ("x",)
    assert verdicts["c1"].action is CommunityAction.FORGET


@pytest.mark.asyncio
async def test_healthy_communities_keep_without_exemption_label():
    """Exemption only fires when it changes the outcome: healthy communities
    with bridges or profile references are plain KEEP."""
    partition = _partition(["x", "a"], ["b", "p"])
    adjacency = _adj([("x", "a"), ("x", "b")])
    features = {
        "x": _feat(),
        "a": _feat(),
        "b": _feat(),
        "p": _feat(profile_referenced=True),
    }
    scores = {"c0": 0.9, "c1": 0.9}

    verdicts = decide_communities(partition, adjacency, features, scores)
    assert verdicts["c0"].action is CommunityAction.KEEP
    assert verdicts["c0"].bridge_memory_ids == ("x",)
    assert verdicts["c1"].action is CommunityAction.KEEP
    assert verdicts["c1"].protected_memory_ids == ("p",)


@pytest.mark.asyncio
async def test_verdict_reports_size_and_score():
    partition = _partition(["a", "b", "c"])
    scores = {"c0": 0.42}

    verdict = decide_communities(partition, {}, {}, scores)["c0"]
    assert verdict.size == 3
    assert verdict.activity_score == 0.42


# ---- forgotten-members projection (T3 seam) ----


@pytest.mark.asyncio
async def test_forgotten_members_matrix():
    """forget → all; exempt_bridge → non-bridge only; profile/keep → none."""
    partition = _partition(["f1", "f2"], ["x", "b"], ["p"], ["k"])
    adjacency = _adj([("x", "b"), ("x", "k")])
    features = {"p": _feat(profile_referenced=True)}
    scores = {"c0": 0.1, "c1": 0.1, "c2": 0.1, "c3": 0.9}

    verdicts = decide_communities(partition, adjacency, features, scores)
    # c1: x bridges into c3 (k); b is its cohort.
    assert verdicts["c1"].action is CommunityAction.EXEMPT_BRIDGE
    assert forgotten_memories(partition, verdicts) == {"f1", "f2", "b"}


@pytest.mark.asyncio
async def test_bridge_only_community_forgets_nothing():
    """A community that is nothing but a bridge loses no members."""
    # x is alone in c0 but spans c1 and c2 — a pure hub community.
    partition = _partition(["x"], ["a"], ["b"])
    adjacency = _adj([("x", "a"), ("x", "b")])
    scores = {"c0": 0.1, "c1": 0.1, "c2": 0.1}

    verdicts = decide_communities(partition, adjacency, {}, scores)
    assert verdicts["c0"].action is CommunityAction.EXEMPT_BRIDGE
    assert verdicts["c0"].bridge_memory_ids == ("x",)
    assert forgotten_memories(partition, verdicts) == {"a", "b"}


# ---- determinism ----


@pytest.mark.asyncio
async def test_decisions_are_pure_and_order_independent():
    partition = _partition(["x", "a"], ["b", "c"])
    adjacency = _adj([("x", "a"), ("x", "b"), ("b", "c")])
    features = {"x": _feat(), "a": _feat(), "b": _feat(), "c": _feat()}
    scores = {"c0": 0.1, "c1": 0.6}

    first = decide_communities(partition, adjacency, features, scores)
    second = decide_communities(partition, adjacency, features, scores)
    assert first == second

    # Insertion order of the inputs must not matter.
    shuffled = {mid: partition[mid] for mid in reversed(list(partition))}
    reshuffled = decide_communities(shuffled, adjacency, features, scores)
    assert reshuffled == first

    # Scoring is equally deterministic.
    assert score_communities(partition, adjacency, features, now=NOW) == score_communities(
        shuffled, adjacency, features, now=NOW
    )


@pytest.mark.asyncio
async def test_empty_partition_decides_nothing():
    assert decide_communities({}, {}, {}, {}) == {}
