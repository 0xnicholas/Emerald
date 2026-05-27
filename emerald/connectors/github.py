"""GitHub connector — repository and issue sync via GitHub App / OAuth.

Supports GitHub OAuth App flow (not GitHub App installation flow).
Webhooks are validated via HMAC-SHA256 using the webhook secret.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx
import structlog

from emerald.config import get_settings
from emerald.connectors.auth import decrypt_credentials, encrypt_credentials
from emerald.connectors.base import (
    BaseConnector,
    ConnectorCredentials,
    ConnectorStatus,
    SyncMode,
    SyncResult,
)

logger = structlog.get_logger(__name__)

GITHUB_OAUTH_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_OAUTH_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_BASE = "https://api.github.com"


class GitHubConnector(BaseConnector):
    """Syncs GitHub repositories, code, issues, PRs, and discussions."""

    provider = "github"

    def __init__(self, entity_id: str) -> None:
        self.entity_id = entity_id
        self.credentials: ConnectorCredentials | None = None
        self._client: httpx.AsyncClient | None = None

    # ---- OAuth ----

    async def get_auth_url(self, redirect_uri: str) -> tuple[str, str]:
        """Generate GitHub OAuth authorization URL.

        Returns (auth_url, state_token).
        """
        settings = get_settings()
        if not settings.github_client_id:
            raise RuntimeError("GitHub client ID not configured")

        state = hashlib.sha256(
            f"{self.entity_id}:{datetime.now(UTC).isoformat()}".encode()
        ).hexdigest()[:32]

        params = {
            "client_id": settings.github_client_id,
            "redirect_uri": redirect_uri,
            "scope": "repo read:user",
            "state": state,
        }
        auth_url = f"{GITHUB_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"

        logger.info(
            "github.oauth.auth_url_generated",
            entity_id=self.entity_id,
            state=state[:8],
        )
        return auth_url, state

    async def handle_callback(
        self, code: str, state: str
    ) -> ConnectorCredentials:
        """Exchange GitHub authorization code for access token."""
        settings = get_settings()
        if not settings.github_client_secret:
            raise RuntimeError("GitHub client secret not configured")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                GITHUB_OAUTH_ACCESS_TOKEN_URL,
                headers={"Accept": "application/json"},
                data={
                    "client_id": settings.github_client_id,
                    "client_secret": settings.github_client_secret,
                    "code": code,
                    "redirect_uri": "",  # Optional for token exchange
                },
            )
            response.raise_for_status()
            data = response.json()

        if "error" in data:
            raise RuntimeError(f"GitHub OAuth error: {data['error_description']}")

        access_token = data["access_token"]
        scopes = data.get("scope", "").split(",") if data.get("scope") else []

        creds = ConnectorCredentials(
            access_token=access_token,
            token_type=data.get("token_type", "Bearer"),
            scopes=scopes,
        )
        self.credentials = creds

        logger.info(
            "github.oauth.token_exchanged",
            entity_id=self.entity_id,
            scopes=scopes,
        )
        return creds

    # ---- Sync ----

    async def sync(self, mode: SyncMode = SyncMode.INCREMENTAL) -> SyncResult:
        """Sync GitHub repositories accessible to the user.

        Current implementation fetches the authenticated user's repositories
        and ingests code and markdown files via the pipeline.
        """
        if not self.credentials:
            raise RuntimeError("GitHub credentials not available")

        client = self._get_api_client()
        result = SyncResult(provider="github")

        try:
            # Fetch user repos
            repos = await self._fetch_repos(client)
            logger.info(
                "github.sync.repos_fetched",
                entity_id=self.entity_id,
                repo_count=len(repos),
            )

            for repo in repos:
                repo_name = repo["full_name"]
                try:
                    files_synced = await self._sync_repo(client, repo_name)
                    result.files_synced += files_synced
                except Exception as exc:
                    logger.warning(
                        "github.sync.repo_failed",
                        repo=repo_name,
                        error=str(exc),
                    )
                    result.files_failed += 1
                    result.errors.append(f"{repo_name}: {exc}")

        except Exception as exc:
            logger.error("github.sync.failed", error=str(exc))
            result.errors.append(str(exc))
        finally:
            await client.aclose()

        return result

    async def _fetch_repos(self, client: httpx.AsyncClient) -> list[dict]:
        """Fetch list of repos accessible to the authenticated user."""
        response = await client.get("/user/repos", params={"per_page": 100})
        response.raise_for_status()
        return response.json()

    async def _sync_repo(
        self, client: httpx.AsyncClient, repo_name: str
    ) -> int:
        """Sync a single repository: fetch file tree and ingest supported files.

        Returns number of files synced.
        """
        from emerald.pipeline.orchestrator import PipelineOrchestrator

        # Fetch default branch
        repo_resp = await client.get(f"/repos/{repo_name}")
        repo_resp.raise_for_status()
        default_branch = repo_resp.json().get("default_branch", "main")

        # Fetch tree recursively
        tree_resp = await client.get(
            f"/repos/{repo_name}/git/trees/{default_branch}",
            params={"recursive": "1"},
        )
        if tree_resp.status_code == 404:
            logger.warning("github.sync.repo_not_found", repo=repo_name)
            return 0
        tree_resp.raise_for_status()
        tree_data = tree_resp.json()

        supported_exts = {
            ".py", ".ts", ".js", ".tsx", ".jsx",
            ".go", ".rs", ".java", ".md", ".txt",
            ".json", ".yaml", ".yml",
        }
        files_synced = 0
        orchestrator = PipelineOrchestrator()

        for item in tree_data.get("tree", []):
            if item.get("type") != "blob":
                continue
            path = item.get("path", "")
            ext = "." + path.split(".")[-1].lower() if "." in path else ""
            if ext not in supported_exts:
                continue

            # Fetch file content
            content_resp = await client.get(
                f"/repos/{repo_name}/contents/{path}",
                params={"ref": default_branch},
            )
            if content_resp.status_code != 200:
                continue
            content_data = content_resp.json()
            import base64

            file_content = base64.b64decode(content_data.get("content", ""))

            # Detect content type
            content_type = "code"
            if ext == ".md":
                content_type = "markdown"
            elif ext in (".txt", ".json", ".yaml", ".yml"):
                content_type = "text"

            try:
                await orchestrator.process_async(
                    content=file_content,
                    content_type=content_type,
                    entity_id=self.entity_id,
                    document_id=f"github:{repo_name}:{path}",
                )
                files_synced += 1
            except Exception as exc:
                logger.warning(
                    "github.sync.file_failed",
                    repo=repo_name,
                    path=path,
                    error=str(exc),
                )

        logger.info(
            "github.sync.repo_complete",
            repo=repo_name,
            files_synced=files_synced,
        )
        return files_synced

    # ---- Webhook ----

    async def handle_webhook(
        self, payload: dict, signature: str
    ) -> bool:
        """Validate GitHub webhook signature and trigger sync.

        GitHub sends: X-Hub-Signature-256: sha256=<hex>
        """
        settings = get_settings()
        secret = settings.github_webhook_secret
        if not secret:
            logger.warning("github.webhook.no_secret", entity_id=self.entity_id)
            return False

        expected = "sha256=" + hmac.new(
            secret.encode(),
            payload.get("_raw_body", b""),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected, signature):
            logger.warning(
                "github.webhook.invalid_signature",
                entity_id=self.entity_id,
            )
            return False

        event_type = payload.get("action", "")
        repo_name = payload.get("repository", {}).get("full_name", "")

        logger.info(
            "github.webhook.received",
            github_event=event_type,
            repo=repo_name,
            entity_id=self.entity_id,
        )

        # Trigger incremental sync for push events
        if event_type in ("push", "synchronize"):
            logger.info(
                "github.webhook.triggering_sync",
                repo=repo_name,
                entity_id=self.entity_id,
            )
            return True

        return False

    # ---- Lifecycle ----

    async def revoke(self) -> None:
        """Revoke OAuth grant and clean up stored credentials."""
        if self.credentials:
            async with httpx.AsyncClient() as client:
                await client.delete(
                    "https://api.github.com/applications/"
                    f"{get_settings().github_client_id}/token",
                    auth=(
                        get_settings().github_client_id,
                        get_settings().github_client_secret,
                    ),
                    json={"access_token": self.credentials.access_token},
                )
            self.credentials = None

        logger.info("github.revoked", entity_id=self.entity_id)

    async def status(self) -> ConnectorStatus:
        """Return current connector status."""
        connected = self.credentials is not None
        return ConnectorStatus(
            provider="github",
            connected=connected,
            sync_status="active" if connected else "inactive",
            last_synced_at=None,
        )

    # ---- Helpers ----

    def _get_api_client(self) -> httpx.AsyncClient:
        """Return authenticated GitHub API client."""
        if not self.credentials:
            raise RuntimeError("Credentials not available")
        return httpx.AsyncClient(
            base_url=GITHUB_API_BASE,
            headers={
                "Authorization": f"Bearer {self.credentials.access_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            follow_redirects=True,
        )

    # ---- Credential persistence helpers ----

    def encrypt(self) -> bytes | None:
        """Encrypt current credentials for storage."""
        if self.credentials:
            return encrypt_credentials(self.credentials)
        return None

    @classmethod
    def decrypt(cls, encrypted: bytes, entity_id: str) -> "GitHubConnector":
        """Restore connector from encrypted credentials."""
        connector = cls(entity_id=entity_id)
        connector.credentials = decrypt_credentials(encrypted)
        return connector
