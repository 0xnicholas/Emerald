# Emerald Frontend — Gap Analysis vs Supermemory

> 最后更新: 2026-07-22
> 参考仓库: `_references/supermemory-main/apps/web`

## 概述

本文件记录 Emerald 前端 (`apps/web`) 与 Supermemory web app 之间的差距。
Supermemory 是 Emerald 的对标项目，前端代码约 **35,134 行**（111 个组件），
我们目前约 **5,800 行**（41 个组件），覆盖率约 **16%**。

---

## 1. 设计系统 ✅ (已对齐)

| Token | Supermemory | Emerald | 状态 |
|---|---|---|---|
| `fg-primary` | `#fafafa` | `#fafafa` | ✅ |
| `fg-muted` | `#d0dae7` | `#d0dae7` | ✅ |
| `fg-subtle` | `#b5c2d3` | `#b5c2d3` | ✅ |
| `fg-faint` | `#a0aec4` | `#a0aec4` | ✅ |
| `surface-base` | `#0b1119` | `#0b1119` | ✅ |
| `surface-card` | `#101822` | `#101822` | ✅ |
| `surface-border` | `#263348` | `#263348` | ✅ |
| `brand-accent` | `#4ba0fa` | `#4ba0fa` | ✅ |
| 字体 | DM Sans | DM Sans (Google Fonts) | ✅ |
| 圆角 | 18px (card) | 18px (card) | ✅ |
| 阴影 | `0 12px 40px rgba(0,0,0,0.22)` | ✅ | ✅ |
| 毛玻璃 | `backdrop-blur-md` | `backdrop-blur-md` | ✅ |

---

## 2. UI 组件库 (28/37 ≈ 76%)

### 已实现 ✅

| 组件 | 基于 | 状态 |
|---|---|---|
| Button | 自定义 (`cva`) | ✅ 多 variant |
| Card | 自定义 | ✅ 18px 圆角 |
| Input | 自定义 | ✅ |
| Textarea | 自定义 | ✅ **新** |
| Badge | 自定义 | ✅ |
| Label | 自定义 | ✅ **新** |
| Skeleton | 自定义 | ✅ 多行/卡片/统计 |
| Typography | 自定义 | ✅ Heading/Label/Title |
| Dialog | Radix | ✅ |
| DropdownMenu | Radix | ✅ |
| Tooltip | Radix | ✅ |
| Tabs | Radix | ✅ |
| Avatar | Radix | ✅ |
| Select | Radix | ✅ |
| Progress | Radix | ✅ |
| Separator | Radix | ✅ |
| ScrollArea | Radix | ✅ |
| Sonner | sonner | ✅ |
| Popover | Radix | ✅ **新** |
| HoverCard | Radix | ✅ **新** |
| Collapsible | Radix | ✅ **新** |
| Toggle | Radix | ✅ **新** |
| ToggleGroup | Radix | ✅ **新** |
| Accordion | Radix | ✅ **新** |
| AlertDialog | Radix | ✅ **新** |
| Checkbox | Radix | ✅ **新** |
| Sheet | Radix | ✅ **新** |
| Drawer | vaul | ✅ **新** |
| Command | cmdk | ✅ **新** |
| Table | HTML | ✅ **新** |

### 缺失 ❌

| 组件 | 优先级 | 备注 |
|---|---|---|
| Breadcrumb | 低 | 导航面包屑，页面多了再做 |
| Carousel (embla) | 低 | 轮播卡片展示 |
| Chart (recharts) | 低 | 统计图表 |
| Combobox | 低 | 搜索+选择框，可基于 Command 封装 |
| GridPlus | 低 | 自定义网格布局工具 |
| TextSeparator | 低 | 文字分隔线 |
| Sidebar (shadcn) | 低 | 已有自定义 Sidebar |
| Sheet (移动端) | 中 | 移动端 drawer 替代 |
| Dropzone | 低 | 文件拖拽上传 |

---

## 3. 页面路由 (4/12 ≈ 33%)

### 已实现 ✅

| 路由 | 功能 | 状态 |
|---|---|---|
| `/` | Dashboard + 连接页 | ✅ |
| `/memories` | 记忆浏览 + 搜索 | ✅ |
| `/graph` | 知识图谱 | ✅ |
| `/settings` | 设置 (Connection/API Keys/System Info) | ✅ |

