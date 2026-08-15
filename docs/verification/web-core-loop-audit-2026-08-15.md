# apps/web 现状事实清单（核心循环审计）

> **定位**：Wayfinder 票「apps/web 现状事实清单」（issue #48）的研究产物。只记事实与出处（file:line），**不断差距**——完成标尺由另一张票（issue #47「审计标尺」）单独定义。
>
> **日期**：2026-08-15
> **范围**：`apps/web`（Next.js 16.2.10，React 19.2.4，见 `apps/web/package.json:38,40`）+ 与之连通的 `docker-compose.yml`、`nginx.conf`、核心引擎路由 `emerald/api/routes/v1/`。
> **方法**：逐文件阅读源码，每个结论标注 `file:line`。

---

## 1. 四环映射（摄入 → 搜索 → 画像 → 对话）

ADR-0003 定义前端评价标准为「核心循环完整性」：摄入 → 搜索 → 画像 → 对话；自托管单机可跑；移动端可用（`docs/adr/0003-web-ui-is-product-layer.md`）。以下按四环列出 web 源码中实际存在的实现与调用路径。

### 1.1 摄入（Ingest）

| 路径 | 实现位置 | 实际行为（事实） |
|---|---|---|
| Dashboard 快速笔记 | `apps/web/src/components/dashboard-view.tsx`（`handleQuickSave`） | 调用 `getClient().addMemory(...)` → `POST /v1/memories`（`apps/web/src/lib/api.ts` `addMemory`；`emerald/api/routes/v1/memories.py:44`）。这是 web 内唯一直接调用 `addMemory` 的位置（`grep -rn "\.addMemory("` 命中 1 处，dashboard-view.tsx）。 |
| Add Memory 弹窗（Note/Link/File 三 tab） | `apps/web/src/components/add-memory-modal.tsx` | 弹窗的 `handleSubmit` 仅在 `onAdd` prop 存在时调用它（`add-memory-modal.tsx:97-99`）；否则只 `setSuccess(true)` 后关闭（`:99-101`）。4 处渲染点均**未传 `onAdd`**：`app/page.tsx:44`、`app/memories/page.tsx:290`、`app/graph/page.tsx:266`、`components/dashboard-view.tsx:603`。→ Note/Link/File 三个「Save」按钮只弹「Memory saved!」并关闭，不落库。 |
| Link 预览 | `add-memory-modal.tsx:80` | 仅在输入 URL 时调 `getClient().extractUrl(url)` → `POST /v1/extract-url`（`emerald/api/routes/v1/extract.py:86`）用于**预览**，保存仍走上面的 `onAdd` 空路径。 |
| File 上传 | `add-memory-modal.tsx`（File tab） | 只记录 `fileName` 状态（`:163-168`），未调用任何上传接口（`getClient` 无 `upload` 方法；`emerald/api/routes/v1/upload.py:29` 的 `POST /v1/upload` 未被 web 引用）。 |
| 数据源连接（连接中心） | `apps/web/src/app/integrations/page.tsx` | `connectSource` → `POST /v1/sources/connect` 后 `window.open(session.auth_link_url)`（`integrations/page.tsx` `ConnectButton`，见 `lib/api.ts` `connectSource`）；另有 `listSources`（GET `/v1/sources`）、`refreshSources`（POST `/v1/sources/refresh`）、`deleteSource`（DELETE `/v1/sources/{binding_id}`）。SOURCE_META 仅 `feishu`（`integrations/page.tsx:30-41`，ADR-0004 连接中心 v1 upstream）。 |
| 导出 JSON | `apps/web/src/app/settings/page.tsx`（`DataPanel`，`handleExport`） | 导出走 `getClient().search("", entityId, {searchMode:"memory", topK:500})` 后浏览器侧 Blob 下载（`settings/page.tsx` DataPanel），不经过 `GET /v1/profiles/{id}/memory.md` 或 `GET /v1/files`。 |

### 1.2 搜索（Search）

