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

Ticket scope (#22, B3 T1): the happy path. Cross-memory resolution of
different surface forms to one canonical node (#23), closed-taxonomy
validation and confidence gating (#24), cross-entity isolation tests (#25),
UPDATES integration (#26) and forgetting (#27) build on this module.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

# Default extraction confidence for the deterministic rule path.
DEFAULT_RULE_CONFIDENCE = 0.9

# Closed mention-type taxonomy (spec #21 / ticket #24).
# Defined here so the graph schema and every extraction path share one
# source of truth. Full validation/gating behavior lands in #24; #22 keeps
# types as-provided (LLM) or gazetteer-declared (rule path).
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
