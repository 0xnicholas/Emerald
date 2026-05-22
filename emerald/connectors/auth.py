"""OAuth authentication utilities for connectors.

Handles AES-256-GCM encryption of credentials and token refresh logic.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from emerald.connectors.base import ConnectorCredentials
from emerald.config import get_settings


def _get_encryption_key() -> bytes:
    """Load the 32-byte AES-256 key from environment."""
    settings = get_settings()
    key_hex = settings.encryption_key
    if len(key_hex) != 64:
        raise ValueError(
            "ENCRYPTION_KEY must be 64 hex characters (32 bytes)"
        )
    return bytes.fromhex(key_hex)


def encrypt_credentials(credentials: ConnectorCredentials) -> bytes:
    """Encrypt connector credentials using AES-256-GCM.

    Returns nonce (12 bytes) + ciphertext.
    """
    key = _get_encryption_key()
    data = json.dumps({
        "access_token": credentials.access_token,
        "refresh_token": credentials.refresh_token,
        "token_type": credentials.token_type,
        "expires_at": credentials.expires_at.isoformat() if credentials.expires_at else None,
        "scopes": credentials.scopes,
    }).encode("utf-8")

    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, data, None)
    return nonce + ciphertext


def decrypt_credentials(encrypted: bytes) -> ConnectorCredentials:
    """Decrypt stored connector credentials."""
    key = _get_encryption_key()
    nonce = encrypted[:12]
    ciphertext = encrypted[12:]

    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    data = json.loads(plaintext)

    expires_at = None
    if data.get("expires_at"):
        expires_at = datetime.fromisoformat(data["expires_at"])

    return ConnectorCredentials(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token"),
        token_type=data.get("token_type", "Bearer"),
        expires_at=expires_at,
        scopes=data.get("scopes", []),
    )