| 调用点 | 实现位置 | 参数（事实） |
|---|---|---|
| 记忆浏览页 | `apps/web/src/app/memories/page.tsx`（`doSearch`） | `searchMode` 由 UI 三态映射为 `hybrid`/`memory`/`rag`（`:110-115`），`topK: 50`，`filters: selectedSpaceTag !== "default" ? { container_tag: selectedSpaceTag } : undefined`（`:117-119`）；type/tag 过滤为**客户端** filter（`:121-129`）。 |
| Dashboard「最近保存」 | `apps/web/src/components/dashboard-view.tsx` | `useSearchMemories("", entityId, {searchMode:"memory", topK:8, filters: container_tag})`（dashboard-view.tsx `searchQuery`）。 |
| Chat 正文 | `apps/web/src/components/chat/chat-interface.tsx`（`handleSend`） | `searchMode:"hybrid", topK:8`（chat-interface.tsx:153-154）。 |
| Chat @提及 | `chat-interface.tsx`（`useAtMentionSearch`） | `searchMode:"memory", topK:6`（`:51-53`）。 |
| 命令面板 | `apps/web/src/components/command-palette.tsx` | `searchMode:"hybrid", topK:8`（`:153-157`）。 |
| 搜索框 | `apps/web/src/components/search/search-bar.tsx` | 受控组件，`autoSearch` 走 300ms 防抖调 `onSearch`（`:92-99`），近次搜索存 localStorage `emerald:recent-searches`（`:8-16`）。 |

统一走 `EmeraldClient.search` → `POST /v1/search`（`lib/api.ts` `search`；`emerald/api/routes/v1/search.py:44`）。引擎另有 `GET /v1/search`（`search.py:113`），web 客户端未使用。

### 1.3 画像（Profile）

| 事实 | 位置 |
|---|---|
| 画像获取 hook | `apps/web/src/hooks/use-profile.ts` → `getClient().getProfile(entityId)` → `GET /v1/profiles/{entity_id}`（`lib/api.ts` `getProfile`；`emerald/api/routes/v1/profiles.py:34`）。 |
| Dashboard 画像渲染 | `dashboard-view.tsx` `StatFactsCard` 展示 `profile.static`（含 importance 进度条）；`stats` 卡片展示 `profile.memory_count`、`profile.static.length`、`profile.dynamic.length`。 |
| 画像注入 | 引擎侧原则「画像是默认上下文，先于搜索注入」（AGENTS.md 原则 5）由引擎保证；web 侧仅**渲染**画像卡片，未发现 web 端在搜索/对话前手动注入画像的代码路径。Chat 的 system prompt（`app/api/chat/route.ts:41-54`）只注入 `memories`，不注入画像；且该 route 未被前端调用（见 §3）。 |

### 1.4 对话（Chat）

| 事实 | 位置 |
|---|---|
| Chat UI 回复生成 | `chat-interface.tsx` `handleSend`：`getClient().search(...hybrid, topK:8)` → `formatMemoryResponse(q, results)`（`chat-interface.tsx:158`）→ 模板化拼 facts/preferences/episodes（`components/chat/types.ts:56-99`）。**无 LLM 调用**。 |
| 会话持久化 | `chat/types.ts` `readSessions`/`writeSessions`，存 localStorage `emerald:chat-sessions`（`:116-137`）。 |
| LLM 代理 route（存在但未被前端引用） | `apps/web/src/app/api/chat/route.ts`：edge runtime，读 `process.env.OPENAI_API_KEY`，流式转发 `https://api.openai.com/v1/chat/completions`（`:52`）。全仓库 grep `/api/chat` 或 `api/chat` 无任何客户端调用点（仅 route 自身）。→ 该 route 当前是**未被前端调用**的代码路径。 |
| 模型选择器 | `chat/types.ts` `CHAT_MODELS`（gpt-4o / gpt-4o-mini / claude-sonnet-4 / auto）（`:24-28`），但 `handleSend` 不使用所选模型发请求——模型选择仅存于会话对象（`saveSession`，`chat-interface.tsx:124-135`）。 |

---

## 2. EmeraldClient 覆盖 vs 引擎路由

### 2.1 引擎路由全集（前缀 `/v1`，`emerald/api/app.py:357-366`）

