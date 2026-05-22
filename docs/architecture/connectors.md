# 连接器架构

连接器负责将外部数据源（Google Drive、Gmail、Notion、GitHub 等）内容同步到 Emerald，使外部文档自动进入处理管线并融入知识图谱。

---

## 1. 架构概览

```
┌──────────────────────────────────────────────────┐
│                    连接器管理器                    │
│                                                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │ OAuth    │  │ Webhook  │  │ 定时同步  │        │
│  │ 模块     │  │ 处理器   │  │ 调度器    │        │
│  └──────────┘  └──────────┘  └──────────┘        │
│       │              │              │              │
│       ▼              ▼              ▼              │
│  ┌───────────────────────────────────────────┐    │
│  │              连接器基类接口                │    │
│  │  authenticate / sync / handle_webhook /   │    │
│  │  revoke / status                           │    │
│  └───────────────────────────────────────────┘    │
│                                                    │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌────────┐  │
│  │ Google  │ │ Gmail   │ │ Notion  │ │ GitHub │  │
│  │ Drive   │ │         │ │         │ │        │  │
│  └────┬────┘ └────┬────┘ └────┬────┘ └───┬────┘  │
│       │          │          │          │          │
└───────┼──────────┼──────────┼──────────┼──────────┘
        │          │          │          │
        ▼          ▼          ▼          ▼
   外部 OAuth API     Webhook 回调     定时轮询
        │          │          │          │
        └──────────┴──────────┴──────────┘
                      │
                      ▼
               Emerald 处理管线
```

---

## 2. 连接器基类

```python
# emerald/connectors/base.py

class BaseConnector(ABC):
    """所有连接器的基类"""

    provider: str                  # "google_drive" | "gmail" | "notion" | "github"
    entity_id: str
    credentials: ConnectorCredentials | None = None

    @abstractmethod
    async def get_auth_url(self, redirect_uri: str) -> tuple[str, str]:
        """
        获取 OAuth 授权 URL。
        返回 (auth_url, state_token)。
        """
        ...

    @abstractmethod
    async def handle_callback(self, code: str, state: str) -> ConnectorCredentials:
        """
        处理 OAuth 回调，用 code 换 token。
        返回 credentials。
        """
        ...

    @abstractmethod
    async def sync(self, mode: SyncMode = SyncMode.INCREMENTAL) -> SyncResult:
        """
        执行同步。
        - INCREMENTAL: 增量同步（webhook 或定时）
        - FULL: 全量同步（首次连接或手动触发）
        """
        ...

    @abstractmethod
    async def handle_webhook(self, payload: dict, signature: str) -> bool:
        """
        处理外部 Webhook 通知。
        返回 True 表示已触发同步。
        """
        ...

    @abstractmethod
    async def revoke(self) -> None:
        """撤销 OAuth 授权，清理本地 token。"""
        ...

    @abstractmethod
    async def status(self) -> ConnectorStatus:
        """返回连接器当前状态。"""
        ...


@dataclass
class ConnectorCredentials:
    access_token: str
    refresh_token: str | None
    token_type: str
    expires_at: datetime | None
    scopes: list[str]

@dataclass
class SyncResult:
    provider: str
    files_synced: int
    files_skipped: int         # 哈希去重
    files_failed: int
    duration_seconds: float
    errors: list[str]

class SyncMode(str, Enum):
    INCREMENTAL = "incremental"
    FULL = "full"

@dataclass
class ConnectorStatus:
    provider: str
    connected: bool
    sync_status: str            # "active" | "paused" | "revoked" | "error"
    last_synced_at: datetime | None
    error_message: str | None
```

---

## 3. OAuth 认证流程

### 3.1 完整流程

```
应用                    Emerald API              外部服务
 │                          │                        │
 │  POST /connectors/       │                        │
 │  {provider}/connect      │                        │
 │  ──────────────────────► │                        │
 │                          │ 生成 state_token       │
 │                          │ 构建 OAuth URL         │
 │  {auth_url, state}       │                        │
 │  ◄────────────────────── │                        │
 │                          │                        │
 │  用户浏览器 → auth_url ──────────────────────────►│
 │                          │                        │
 │  用户授权完成            │                        │
 │  ◄───────────────────────────────────────────────│
 │                          │                        │
 │  重定向到 callback       │                        │
 │  ?code=xxx&state=yyy     │                        │
 │  ──────────────────────► │                        │
 │                          │ 用 code 换 token─────► │
 │                          │ ◄───── access_token ── │
 │                          │                        │
 │                          │ 加密存储 credentials   │
 │                          │ 启动首次全量同步        │
 │                          │ 注册 Webhook（如支持）  │
 │  {status: "active"}      │                        │
 │  ◄────────────────────── │                        │
```

