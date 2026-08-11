# Emerald 安全审计报告（2026-08）

> **范围**：roadmap M2 #14（原主题 A6）。三维审计：① 依赖扫描 ② Secret 检测 ③ API 层清单五项。
> **结论**：**0 个 P0/P1 漏洞**。发现并修复 2 个中危问题（`/v1/extract-url` 无鉴权 SSRF 面、CI secret 门禁形同虚设），修复 3 个门禁配置缺陷（pip-audit 非硬门禁、Gitleaks 规则跨行误报、Gitleaks allowlist 结构失效）。
> **验收**：报告 + CI 门禁状态（`security.yml` 三项 job 全绿为达成标准）。
> **关联**：ADR-0001（独立度量）、roadmap M2 成功标准第 3 条。

---

## 1. 执行摘要

| 维度 | 结果 | 门禁状态 |
|---|---|---|
| ① 依赖扫描（pip-audit） | **0 已知漏洞**（含豁免 PYSEC-2024-1） | ✅ 硬门禁（本轮由 warning 升级为硬失败） |
| ② Secret 检测（Gitleaks 全历史） | **0 真实泄漏**（237 commits；31 个 dev 默认值命中已消解） | ✅ 新增全历史扫描 job（原 CI 仅扫 push diff） |
| ③ API 层清单五项 | **5/5 达标**（其中 1 项本轮修复后达标） | ✅ `tests/api` 101 + 2 新增回归测试全绿 |

**修复清单（本轮落地）**：

| # | 严重性 | 问题 | 修复 |
|---|---|---|---|
| F1 | **中** | `POST /v1/extract-url` 无鉴权执行出站 HTTP fetch——未认证 SSRF 面（内网探测）+ 资源滥用，且 `follow_redirects=True` | 挂载 `api_key_auth` + `rate_limit`；2 个回归测试（401 前置拦截 / 认证后正常流程）；OpenAPI 重新生成 |
| F2 | **中** | CI `secret-scan` 从未全历史扫描——gitleaks-action 仅扫 push commit range（`base^..HEAD`），历史泄漏永不触发失败 | 新增 `secret-scan-full-history` job（固定 gitleaks 8.30.1，全历史 `detect`） |
| F3 | 低 | CI `dependency-audit` 为 warning 而非硬门禁（`\|\| echo ::warning`），与 roadmap「0 已知漏洞硬门禁」不符 | 移除 `||` 兜底，pip-audit 失败即 job 失败 |
| F4 | 低 | Gitleaks 连接串规则 `[^@]+` 跨行贪婪匹配（Go 否定字符类含 `\n`），吞掉多行块直到下一个 `@` → 31 个误报 | 规则改为 `[^@\n]+`，单行限定 |
| F5 | 低 | Gitleaks `[allowlist.rules]` map 结构与 `paths` 共存时被静默丢弃（8.24.3/8.30.1 均复现），原 allowlist 基本未生效 | 改用官方 `[allowlist] regexes` 字段（两版本验证生效）；示例/测试配置文件按路径豁免 |

---

## 2. ① 依赖扫描

**工具**：pip-audit 2.10.1（2026-08-10 版本）
**方法**：两种模式交叉验证——
1. 当前 venv 实装包扫描（`pip_audit` 无参，扫 site-packages）
2. 干净环境解析（uv 建临时 venv，安装 `requirements.txt` + `requirements-prod.txt` + `requirements-dev.txt` 全部最新满足约束的版本后扫描）——复现 CI 语义

**结果**：两种模式均 **No known vulnerabilities found**。

- `emerald` 自身（0.4.0）不在 PyPI，跳过审计（预期）。
- PYSEC-2024-1 豁免保留（既有 ADR 决议，`.gitleaks.toml` 之外见 `security.yml` `--ignore-vuln`）。
- 扫描范围含 `requirements-dev.txt`（开发依赖也在生产环境之外的 CI 运行），prod 精简清单单独覆盖。

**发现 F3**：CI 门禁此前为 `pip-audit ... || echo "::warning"`——漏洞永远不失败。已改为硬失败。

**验证命令**（可复现）：
```bash
uv venv /tmp/emerald-audit-venv
uv pip install --python /tmp/emerald-audit-venv/bin/python \
  -r requirements.txt -r requirements-prod.txt -r requirements-dev.txt pip-audit
/tmp/emerald-audit-venv/bin/python -m pip_audit --ignore-vuln PYSEC-2024-1
# → No known vulnerabilities found, exit 0
```

---

## 3. ② Secret 检测（Gitleaks 全历史）

**工具**：gitleaks 8.30.1（本地验证）+ 8.24.3（CI action 解析版本）双版本对照；237 commits 全历史。
**方法**：`gitleaks detect --source . --config .gitleaks.toml`（全历史，无 commit range 限定）。

