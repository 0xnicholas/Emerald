"""Emerald Python SDK — minimal, declarative client for the memory API.

AGENTS.md principle: "SDK 各语言方法名、参数结构、返回类型一一对应"
"""

from emerald.sdk.client import EmeraldClient
from emerald.sdk.models import (
    AddResult,
    SearchResult,
    SearchResults,
    ProfileFact,
    Profile,
    HealthStatus,
)

__all__ = [
    "EmeraldClient",
    "AddResult",
    "SearchResult",
    "SearchResults",
    "ProfileFact",
    "Profile",
    "HealthStatus",
]