### 缺失 ❌

| 路由 | 预计复杂度 | 备注 |
|---|---|---|
| `/login` | 中 | OAuth + email 登录，依赖 Better Auth |
| `/login/new` | 中 | 新用户注册 |
| `/onboarding` | 高 | 新手引导：连 MCP、装插件、导入数据 |
| `/onboarding/[...slug]` | 高 | 多步骤引导流程 |
| `/settings/integrations` | 中 | Chrome/Raycast/Shortcuts 等集成管理 |
| `/auth/agent-connect` | 低 | AI Agent OAuth 连接 |
| `/auth/connect` | 中 | Google/Notion/GitHub 等连接器授权 |
| `/ref` | 低 | 邀请/推广 |
| `/ref/[code]` | 低 | 邀请码落地页 |
| `/upgrade-mcp` | 低 | MCP 升级引导 |

---

## 4. 功能模块

### Dashboard (≈ 60% 覆盖)

| Supermemory 功能 | 状态 | 备注 |
|---|---|---|
| 个性化欢迎 + 头像 | ✅ | 简化版 |
| 统计卡片（记忆数/事实/上下文） | ✅ | |
| Quick Actions (Save Link / Write Note / Search) | ✅ | 多了 Add 按钮 |
| Tip of the day | ✅ | 静态 tips |
| 今日简报 (HighlightsCard) | ✅ | |
| 记忆回顾 (MemoryOfDayCard) | ✅ | |
| 插件推广卡 (PluginPromoCard) | ❌ | 无插件系统 |
| 工具使用记录 (ToolUsageRecentRow) | ❌ | 无工具追踪 |
| 最近保存 + 推荐 (双列) | ✅ | |
| 骨架屏加载态 | ✅ | |
| 静态图谱预览 (StaticGraphPreview) | ❌ | |
| 今日提示轮换 | ❌ | |

### Memories Grid (≈ 40% 覆盖)

| Supermemory 功能 | 状态 | 备注 |
|---|---|---|
| Masonry 布局 | ✅ | masonic |
| 无限滚动 | ✅ | useInfiniteLoader |
| 类型感知卡片 | ✅ | Website/Youtube/File/Note |
| Tweet 卡片 (react-tweet) | ❌ | 缺少 Twitter API |
| YouTube 卡片 | ✅ | 简化版 |
| 文件卡片 | ✅ | 简化版 |
| Google Docs 卡片 | ❌ | |
| Notion 卡片 | ❌ | |
| MCP 预览卡片 | ❌ | |
| OG 数据加载 | ❌ | |
| 批量选择 + 操作 | ❌ | |
| Facet 筛选 | ❌ | |
| 加载骨架屏 | ✅ | |
| 拖拽排序 | ❌ | |

### Graph (≈ 50% 覆盖)

| Supermemory 功能 | 状态 | 备注 |
|---|---|---|
| d3-force 物理模拟 | ✅ | |
| Canvas 渲染 | ❌ | 用 SVG |
| 节点发光效果 | ✅ | feGaussianBlur |
| 悬停弹窗 | ✅ | |
| 图例 | ✅ | |
| 缩放控件 | ✅ | |
| 分享功能 | ❌ | |
| 版本链 (VersionChainIndex) | ❌ | |
| 幻灯片模式 | ❌ | |
| 主题色自定义 | ❌ | |

### Chat (≈ 30% 覆盖)

| Supermemory 功能 | 状态 | 备注 |
|---|---|---|
| 侧滑面板 | ✅ | |
| 消息列表 | ✅ | |
| 输入框 + 发送 | ✅ | |
| 模型选择器 | ❌ | |
| 流式响应 | ❌ | |
| @提及记忆搜索 | ❌ | |
| 推理过程展示 | ❌ | |
| AI SDK 集成 (@ai-sdk/react) | ❌ | |
| Chat history | ❌ | |
| 会话管理 | ❌ | |
| Web search tools | ❌ | |

### Settings (≈ 40% 覆盖)

