"""Profile API schemas — entity profile models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProfileFact(BaseModel):
    content: str
    importance: float = 1.0  # For static facts
    relevance: float = 1.0   # For dynamic facts
    source: str = ""
    acquired_at: str = ""


class ProfileResponse(BaseModel):
    entity_id: str
    static: list[ProfileFact] = Field(default_factory=list)
    dynamic: list[ProfileFact] = Field(default_factory=list)
    memory_count: int = 0
    computed_at: str = ""
    version: int = 1


class ProfileConfig(BaseModel):
    static_max_items: int = Field(default=10, ge=1, le=50)
    dynamic_max_items: int = Field(default=5, ge=1, le=20)
    dynamic_lookback_days: int = Field(default=7, ge=1, le=90)
    min_confidence_static: float = Field(default=0.5, ge=0.0, le=1.0)
    min_confidence_dynamic: float = Field(default=0.3, ge=0.0, le=1.0)
