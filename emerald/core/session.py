"""Session scope management — lightweight JWT session tokens.

Session tokens are optional. They let an agent/client scope a request to a
specific project or conversation session without giving up the master API key.
They do not replace API-key authentication; they ride alongside it via the
``X-Session-Token`` header.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import structlog

from emerald.config import get_settings

logger = structlog.get_logger(__name__)


class SessionManager:
    """Create and validate short-lived JWT session tokens."""

    def __init__(self, secret: str | None = None, algorithm: str = "HS256") -> None:
        settings = get_settings()
        self._secret = secret or settings.session_jwt_secret or settings.api_key_secret
        self._algorithm = algorithm

    def create_token(
        self,
        entity_id: str,
        *,
        project_id: str | None = None,
        session_id: str | None = None,
        ttl_hours: float = 24,
        extras: dict | None = None,
    ) -> str:
        """Create a signed JWT session token."""
        now = datetime.now(UTC)
        payload = {
            "iss": "emerald",
            "sub": entity_id,
            "jti": uuid4().hex,
            "iat": now,
            "exp": now + timedelta(hours=ttl_hours),
            "entity_id": entity_id,
        }
        if project_id:
            payload["project_id"] = project_id
        if session_id:
            payload["session_id"] = session_id
        if extras:
            payload.update(extras)

        token = jwt.encode(payload, self._secret, algorithm=self._algorithm)
        logger.info(
            "session.created",
            entity_id=entity_id,
            project_id=project_id,
            session_id=session_id,
        )
        return token

    def decode_token(self, token: str) -> dict:
        """Decode and validate a session token.

        Raises:
            ValueError: If the token is invalid or expired.
        """
        try:
            return jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                issuer="emerald",
            )
        except jwt.ExpiredSignatureError as exc:
            raise ValueError("Session token expired") from exc
        except jwt.InvalidTokenError as exc:
            raise ValueError(f"Invalid session token: {exc}") from exc
