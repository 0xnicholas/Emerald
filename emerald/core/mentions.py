"""Mention extraction — named-entity mentions attached to memories (B3 NER).

A **Mention** is a named thing (person / organization / location /
technology / datetime / role / concept) that a memory talks about. Mentions
are extracted during ingestion — by the LLM fact-extraction path (per-fact)
or by the deterministic rule path (gazetteer) — and stored in the knowledge
graph as Mention nodes linked to memories via MENTIONS edges.

Terminology (spec #21, pending /domain-modeling in CONTEXT.md):
- **Entity** = the namespace a memory belongs to (e.g. a user).
- **Mention** = a named thing a memory talks about, resolved within exactly
  one Entity's context pool. Never shared across entities.

Ticket scope (#22/#23/#24, B3 T1-T3): the happy path, cross-memory
resolution — different surface forms of the same thing resolve to one
canonical Mention node per entity, with surface forms accumulating as
aliases (dedup key (entity_id, canonical_form, type)) — plus the closed
mention-type taxonomy and confidence gating: types outside the taxonomy
fall back to ``concept`` and below-threshold mentions are dropped at
attach time. Entity-scoped reads and cross-entity isolation landed in
#25 (get_entity_mentions); UPDATES integration (#26) and forgetting (#27)
build on this module.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

# Default extraction confidence for the deterministic rule path.
DEFAULT_RULE_CONFIDENCE = 0.9

# Confidence gating (#24): mentions below this threshold are dropped at
# attach time — they produce no Mention node and no MENTIONS edge. The
# boundary is inclusive (== threshold is kept). The rule path emits
# DEFAULT_RULE_CONFIDENCE, the LLM path 0.5-0.95 by prompt design, so the
# gate only cuts genuinely uncertain extractions.
MENTION_CONFIDENCE_THRESHOLD = 0.5

# Closed mention-type taxonomy (spec #21 / ticket #24).
# Defined here so the graph schema and every extraction path share one
# source of truth; ``normalize_mention_type`` is the single validation
# funnel (spec #21: "校验；非法 → concept(other) 或丢弃").
VALID_MENTION_TYPES = frozenset(
    {
        "person",
        "organization",
        "location",
        "technology",
        "datetime",
        "role",
        "concept",
    }
)

# Spec #21's parenthetical synonyms — "technology(or product)",
# "role(or title)", "concept(other)" — map into the canonical classes.
MENTION_TYPE_ALIASES: dict[str, str] = {
    "product": "technology",
    "title": "role",
    "other": "concept",
}


def coerce_confidence(value: Any, default: float = 0.9) -> float:
    """Parse and clamp a confidence value into [0.0, 1.0].

    Shared by every mention path (rule extraction emits a fixed value,
    LLM extraction parses model output, the graph layer re-checks before
    gating) so the coercion rules cannot drift between them (#24).
    Unparseable input falls back to ``default``.
    """
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = default
    return max(0.0, min(1.0, confidence))


def normalize_mention_type(value: str) -> str:
    """Normalize a mention type into the closed taxonomy (#24).

    Strips and lowercases the input, maps the spec's parenthetical
    synonyms into their canonical classes, and falls back to ``concept``
    for anything outside the taxonomy — malformed types never reach the
    graph.
    """
    key = str(value).strip().lower()
    if key in VALID_MENTION_TYPES:
        return key
    return MENTION_TYPE_ALIASES.get(key, "concept")


@dataclass
class Mention:
    """A named entity mentioned by a memory (B3 NER).

    Attributes:
        surface_form:   how the thing appears in this memory (e.g. "谷歌").
        canonical_form: the canonical name of the thing (e.g. "Google").
        type:           closed-taxonomy class (person/organization/.../concept).
        confidence:     extraction confidence in [0.0, 1.0].
    """

    surface_form: str
    canonical_form: str = ""
    type: str = "concept"
    confidence: float = 0.9

    def __post_init__(self) -> None:
        # A mention without an explicit canonical form is its own canonical form.
        if not self.canonical_form:
            self.canonical_form = self.surface_form

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe serialization (Redis/Celery transport, Cypher params)."""
        return {
            "surface_form": self.surface_form,
            "canonical_form": self.canonical_form,
            "type": self.type,
            "confidence": self.confidence,
        }


class MentionExtractor(ABC):
    """Extracts mentions from a piece of text."""

    @abstractmethod
    def extract(self, text: str) -> list[Mention]:
        """Return the mentions found in ``text``.

        Rule/mock paths must be deterministic: the same text yields the same
        mentions in the same order (quality suite asserts exact graph
        structure, so ordering is part of the contract).
        """


# Default gazetteer for the rule path — canonical form + type per surface
# key (matched case-insensitively). The set is intentionally modest:
# the rule path is a deterministic fallback, not a full NER system.
DEFAULT_KNOWN_ENTITIES: dict[str, tuple[str, str]] = {
    "python": ("Python", "technology"),
    "rust": ("Rust", "technology"),
    "typescript": ("TypeScript", "technology"),
    "fastapi": ("FastAPI", "technology"),
    "postgresql": ("PostgreSQL", "technology"),
    "neo4j": ("Neo4j", "technology"),
    "redis": ("Redis", "technology"),
    "docker": ("Docker", "technology"),
    "kubernetes": ("Kubernetes", "technology"),
    "macbook": ("MacBook", "technology"),
    "notion": ("Notion", "technology"),
    "vs code": ("VS Code", "technology"),
    "iphone": ("iPhone", "technology"),
    "android": ("Android", "technology"),
    "google": ("Google", "organization"),
    "谷歌": ("Google", "organization"),
    "stripe": ("Stripe", "organization"),
    "openai": ("OpenAI", "organization"),
    "anthropic": ("Anthropic", "organization"),
    "github": ("GitHub", "organization"),
    "alice": ("Alice", "person"),
}


class RuleMentionExtractor(MentionExtractor):
    """Deterministic gazetteer-based mention extraction (no LLM).

    Matches known surface forms case-insensitively and returns one mention
    per known entity per text, ordered by first occurrence. The surface form
    keeps the original casing found in the text (e.g. "GOOGLE"), while the
    canonical form and type come from the gazetteer.
    """

    def __init__(
        self,
        known_entities: dict[str, tuple[str, str]] | None = None,
        confidence: float = DEFAULT_RULE_CONFIDENCE,
    ) -> None:
        self._known = known_entities if known_entities is not None else DEFAULT_KNOWN_ENTITIES
        self._confidence = confidence

    def extract(self, text: str) -> list[Mention]:
        if not text or not text.strip():
            return []

        matches: list[tuple[int, str, str, str]] = []
        for key, (canonical, mention_type) in self._known.items():
            # ASCII keys match on word boundaries ("rust" must not fire
            # inside "trust"); CJK keys have no such boundary and match
            # as-is. Case-insensitive on the original text so the surface
            # form keeps the author's casing.
            pattern = re.compile(
                rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])",
                re.IGNORECASE,
            )
            match = pattern.search(text)
            if match is None:
                continue
            matches.append(
                (
                    match.start(),
                    match.group(0),
                    canonical,
                    mention_type,
                )
            )
        # Deterministic order: first occurrence in the text; stable sort
        # keeps gazetteer insertion order for ties.
        matches.sort(key=lambda m: m[0])
        return [
            Mention(
                surface_form=surface,
                canonical_form=canonical,
                type=mention_type,
                confidence=self._confidence,
            )
            for _start, surface, canonical, mention_type in matches
        ]
