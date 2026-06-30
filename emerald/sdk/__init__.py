"""Emerald Python SDK — minimal, declarative client for the memory API.

AGENTS.md principle: "SDK 各语言方法名、参数结构、返回类型一一对应"
"""

from emerald.sdk.client import EmeraldClient
from emerald.sdk.exceptions import (
    EmeraldAuthError,
    EmeraldError,
    EmeraldNetworkError,
    EmeraldNotFoundError,
    EmeraldRateLimitError,
    EmeraldServerError,
    EmeraldValidationError,
)
from emerald.sdk.models import (
    AddResult,
    HealthStatus,
    Profile,
    ProfileFact,
    SearchResult,
    SearchResults,
)

__all__ = [
    "EmeraldClient",
    "AddResult",
    "SearchResult",
    "SearchResults",
    "ProfileFact",
    "Profile",
    "HealthStatus",
    # Typed exceptions (P1.2c)
    "EmeraldError",
    "EmeraldAuthError",
    "EmeraldNotFoundError",
    "EmeraldValidationError",
    "EmeraldRateLimitError",
    "EmeraldServerError",
    "EmeraldNetworkError",
]
