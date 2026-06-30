"""V2 re-export of V1 sessions router.

When a breaking change is needed for this resource, replace this file
with a concrete V2 implementation instead of importing from V1.
"""

from emerald.api.routes.v1.sessions import router

__all__ = ["router"]