| 路由文件 | 端点（方法 + 路径） |
|---|---|
| memories.py | `POST /memories`（:44）、`GET /memories/{id}`（:83）、`POST /memories/{id}/validate`（:114）、`PATCH /memories/{id}`（:134）、`DELETE /memories/{id}`（:158）、`POST /memories/batch`（:175） |
| search.py | `POST /search`（:44）、`GET /search`（:113） |
| profiles.py | `GET /profiles/{entity_id}`（:34）、`GET /profiles/{entity_id}/memory.md`（:66）、`GET /profiles/{entity_id}/config`（:82）、`PUT /profiles/{entity_id}/config`（:113）、`DELETE /profiles/{entity_id}/config`（:161） |
| upload.py | `POST /upload`（:29）、`GET /files`（:135） |
| pipelines.py | `GET /pipelines/{pipeline_id}`（:18） |
| conflicts.py | `POST /conflicts/{conflict_id}/resolve`（:39） |
| extract.py | `POST /extract-url`（:86） |
| sessions.py | `POST /sessions`（:23）、`GET /sessions/verify`（:69） |
| sources.py | `POST /connect`（:69）、`POST /webhook`（:109）、`GET /sources`（:154）、`POST /refresh`（:177）、`DELETE /{binding_id}`（:209）——router 前缀 `/sources`（sources.py:29） |
| keys.py | `POST /keys`（:47）、`GET /keys`（:110）、`DELETE /keys/{key_id}`（:204） |
| spaces.py | `GET /spaces`（:35）、`POST /spaces`（:57）、`PATCH /spaces/{container_tag}`（:86）、`DELETE /spaces/{container_tag}`（:116） |
| system.py | `GET /health`（:50）、`GET /memories/graph`（:82） |
| （nginx 额外代理） | `GET /v1/metrics`（`nginx.conf:71`）、`/docs`、`/openapi.json`（`nginx.conf:61-68`） |

### 2.2 EmeraldClient（`apps/web/src/lib/api.ts`）覆盖

| 客户端方法 | 请求 | 对应引擎端点 | 被 UI 调用次数* |
|---|---|---|---|
| `search` | POST `/v1/search` | search.py:44 | 7 |
| `getMemory` | GET `/v1/memories/{id}` | memories.py:83 | **0** |
| `addMemory` | POST `/v1/memories` | memories.py:44 | 1 |
| `updateMemory` | PATCH `/v1/memories/{id}` | memories.py:134 | 1 |
| `updateMemoryTags` | PATCH `/v1/memories/{id}` | memories.py:134 | **0** |
| `deleteMemory` | DELETE `/v1/memories/{id}` | memories.py:158 | 1 |
| `getProfile` | GET `/v1/profiles/{entity_id}` | profiles.py:34 | 1 |
| `getPipelineStatus` | GET `/v1/pipelines/{id}` | pipelines.py:18 | **0** |
| `listSpaces` | GET `/v1/spaces` | spaces.py:35 | 1 |
| `createSpace` | POST `/v1/spaces` | spaces.py:57 | 1 |
| `updateSpace` | PATCH `/v1/spaces/{tag}` | spaces.py:86 | 1 |
| `deleteSpace` | DELETE `/v1/spaces/{tag}` | spaces.py:116 | 1 |
| `getGraph` | GET `/v1/memories/graph` | system.py:82 | 2 |
| `extractUrl` | POST `/v1/extract-url` | extract.py:86 | 1 |
| `listSources` | GET `/v1/sources` | sources.py:154 | 1 |
| `connectSource` | POST `/v1/sources/connect` | sources.py:69 | 1 |
| `refreshSources` | POST `/v1/sources/refresh` | sources.py:177 | 1 |
| `deleteSource` | DELETE `/v1/sources/{binding_id}` | sources.py:209 | 1 |
| `health` | GET `/v1/health` | system.py:50 | 4 |

\* 调用次数 = `grep -rn "\.<method>(" apps/web/src --include="*.ts" --include="*.tsx"`（排除 `lib/api.ts` 自身定义行）。

**未被 EmeraldClient 覆盖的引擎端点**：`POST /memories/batch`、`POST /memories/{id}/validate`、`POST /upload`、`GET /files`、`GET /profiles/{id}/memory.md`、`GET|PUT|DELETE /profiles/{id}/config`、`POST /conflicts/{id}/resolve`、`POST /sessions`、`GET /sessions/verify`、`POST /sources/webhook`、`POST|GET|DELETE /keys`、`GET /search`（仅用 POST）。

---

## 3. Chat 代理链路