### 3.2 Token 安全存储

```python
# emerald/connectors/auth.py

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import os

# 加密密钥通过环境变量 ENCRYPTION_KEY 注入（64 位十六进制 = 32 bytes）
ENCRYPTION_KEY = bytes.fromhex(os.environ["ENCRYPTION_KEY"])

def encrypt_credentials(credentials: ConnectorCredentials) -> bytes:
    """AES-256-GCM 加密，每次加密使用随机 nonce"""
    data = json.dumps(vars(credentials)).encode("utf-8")
    nonce = os.urandom(12)
    aesgcm = AESGCM(ENCRYPTION_KEY)
    ciphertext = aesgcm.encrypt(nonce, data, None)
    return nonce + ciphertext  # 前 12 字节为 nonce

def decrypt_credentials(encrypted: bytes) -> ConnectorCredentials:
    nonce = encrypted[:12]
    ciphertext = encrypted[12:]
    aesgcm = AESGCM(ENCRYPTION_KEY)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return ConnectorCredentials(**json.loads(plaintext))
```

### 3.3 Token 刷新

```python
async def _refresh_if_needed(connector: BaseConnector):
    if not connector.credentials.refresh_token:
        return  # 无 refresh_token，需用户重新授权

    if connector.credentials.expires_at and \
       connector.credentials.expires_at > datetime.utcnow() + timedelta(minutes=5):
        return  # token 仍有 5 分钟以上有效期

    new_creds = await connector.refresh_token(connector.credentials.refresh_token)
    encrypted = encrypt_credentials(new_creds)
    await db.execute(
        update(ConnectorTable)
        .where(entity_id=..., provider=...)
        .values(credentials=encrypted)
    )
```

---

## 4. Webhook 处理

### 4.1 Webhook 端点

```
POST /v1/connectors/{provider}/webhook
```

请求头必须包含提供商的签名（如 `X-Goog-Channel-Token` 用于 Google，`X-Hub-Signature-256` 用于 GitHub）。

### 4.2 签名验证

```python
# emerald/api/routes/connectors.py

@router.post("/{provider}/webhook")
async def handle_webhook(
    provider: str,
    request: Request,
    db: AsyncSession,
):
    # 1. 验证签名
    signature = request.headers.get(webhook_signature_header(provider))
    payload = await request.body()
    entity_id = await extract_entity_from_webhook(provider, payload, signature)

    if not entity_id:
        raise HTTPException(400, "无法识别 webhook 来源")

    # 2. 验证 webhook_secret（存储时比对）
    connector = await get_connector(entity_id, provider)
    if not verify_webhook_signature(provider, payload, signature, connector.webhook_secret):
        raise HTTPException(401, "Webhook 签名验证失败")

    # 3. 幂等处理（按 event_id 去重）
    event_id = extract_event_id(provider, payload)
    if await is_duplicate_event(provider, event_id):
        return {"status": "duplicate"}

    # 4. 提交增量同步任务
    sync_connector.delay(str(entity_id), provider, SyncMode.INCREMENTAL)

    return {"status": "accepted"}
```

### 4.3 各提供商的 Webhook 签名头

| 提供商 | 签名头 | 签名算法 |
|---|---|---|
| Google Drive | `X-Goog-Channel-Token` | 自定义 token 匹配 |
| Gmail (Pub/Sub) | 无（通过 topic 验证） | GCP IAM |
| Notion | 无（SSE 推送） | 连接时验证 |
| GitHub | `X-Hub-Signature-256` | HMAC-SHA256 |
| OneDrive | `X-Client-State` | 自定义 state 匹配 |

---

## 5. 同步策略

### 5.1 各连接器同步模式

| 连接器 | 实时同步 | 定时同步 | 手动触发 | 说明 |
|---|---|---|---|---|
| Google Drive | Webhook (7 天过期) | 每 4 小时 | 支持 | Webhook 到期后自动重新注册 |
| Gmail | Pub/Sub (7 天过期) | 每 4 小时 | 支持 | 邮件触发增量，定期补全 |
| Notion | Webhook | 每 4 小时 | 支持 | 页面/数据库变更触发 |
| GitHub | Webhook | 每 4 小时 | 支持 | Push/PR/Issue 等事件 |
| Web Crawler | 不支持 | 定时抓取（7 天+） | 支持 | 无推送，纯轮询 |

### 5.2 定时同步调度 (Celery Beat)

