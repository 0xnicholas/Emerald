"""Tests for the memory trust model."""

from datetime import UTC, datetime, timedelta

import pytest

from emerald.core.trust import Provenance, compute_trust_score


@pytest.mark.parametrize(
    "provenance,expected_min",
    [
        (Provenance.EXPLICIT_STATEMENT, 0.79),
        (Provenance.VALIDATED, 0.75),
        (Provenance.OBSERVED, 0.67),
        (Provenance.CORRECTED, 0.71),
        (Provenance.IMPORTED, 0.63),
        (Provenance.INFERRED, 0.55),
    ],
)
def test_provenance_weights(provenance, expected_min):
    """Lower-provenance memories receive lower trust scores."""
    memory = {
        "confidence": 0.8,
        "provenance": provenance.value,
        "validation_count": 0,
        "contradiction_detected": False,
        "is_latest": True,
        "memory_type": "fact",
        "created_at": datetime.now(UTC),
    }
    score = compute_trust_score(memory)
    assert score >= expected_min
    assert score <= 1.0


def test_validation_boost():
    """Each validation increases trust, up to a cap."""
    base = {
        "confidence": 0.8,
        "provenance": Provenance.EXPLICIT_STATEMENT.value,
        "validation_count": 0,
        "contradiction_detected": False,
        "is_latest": True,
        "memory_type": "fact",
        "created_at": datetime.now(UTC),
    }
    score_0 = compute_trust_score(base)
    base["validation_count"] = 1
    score_1 = compute_trust_score(base)
    base["validation_count"] = 10
    score_10 = compute_trust_score(base)

    assert score_1 > score_0
    assert score_10 > score_1
    assert score_10 <= 1.0


def test_contradiction_penalty():
    """Contradicted memories get a very low trust score."""
    memory = {
        "confidence": 0.9,
        "provenance": Provenance.EXPLICIT_STATEMENT.value,
        "validation_count": 5,
        "contradiction_detected": True,
        "is_latest": True,
        "memory_type": "fact",
        "created_at": datetime.now(UTC),
    }
    score = compute_trust_score(memory)
    assert score <= 0.3


def test_superseded_or_not_latest_zero():
    """Superseded / not-latest memories have zero trust."""
    memory = {
        "confidence": 0.9,
        "provenance": Provenance.EXPLICIT_STATEMENT.value,
        "validation_count": 0,
        "contradiction_detected": False,
        "is_latest": False,
        "memory_type": "fact",
        "created_at": datetime.now(UTC),
    }
    assert compute_trust_score(memory) == 0.0

    memory["is_latest"] = True
    memory["status"] = "superseded"
    assert compute_trust_score(memory) == 0.0


def test_age_decay_for_preferences():
    """Preferences and observations decay with age."""
    old = {
        "confidence": 0.8,
        "provenance": Provenance.EXPLICIT_STATEMENT.value,
        "validation_count": 0,
        "contradiction_detected": False,
        "is_latest": True,
        "memory_type": "preference",
        "created_at": datetime.now(UTC) - timedelta(days=120),
    }
    recent = {**old, "created_at": datetime.now(UTC) - timedelta(days=5)}

    assert compute_trust_score(old) < compute_trust_score(recent)


def test_facts_do_not_decay():
    """Facts are not subject to age decay."""
    old_fact = {
        "confidence": 0.8,
        "provenance": Provenance.EXPLICIT_STATEMENT.value,
        "validation_count": 0,
        "contradiction_detected": False,
        "is_latest": True,
        "memory_type": "fact",
        "created_at": datetime.now(UTC) - timedelta(days=200),
    }
    recent_fact = {**old_fact, "created_at": datetime.now(UTC) - timedelta(days=5)}

    assert compute_trust_score(old_fact) == pytest.approx(
        compute_trust_score(recent_fact), abs=1e-6
    )