| Supermemory 功能 | 状态 | 备注 |
|---|---|---|
| Connection 配置 | ✅ | |
| API Keys | ✅ | |
| System Info / Health | ✅ | |
| 账号设置 (Account) | ❌ | |
| 计费/订阅 (Billing) | ❌ | |
| 集成管理 (Integrations) | ❌ | |
| MCP 连接配置 | ❌ | |
| 组织管理 | ❌ | |

### 其他缺失功能

| 功能 | 复杂度 | 备注 |
|---|---|---|
| 登录/认证系统 | 高 | OAuth + Better Auth |
| 新手引导 | 高 | 多步引导流程 |
| 命令面板 (Cmd+K) | 中 | Command 组件已就绪 |
| 移动端适配 | 中 | 响应式 sidebar + bottom nav |
| 键盘快捷键 | 低 | HotkeysProvider |
| PWA 支持 | 低 | manifest + service worker |
| 错误边界 (ErrorBoundary) | 低 | |
| 分析/遥测 (PostHog) | 低 | |
| Sentry 错误追踪 | 低 | |
| 空间/Workspace 管理 | 中 | |
| 文件缓存 (IndexedDB) | 中 | |
| 全文搜索 (DocumentsCommandPalette) | 中 | |

---

## 5. 代码量追踪

``` 
日期        组件数    UI组件    代码行    差距倍率
2026-07-10    41       28       ~5,800     6x
2026-07-22    45       30       ~7,200     5x
2026-07-22(b) 50       30       ~8,500     4x
目标         111       37      ~35,134     1x
```

---

## 6. 总进度估算

| 领域 | 权重 | 进度 | 加权 |
|---|---|---|---|
| 设计系统 | 10% | 100% | 10% |
| UI 组件库 | 15% | 81% | 12.2% |
| 页面路由 | 15% | 50% | 7.5% |
| Dashboard | 15% | 70% | 10.5% |
| Memories Grid | 15% | 55% | 8.25% |
| Graph | 10% | 50% | 5% |
| Chat | 10% | 30% | 3% |
| Settings | 5% | 50% | 2.5% |
| 其他功能 | 5% | 30% | 1.5% |
| **合计** | **100%** | — | **~60.5%** |

> 注：按代码量算约 16%，但核心功能覆盖度和视觉质量拉高了加权进度。

---

## 7. 已完成（2026-07-22 · 两轮）

| # | 任务 | 状态 |
|---|------|------|
| 1 | **修复构建** — Node 23 正常工作 | ✅ |
| 2 | **命令面板** — Cmd+K 全局搜索 | ✅ |
| 3 | **移动端适配** — 响应式 sidebar + 底部导航 | ✅ |
| 4 | **Hooks 提炼** — useProfile, useSearchMemories, useGraphData, useConnectors, useAddMemory | ✅ |
| 5 | **Keyboard shortcuts** — C/M/G/D/T/? 全局快捷键 | ✅ |
| 6 | **登录页 `/login`** — API Key 连接 + Demo 模式 | ✅ |
| 7 | **集成管理页 `/integrations`** — 连接器状态查看/断连 | ✅ |
| 8 | **错误边界 ErrorBoundary** — 全局 error + per-component | ✅ |
| 9 | **Dashboard 增强** — StaticGraphPreview, TipRotationCard, Quick Actions 改进 | ✅ |
| 10 | **Memories Grid 卡片补全** — GoogleDocs/Notion/Tweet/MCP 卡片 | ✅ |
| 11 | **Dashboard 重构** — 使用 useProfile/useSearchMemories hooks | ✅ |

## 8. 下一批可做

| 方向 | 说明 | 优先级 |
|------|------|--------|
| **Chat 完善** | 流式响应 (AI SDK), 模型选择器, @提及, 会话管理 | 高 |
| **Graph 升级** | Canvas 渲染 (替代 SVG), 分享, 版本链, 幻灯片模式 | 中 |
| **Auth 完善** | Better Auth OAuth, 注册, 密码重置 | 中 |
| **Memories 批量操作** | 多选/删除/移动, Facet 筛选 | 中 |
| **PWA 支持** | manifest + service worker | 低 |
| **移动端完善** | 移动端搜索栏优化, 手势操作 | 低 |