- Route 定义：`apps/web/src/app/api/chat/route.ts`，`runtime = "edge"`、`dynamic = "force-dynamic"`（`:3-4`）。
- 输入：`{ messages[], model = "gpt-4o-mini", memories? }`（`:9-12`）。
- API Key 来源：`process.env.OPENAI_API_KEY`（`:17`）。**无 key 时**返回降级文案（用 `memories` 拼字符串，`:19-32`）。
- 转发：`fetch("https://api.openai.com/v1/chat/completions", {... stream:true ...})`（`:52-66`），错误时 502（`:68-74`）。
- 前端调用：**无**——grep 全 src 无 `/api/chat` 客户端引用（见 §1.4）。Chat 回复实际由 `formatMemoryResponse` 模板生成，不经过此 route。

---

## 4. docker-compose 全链路

`docker-compose.yml` 服务（共 11 个）：

| 服务 | 关键配置 | 说明 |
|---|---|---|
| `api` | `uvicorn emerald.api.app:app --host 0.0.0.0 --port 8000 --reload`，端口 `8000:8000`（:9-17）；`depends_on` postgres/neo4j/redis/minio 均 `condition: service_healthy`（:24-33） | 后端 API |
| `worker` | `celery -A emerald.pipeline.tasks worker --concurrency=4`（:46） | 管线 |
| `beat` | `celery -A emerald.pipeline.tasks beat`（:61） | 定时（遗忘/整合等） |
| `postgres` | `pgvector/pgvector:pg16`，端口 `5433:5432`（:79-82） | 向量+关系 |
| `neo4j` | `neo4j:5-community`，APOC 插件，端口 `7474:7474` / `7687:7687`（:96-101） | 图谱 |
| `redis` | `redis:8.0`，requirepass，端口 `6380:6379`（:116-120） | 锁/缓存 |
| `minio` | `minio/minio:latest`，端口 `9002:9000` / `9003:9001`（:135-139） | 文件 |
| `minio-init` | `minio/mc`，建 bucket `emerald-documents` / `emerald-temp`（:152-165） | 初始化 |
| `mcp` | `python -m emerald.mcp.server --transport sse --port 8001`，端口 `8001:8001`（:177-181） | MCP |
| `frontend` | `build: ./apps/web`，`command: npm run dev`，端口 `3000:3000`，`NEXT_PUBLIC_EMERALD_API_URL=http://api:8000`（:208-217） | Next.js |
| `nginx` | `nginx:alpine`，端口 `80:80`，`depends_on api, frontend`（:224-230） | 反向代理 |

- 前端为 **dev 模式**（`npm run dev`），非 `next start`（compose `frontend.command`）。
- `NEXT_PUBLIC_EMERALD_API_URL=http://api:8000` 在 compose 中设置，但 **web 源码无任何读取该变量的代码**（grep `NEXT_PUBLIC_EMERALD_API_URL` / `NEXT_PUBLIC` 在 `apps/web/src` 与 `apps/web/next.config.ts` 均为 0 命中）。`EmeraldClient.getClient()` 的 baseUrl 默认硬编码 `http://localhost:8000`（`lib/api.ts:308-315`），仅可被 localStorage `emerald_base_url` 覆盖。
- `nginx.conf`：`location /v1/` 与 `/docs`、`/openapi.json`、`/v1/metrics` 代理到 `api:8000`（:31-73）；`/mcp/` 代理到 `mcp:8001`（:76-85）；`/` 代理到 `frontend:3000`（:89-98）；`client_max_body_size 50m`（:24）。

---

## 5. 登录 / 鉴权路径

