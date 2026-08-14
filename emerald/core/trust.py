"""Trust scoring for memories.

Computes a calibrated confidence score from provenance, validation history,
age, and contradiction state. Based on the trust model observed in MEMANTO
but adapted for Emerald's graph-first architecture.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any


class Provenance(str, Enum):
    """How a memory was obtained."""

    EXPLICIT_STATEMENT = "explicit_statement"
    VALIDATED = "validated"
    OBSERVED = "observed"
    CORRECTED = "corrected"
    IMPORTED = "imported"
    INFERRED = "inferred"


# Base weight applied to the stored confidence for each provenance type.
PROVENANCE_WEIGHTS: dict[Provenance, float] = {
    Provenance.EXPLICIT_STATEMENT: 1.0,
    Provenance.VALIDATED: 0.95,
    Provenance.OBSERVED: 0.85,
    Provenance.CORRECTED: 0.9,
    Provenance.IMPORTED: 0.8,
    Provenance.INFERRED: 0.7,
}

# Memory types whose relevance decays with age.
DECAYING_MEMORY_TYPES = {"preference", "observation", "episodic"}


def compute_trust_score(
    memory: dict[str, Any], *, now: datetime | None = None
) -> float:
    """Compute a trust score in [0, 1] for a memory dict.

    Factors:
      - provenance weight
      - validation_count boost (+0.03 per validation, max +0.15)
      - age decay for preference/observation/episodic memories
      - contradiction penalty (score * 0.3)
      - superseded status -> 0

    ``now`` is optional and defaults to the wall clock; callers that
    need determinism (B6 consolidation representative selection, #42:
    same graph + same inputs must yield the same decision) pass it
    explicitly.

    The returned score is independent of vector similarity; it should be
    multiplied into the search ranking score or used for profile weighting.
    """
    if memory.get("status") == "superseded" or memory.get("is_latest") is False:
        return 0.0

    if memory.get("contradiction_detected"):
        return max(0.1, memory.get("confidence", 0.8) * 0.3)

    provenance_str = memory.get("provenance", Provenance.EXPLICIT_STATEMENT.value)
    try:
        provenance = Provenance(provenance_str)
    except ValueError:
        provenance = Provenance.EXPLICIT_STATEMENT

    base_confidence = memory.get("confidence", 0.8)
    provenance_weight = PROVENANCE_WEIGHTS.get(provenance, 0.8)
    score = base_confidence * provenance_weight

    validation_count = memory.get("validation_count", 0) or 0
    score += min(0.15, validation_count * 0.03)

    memory_type = memory.get("memory_type", "fact")
    if memory_type in DECAYING_MEMORY_TYPES:
        created_at = memory.get("created_at")
        # Neo4j returns DateTime objects that expose a to_native() method.
        if created_at is not None and hasattr(created_at, "to_native"):
            created_at = created_at.to_native()
        if isinstance(created_at, datetime):
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            age_days = ((now or datetime.now(UTC)) - created_at).days
            if age_days > 90:
                score -= 0.2
            elif age_days > 30:
                score -= 0.1

    return max(0.0, min(1.0, score))