**结果**：**0 真实泄漏**。修复配置前原始扫描 31 个命中，逐项核验全部为开发占位凭据：

| 来源文件 | 命中内容 | 性质 |
|---|---|---|
| `.env.example` / `.env.test` / `.env.docker.example` | `postgresql://emerald:emerald_dev@`、`redis://:emerald_dev@`、`bolt://...` | 示例/测试配置，占位凭据 |
| `emerald/config.py` 默认值 | 同上（开发默认连接串） | 开发默认，仅 localhost |
| `.github/workflows/benchmark.yml` | docker-compose 服务地址 + CI 环境变量 | CI 沙箱凭据 |
| `scripts/persistent_server.py` | `os.environ.setdefault` 开发默认 | 开发脚本 |

**无** API key / token / 私钥 / 生产连接串命中（generic-api-key、openai-key、jwt、private-key 规则均零命中）。

**发现 F4**：连接串规则 `redis://[^@]+@` 的 `[^@]` 在 Go regex 中匹配换行，跨行吞块直到下一个 `@`，把整段 YAML/配置块识别为 secret——31 个命中里大部分因此产生。规则改为 `[^@\n]+` 后单行限定，命中数从 31 → 8（剩余均为真实 dev 连接串）。

**发现 F5**：原 `.gitleaks.toml` 用 `[allowlist.rules]` map 结构。实验证实（8.24.3 与 8.30.1 均复现）：当 `[allowlist]` 块同时定义 `paths` 时，`[allowlist.rules]` 被**静默丢弃**——原 allowlist 从未生效（CI 此前绿只是因为从没全历史扫描）。已迁移到官方 `[allowlist] regexes` 字段（匹配规则捕获文本），并补充示例/测试配置文件的路径豁免。

**发现 F2**：`security.yml` 的 gitleaks-action 日志证实扫描范围为 `base^..HEAD`（仅当次 push 的 commits）。roadmap 验收「全历史零命中」从未被 CI 覆盖。新增 `secret-scan-full-history` job。

**验证命令**（可复现）：
```bash
gitleaks detect --source . --config .gitleaks.toml --redact
# → no leaks found, exit 0（8.30.1 与 8.24.3 一致）
```

---

## 4. ③ API 层清单五项

### 4.1 CORS 加固 — ✅ 达标

`emerald/api/app.py`（`create_app`）：
- `CORS_ALLOWED_ORIGINS` 显式白名单；空字符串 = **完全不发 CORS 头**（最严格）。
- 通配符 `*` 仅限 `development` 环境（`emerald_env`），生产环境出现通配符记录 warning（`cors_wildcard_in_production`）。
- 通配符时 `allow_credentials=False`（正确——`*` 与凭据不能共存），白名单时 `True`。
- `/docs`（Swagger UI）仅在 development 暴露。

### 4.2 实体隔离 — ✅ 达标

`emerald/api/dependencies.py`：
- `api_key_auth`：Bearer + `em_` 前缀 + SHA-256 哈希查询（服务端不存明文）+ 过期检查 + **external_id 作用域**（2026-08-10 Totem Pilot 联调修复，join Entity 取 external id，杜绝内部 UUID 约定错配）。
- `authorize_entity`：集中式跨实体检查（403），memories / search / profiles / conflicts / upload / batch / spaces / sources / keys 全部接入。
- upload：实体授权在**任何 I/O 之前**（MinIO PUT 前），P0 修复回归测试 `tests/api/test_upload_authorization.py` 守护。
- keys（管理面）：内部 UUID 比对 + `require_admin_permission` 双保险。

### 4.3 鉴权边界 — ⚠️ 发现并修复（F1）

核查全部 13 个路由模块 × 39 个 operation：
- **修复前**：`POST /v1/extract-url` 无任何认证/限流依赖，执行出站 HTTP fetch（`httpx` + `follow_redirects=True`）。未认证攻击者可：① SSRF 探测内网（云元数据 169.254.169.254、localhost 服务指纹经 og:title/description 回显）；② 无限制消耗出站带宽与连接。
- **修复**：挂载 `api_key_auth` + `rate_limit`；回归测试 `tests/api/test_extract_auth.py`（2 例：401 前置拦截断言 httpx 零调用；认证后正常提取断言 fetch 恰一次）；OpenAPI 重新生成（全局 `security: ApiKeyAuth` 覆盖）。
- 其余 38 个 operation 全部有 `api_key_auth`（webhook 除外——以签名代替 key，见 4.5）；写操作统一 `require_write_permission`；管理端点 `require_admin_permission`。
- 负面守卫：`tests/negative/test_no_internal_exposure.py`（v2 内部路由不暴露）+ `tests/api/test_route_completeness.py`（路由面枚举）。