```python
# emerald/connectors/scheduler.py

app.conf.beat_schedule = {
    "sync-google-drive": {
        "task": "emerald.connectors.tasks.sync_all",
        "schedule": crontab(minute=0, hour="*/4"),
        "kwargs": {"provider": "google_drive"},
    },
    "sync-gmail": {
        "task": "emerald.connectors.tasks.sync_all",
        "schedule": crontab(minute=0, hour="*/4"),
        "kwargs": {"provider": "gmail"},
    },
    "sync-notion": {
        "task": "emerald.connectors.tasks.sync_all",
        "schedule": crontab(minute=0, hour="*/4"),
        "kwargs": {"provider": "notion"},
    },
    "sync-github": {
        "task": "emerald.connectors.tasks.sync_all",
        "schedule": crontab(minute=0, hour="*/4"),
        "kwargs": {"provider": "github"},
    },
    "renew-webhooks": {
        "task": "emerald.connectors.tasks.renew_webhooks",
        "schedule": crontab(hour=2, minute=0),  # 每天凌晨 2 点
    },
}
```

### 5.3 增量同步逻辑

```python
# emerald/connectors/tasks.py

@app.task(bind=True)
def sync_all(self, provider: str):
    """同步所有活跃的该类型连接器"""
    connectors = get_active_connectors(provider)
    for conn in connectors:
        sync_single.delay(conn.entity_id, provider, SyncMode.INCREMENTAL)

@app.task(bind=True, max_retries=2)
def sync_single(self, entity_id: str, provider: str, mode: SyncMode):
    connector = build_connector(entity_id, provider)
    try:
        result = connector.sync(mode=mode)
        update_sync_status(entity_id, provider, result)
        log_sync_result(result)
    except TokenExpiredError:
        handle_token_expired(entity_id, provider)
    except Exception as e:
        raise self.retry(exc=e)
```

---

## 6. 同步内容处理

同步获取的文件进入标准管线：

```python
async def sync(self, mode: SyncMode) -> SyncResult:
    changes = await self._fetch_changes(mode)
    result = SyncResult(provider=self.provider)

    for change in changes:
        file_data = await self._download_file(change.file_id)

        # 哈希去重
        content_hash = sha256(file_data).hexdigest()
        if await self._is_duplicate(content_hash):
            result.files_skipped += 1
            continue

        # 提交到处理管线
        try:
            pipeline_id = await pipeline.process_async(
                content=base64_encode(file_data),
                content_type=change.mime_type,
                entity_id=self.entity_id,
                document_id=change.file_id,
            )
            result.files_synced += 1
        except Exception as e:
            result.files_failed += 1
            result.errors.append(str(e))

    return result
```

---

## 7. 连接器注册表

```python
# emerald/connectors/registry.py

CONNECTORS: dict[str, type[BaseConnector]] = {}

def register_connector(provider: str):
    def decorator(cls):
        CONNECTORS[provider] = cls
        return cls
    return decorator

def get_connector_class(provider: str) -> type[BaseConnector]:
    if provider not in CONNECTORS:
        raise UnsupportedConnectorError(f"No connector for: {provider}")
    return CONNECTORS[provider]

# 逐一注册
@register_connector("google_drive")
class GoogleDriveConnector(BaseConnector): ...

@register_connector("gmail")
class GmailConnector(BaseConnector): ...

@register_connector("notion")
class NotionConnector(BaseConnector): ...

@register_connector("github")
class GitHubConnector(BaseConnector): ...
```

---

## 8. 错误处理与重试

| 错误类型 | 重试策略 | 说明 |
|---|---|---|
| 网络超时 | 3 次，指数退避 (1s, 5s, 25s) | 临时故障 |
| Token 过期 | 先刷新 token，再重试 1 次 | 自动刷新 |
| 限流 (429) | 等待 Retry-After 头 + 1 次 | 遵守对方限制 |
| 权限不足 (403) | 不重试，设置 sync_status=error | 需用户重新授权 |
| Webhook 验证失败 | 不重试，返回 401 | 可能是攻击 |
| 文件下载失败 | 3 次重试，跳过该文件继续 | 单文件不影响整体 |

---

## 9. 已规划的连接器

| 连接器 | 优先级 | 依赖 |
|---|---|---|
| GitHub | P0 (v1) | GitHub App OAuth |
| Google Drive | P0 (v1) | Google Cloud OAuth |
| Gmail | P1 | Google Cloud OAuth + Pub/Sub |
| Notion | P1 | Notion OAuth |
| OneDrive | P2 | Microsoft Graph OAuth |
| Slack | P2 | Slack OAuth |
| Discord | P3 | Discord OAuth |
| Web Crawler | P3 | 无（纯 HTTP 抓取） |