- 登录页：`apps/web/src/app/login/page.tsx`。表单三项：Server URL、API Key、Entity ID（均为手工输入，`:121-155`）。
- 测试连接：`handleTest` 用输入的 key/url/entity 构造 `EmeraldClient` 调 `client.health()`（`login/page.tsx:38-50`）→ `GET /v1/health`。
- 连接：`handleConnect` 把三项写入 zustand store（`setApiKey/setBaseUrl/setEntityId`），store 同步写 localStorage `emerald_api_key` / `emerald_base_url` / `emerald_entity_id`（`apps/web/src/stores/app.ts:37-50`）。
- 每次请求的鉴权头：`EmeraldClient.headers` → `Authorization: Bearer ${config.apiKey}`（`lib/api.ts:28-33`）。
- **API Key 获取方式**：web 不生成 key。Settings 的 `ApiKeysPanel` 文案「API keys are managed through the Emerald backend. Generate keys using the CLI or seed script」，给出的命令为 `docker exec emerald-api python scripts/seed_dev_api_key.py`（`settings/page.tsx` ApiKeysPanel）。引擎的 `POST /v1/keys`（`emerald/api/routes/v1/keys.py:47`）未被 web 调用。
- 另有一个非登录页的连接面板 `apps/web/src/components/layout/connection-panel.tsx`：同样手工填三项，`testConnection` 要求 `health.status === "healthy"`（`:31-35`）。
- 未连接时的门卫：`app/page.tsx:19-26`（首页）、`memories/page.tsx:34-41`、`graph/page.tsx`、`integrations/page.tsx`、`settings/page.tsx` 均在 `!connected && !demoMode` 时渲染 `ConnectionPanel`。
- Demo 模式：登录页 `handleDemo` → `setDemoMode(true)`（`login/page.tsx:63-66`）；demo 数据来自 `apps/web/src/lib/mock-data.ts`（`MOCK_PROFILE` / `MOCK_SPACES` / `MOCK_MEMORIES` / `getMockSearchResults`，:3, :22, :228, :235）。

---

## 6. 其他事实

### 6.1 Spaces 相关

- 前端默认 space tag 字面量为 `"default"`：`apps/web/src/lib/spaces.ts:3`（`DEFAULT_SPACE_TAG = "default"`）、`apps/web/src/hooks/use-space.ts:5`（`DEFAULT_SPACE_TAG = "default"`）。dashboard / memories / graph 页初始 `selectedSpaceTag` 也回退 `"default"`（`dashboard-view.tsx`、`memories/page.tsx:57-60`、`graph/page.tsx:53-56`）。
- 搜索过滤：`filters: selectedSpaceTag !== "default" ? { container_tag: selectedSpaceTag } : undefined`（`memories/page.tsx:118`、`dashboard-view.tsx` `searchQuery`）。
- Space 选择器：`components/spaces/space-selector.tsx` → `useContainerTags()`（`listSpaces`）+ `SelectSpacesModal` + `AddSpaceModal`（`createSpaceMutation`，`add-space-modal.tsx:37`）。
- 对照引用：ADR-0002 规定 `container_tag` 可空、移除 `"default"` 伪空间、系统不自动创建/推断空间（`docs/adr/0002-spaces-are-views-not-partitions.md`）。

### 6.2 依赖与构建

- `apps/web/package.json` 声明 `"@supermemory/memory-graph": "^0.2.3"`（:37），但 grep 全 src 无任何 import 该包（0 命中）——依赖已声明未使用。
- 图谱渲染用 `d3-force`（`apps/web/src/components/graph/knowledge-graph.tsx:13`）。
- 生产构建：`apps/web/Dockerfile` 多阶段（dev → deps → builder → runner，standalone 输出），`next.config.ts` 生产 `output: "standalone"`（`apps/web/next.config.ts:3-5`）。compose 用的是 `target: development` + `npm run dev`，非 runner 阶段。

### 6.3 移动端

- 存在移动端底部导航 `components/layout/mobile-bottom-nav.tsx` 与 `hooks/use-mobile.ts`、侧边栏移动抽屉（`sidebar.tsx` 移动分支 `:31-103`）。移动端形态的验收标准由标尺票（issue #47）定义，此处仅记录实现存在。

---

## 附录：关键文件清单（审计覆盖面）

- `apps/web/src/lib/api.ts`（EmeraldClient 全部方法）
- `apps/web/src/lib/types.ts`（Memory / SearchMemory / Profile / Space / Graph 等类型）
- `apps/web/src/stores/app.ts`（连接配置 store + localStorage）
- `apps/web/src/hooks/`（use-profile / use-search-memories / use-memory-mutations / use-container-tags / use-space / use-project-mutations / use-mobile）
- `apps/web/src/app/` 6 页面（page / memories / graph / integrations / settings / login）+ `app/api/chat/route.ts`
- `apps/web/src/components/`（chat / graph / memories / search / spaces / layout / add-memory-modal / command-palette / dashboard-view）
- `emerald/api/routes/v1/*.py`（引擎路由全集）
- `docker-compose.yml`、`nginx.conf`、`apps/web/Dockerfile`、`apps/web/next.config.ts`、`apps/web/package.json`
