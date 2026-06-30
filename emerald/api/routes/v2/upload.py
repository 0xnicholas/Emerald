"""V2 re-export of V1 upload router.

When a breaking change is needed for this resource, replace this file
with a concrete V2 implementation instead of importing from V1.
"""

from emerald.api.routes.v1 import upload as _v1_upload
from emerald.api.routes.v1.upload import router

# Re-export the per-entity authorization helper so security tests can
# patch it on the v2 module — the v2 route uses the same body as v1.
_authorize_entity = _v1_upload._authorize_entity
_get_minio_client = _v1_upload._get_minio_client

__all__ = ["router", "_authorize_entity", "_get_minio_client"]
