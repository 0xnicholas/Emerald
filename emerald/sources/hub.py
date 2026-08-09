"""Connection Hub — the abstract boundary between Emerald and external providers.

Emerald never talks to provider APIs directly. All external content flows
through a connection hub (ADR-0004): OAuth, credential storage, sync and
webhook renewal are the hub's job. This module defines the *interface*
Emerald depends on; concrete hubs (StackOne is the first) implement it.

Swapping the hub must only require: a new implementation of this ABC, a
factory entry, and config. Nothing else in Emerald may reference a
concrete hub.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ConnectSession:
    """A short-lived account-linking session created on the hub.

    ``url`` is where the end user should be sent to authorize.
    """

    id: str
    url: str
    token: str
    expires_in: int = 1800
    provider: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class HubAccount:
    """A linked account (an end user's connection to one provider)."""

    id: str
    provider: str
    origin_owner_id: str
    status: str = "active"  # active | revoked | error
    created_at: datetime | None = None


@dataclass
class HubEvent:
    """A normalized inbound event delivered by the hub.

    ``raw_payload`` keeps the hub-specific body so adapters can pull
    what they need without the interface losing fidelity.
    """

    event_type: str  # e.g. "account.connected", "file.changed"
    provider: str
    account_id: str
    origin_owner_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    raw: bytes = b""


class ConnectionHubError(Exception):
    """Base error for hub interactions."""


class ConnectionHubAuthError(ConnectionHubError):
    """Hub rejected our credentials."""


class ConnectionHub(ABC):
    """The contract Emerald requires from any connection hub."""

    @abstractmethod
    async def create_connect_session(
        self,
        *,
        origin_owner_id: str,
        origin_owner_name: str,
        provider: str,
        metadata: dict[str, Any] | None = None,
    ) -> ConnectSession:
        """Open the account-linking flow for an entity on one provider."""

    @abstractmethod
    async def list_accounts(self, origin_owner_id: str) -> list[HubAccount]:
        """List linked accounts belonging to an entity."""

    @abstractmethod
    async def execute_action(
        self,
        *,
        account_id: str,
        action: str,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute one action against a linked account (hub's RPC layer)."""

    @abstractmethod
    async def verify_webhook(
        self,
        raw_body: bytes,
        headers: Mapping[str, str],
    ) -> bool:
        """Verify an inbound webhook delivery's signature.

        Implementations must hash the raw request bytes and compare in
        constant time.
        """

    @abstractmethod
    async def parse_event(self, raw_body: bytes) -> HubEvent:
        """Parse a verified webhook delivery into a HubEvent."""
