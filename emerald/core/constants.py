"""Core constants and enums used across Emerald.

These are internal implementation details; they are not exposed through the
public SDK surface (add / search / profile / upload).
"""

from __future__ import annotations

from enum import Enum


class MemoryStage(str, Enum):
    """Lifecycle stage of a memory or raw chunk.

    - ``fast_lane``: raw, coarse chunk that is searchable immediately after
      ingestion, before full extraction/relationship building completes.
    - ``extracted``: facts have been extracted but not yet indexed in the
      vector store.
    - ``indexed``: fully processed and available through normal search.
    - ``archived``: no longer surfaced in search (superseded or stale fast lane).
    """

    FAST_LANE = "fast_lane"
    EXTRACTED = "extracted"
    INDEXED = "indexed"
    ARCHIVED = "archived"


class InternalMemoryType(str, Enum):
    """Fine-grained internal memory type tags.

    These are produced automatically by the extraction layer and used for
    internal ranking, conflict detection, and profiling. They are **not**
    exposed through the public SDK / API surface.
    """

    FACT = "fact"
    PREFERENCE = "preference"
    EPISODIC = "episodic"
    DECISION = "decision"
    COMMITMENT = "commitment"
    GOAL = "goal"
    INSTRUCTION = "instruction"
    LEARNING = "learning"
    ERROR = "error"
    OBSERVATION = "observation"
    RELATIONSHIP = "relationship"
    CONTEXT = "context"
    ARTIFACT = "artifact"