### 4.4 限流 — ✅ 达标

`emerald/api/dependencies.py::rate_limit`：
- Redis 滑动窗口（ZSET，按 key_id + 路由 pattern 分桶，路径参数不拆分桶）。
- 端点级配额（memories/search/profiles/upload 独立，默认 60/分）。
- 429 + `Retry-After`；`X-RateLimit-*` 头经中间件注入。
- 已挂载到全部高频端点；webhook 也限流。
- **观察项 W1**（见 §5）：Redis 不可用时跳过限流（fail-open）——权衡是避免 Redis 故障拖垮 API，记录在案。

### 4.5 上传 + Webhook 验签 — ✅ 达标

上传（`emerald/api/routes/v1/upload.py`）：
- 50MB 上限（413）；实体授权先于 I/O（§4.2）；write 权限；限流；MIME 检测。

Webhook（`emerald/api/routes/v1/sources.py::receive_webhook` + `emerald/sources/totem.py::verify_webhook`）：
- HMAC-SHA256 over **raw body**，base64url，`x-totem-signature` 头，`hmac.compare_digest` 常量时间比较。
- **无 secret 配置时拒绝**（fail-closed），未配置/缺失签名均 401。
- 事件归一化（§8.2 envelope）与验签同代码路径服务 v1 直连与 v2 平台投递。

---

## 5. 观察项（低风险，记录不阻塞）

| # | 观察 | 理由与建议 |
|---|---|---|
| W1 | `rate_limit` 在 Redis 不可用时跳过（fail-open） | 防止 Redis 故障级联拒绝 API；接受此权衡。后续若需严格模式可加 `RATE_LIMIT_STRICT=1` |
| W2 | `authorize_entity` 在 `request.state.entity_id` 未设置时 no-op | 测试便利设计；生产所有路由均有 `api_key_auth` 前置，风险可控。已在 docstring 注明 |
| W3 | Gitleaks 豁免 `tests/`、`docs/` 整目录（历史遗留） | 若未来在这些目录提交真实凭据将漏检。本轮未收紧（避免破坏既有绿态），建议后续将豁免缩窄到具体 fixture 文件 |
| W4 | `gitleaks-action@v2` 版本漂移（当前解析 8.24.3） | 新增的全历史 job 固定 8.30.1 与本地验证一致；增量 job 保留 action |
| W5 | `requirements*.txt` 无锁定版本（`>=` 约束） | pip-audit 扫最新解析结果；若需严格供应链可引入 lockfile（不在 M2 范围） |

---

## 6. 门禁状态汇总

`.github/workflows/security.yml`（push / PR / 每周一 08:00 UTC / 手动）：

| Job | 门禁 | 本地验证 |
|---|---|---|
| `dependency-audit` | pip-audit 0 漏洞（硬失败，PYSEC-2024-1 豁免） | ✅ 双模式 0 漏洞 |
| `secret-scan` | gitleaks-action（增量 commit range） | ✅ 配置修复后无命中 |
| `secret-scan-full-history`（新增） | gitleaks 8.30.1 全历史零命中 | ✅ 8.30.1 + 8.24.3 双版本 no leaks |
| `codeql` | CodeQL Python 分析 | 未改动（既有） |

**验收对照（roadmap M2 成功标准）**：`pip-audit 0 已知漏洞硬门禁` ✅ / `Gitleaks 全历史零命中` ✅ / `API 层清单五项` ✅（1 项修复后达标）/ `0 个 P0/P1 漏洞` ✅。

---

## 7. 变更文件

| 文件 | 变更 |
|---|---|
| `.github/workflows/security.yml` | pip-audit 硬门禁；新增全历史 secret 扫描 job |
| `.gitleaks.toml` | 规则跨行修复；allowlist 迁移 regexes；示例配置路径豁免 |
| `emerald/api/routes/v1/extract.py` | `/v1/extract-url` 挂载 auth + rate_limit（F1） |
| `tests/api/test_extract_auth.py` | 新增 2 例回归测试（F1） |
| `docs/api/openapi.yaml` | 重新生成（extract-url security 声明） |

测试基线：`tests/api` 101 passed + 新增 2 例全绿；`tests/quality/temporal` 聚合门全绿；全量 914 passed / 32 failed 为本地环境既有基线（可选提取库未安装、无 OpenAI key、Redis 状态——stash 对照验证与本轮改动无关）。

---

*报告生成：2026-08-11。审计执行：AFK 驱动（roadmap M2 #14）。工具版本：pip-audit 2.10.1 / gitleaks 8.30.1 & 8.24.3 / Python 3.13。*
