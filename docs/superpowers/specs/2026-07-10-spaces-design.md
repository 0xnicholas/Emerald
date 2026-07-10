# Spaces（空间集合）设计文档

> 日期：2026-07-10
> 对标：Supermemory Spaces / Container Tags 功能
> 状态：设计稿

---

## 1. 概述

Spaces 是组织记忆的核心功能，允许用户将记忆分组到不同的"空间"中。每个 Space 是一个命名的容器，带有一个 emoji 图标，记忆可以通过 `container_tag` 字段归属于某个 Space。

### 1.1 对标 Supermemory 的实现

Supermemory 中 Spaces 的实现：
- `ContainerTagListType` 是后端返回的空间类型，包含 `id`, `name`, `emoji`, `containerTag`, `createdAt`, `updatedAt`
- 每个记忆通过 `containerTag` 字段关联到 Space
- API 端点：CRUD Spaces、搜索时按 `containerTags` 过滤
- UI：`SpaceSelector`（Header 按钮）+ `SelectSpacesModal`（弹窗）+ `AddSpaceModal`（创建弹窗）
- 支持最近使用、搜索、批量删除、编辑名称

---

## 2. 数据模型

### 2.1 后端 (Python / SQLModel / Pydantic)

#### Memory 模型扩展

```python
# emerald/db/models.py (现有 Memory 模型增加字段)
class Memory(Base):
    __tablename__ = "memories"

    # ... 现有字段
    container_tag: str = Field(default="default", index=True)
    container_tag_name: str = Field(default="My Space")
    container_tag_emoji: str = Field(default="📁")
```

#### Space 模型（新增）

```python
# emerald/db/models.py
class Space(Base):
    __tablename__ = "spaces"

    id: int = Field(primary_key=True)
    container_tag: str = Field(unique=True, index=True)  # 唯一标识
    name: str = Field(default="My Space")
    emoji: str = Field(default="📁")
    entity_id: str = Field(index=True)  # 归属实体
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
```

#### Pydantic Schema

```python
# emerald/api/schemas/spaces.py (新增)
class SpaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    emoji: str = Field(default="📁", max_length=10)
    entity_id: str

class SpaceUpdate(BaseModel):
    name: str | None = None
    emoji: str | None = None

class SpaceResponse(BaseModel):
    container_tag: str
    name: str
    emoji: str
    entity_id: str
    memory_count: int
    created_at: datetime
    updated_at: datetime
```

### 2.2 前端 (TypeScript)

```typescript
// apps/web/src/lib/types.ts (新增)
export interface Space {
  containerTag: string;
  name: string;
  emoji: string;
  entityId: string;
  memoryCount: number;
  createdAt: string;
  updatedAt: string;
}

// Memory 类型扩展
export interface Memory {
  // ... 现有字段
  containerTag?: string;
  containerTagName?: string;
  containerTagEmoji?: string;
}

export interface SearchMemory {
  // ... 现有字段
  containerTag?: string;
  containerTagName?: string;
  containerTagEmoji?: string;
}
```

---

## 3. API 设计

### 3.1 新增端点

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/spaces` | 列出某 entity_id 下的所有 Spaces（含 memory_count） |
| `POST` | `/v1/spaces` | 创建新 Space |
| `PATCH` | `/v1/spaces/{container_tag}` | 更新 Space 名称/emoji |
| `DELETE` | `/v1/spaces/{container_tag}` | 删除 Space（可选迁移记忆到 default） |

### 3.2 现有端点扩展

| Method | Path | Change |
|--------|------|--------|
| `POST` | `/v1/memories` | 新增可选参数 `container_tag` |
| `POST` | `/v1/search` | filters 支持 `container_tag` 精确匹配 |

### 3.3 请求/响应示例

```json
// GET /v1/spaces?entity_id=user_alex
// Response:
{
  "data": [
    {
      "container_tag": "default",
      "name": "My Space",
      "emoji": "📁",
      "entity_id": "user_alex",
      "memory_count": 42,
      "created_at": "...",
      "updated_at": "..."
    },
    {
      "container_tag": "work",
      "name": "Work",
      "emoji": "💼",
      "entity_id": "user_alex",
      "memory_count": 15,
      "created_at": "...",
      "updated_at": "..."
    }
  ]
}

// POST /v1/spaces
// Body: { "name": "Ideas", "emoji": "💡", "entity_id": "user_alex" }
// Response: { "data": { "container_tag": "ideas", "name": "Ideas", "emoji": "💡", ... } }

// POST /v1/memories (with space)
// Body: { "content": "...", "entity_id": "user_alex", "container_tag": "work" }

// POST /v1/search (filter by space)
// Body: { "q": "...", "entity_id": "user_alex", "filters": { "container_tag": "work" } }
```

---

## 4. 前端架构

### 4.1 组件树

```
Sidebar
├── Logo / Brand
├── SpaceSelector ─────────────────────── SelectSpacesModal
│   ├── 当前 Space 显示（emoji + name）       ├── 分类导航（All / My Spaces）
│   └── 下拉箭头                              ├── 搜索框
│                                              ├── 最近使用列表
├── Nav Items                                 ├── 全部 Spaces 列表（可编辑/删除）
│   ├── Dashboard                             ├── Bulk delete 模式
│   ├── Memories                              └── New Space 按钮
│   ├── Graph                                      └── AddSpaceModal
│   └── Settings                                      ├── 名称输入
│                                                    └── Emoji 选择器
└── Chat / Collapse
```

### 4.2 组件详细设计

#### SpaceGlyph
- 纯展示组件
- 接收 `emoji: string` + `size?: number`
- 渲染 emoji 文本或一个带背景的 fallback

#### SpaceSelector（Sidebar 集成）
- 位置：Sidebar Logo 下方，Nav Items 上方
- 显示当前 Space 的 emoji + name
- 点击打开 SelectSpacesModal
- 加载状态显示骨架屏
- 对齐 Supermemory 的 `SpaceSelector` 组件

#### SelectSpacesModal
- 全屏 Dialog（桌面）/ Drawer（移动端）
- **左侧分类栏**：All Spaces / My Spaces / 其他分类
- **搜索框**：实时过滤 Space 列表
- **最近使用**：localStorage 记录最近 5 个 Space
- **Space 行**：radio 选择 + hover 显示编辑/删除按钮
- **Bulk delete 模式**：多选 → 确认删除
- **底部**：New Space 按钮
- 对齐 Supermemory 的 `SelectSpacesModal` 组件

#### AddSpaceModal
- Dialog 弹窗
- Emoji 选择器（grid 展示常用 emoji）
- Space 名称输入
- 创建按钮
- 对齐 Supermemory 的 `AddSpaceModal` 组件

### 4.3 Zustand Store 变更

```typescript
// apps/web/src/stores/app.ts (扩展)
interface AppState {
  // ... 现有字段

  // Spaces
  selectedSpaceTag: string;      // 当前选中的 Space tag
  spaces: Space[];               // Spaces 列表
  spacesLoading: boolean;

  // Actions
  setSelectedSpaceTag: (tag: string) => void;
  setSpaces: (spaces: Space[]) => void;
  setSpacesLoading: (v: boolean) => void;

  // Space CRUD helpers
  createSpace: (name: string, emoji: string) => Promise<Space>;
  updateSpace: (tag: string, data: Partial<Space>) => Promise<void>;
  deleteSpace: (tag: string) => Promise<void>;
}
```

### 4.4 API Client 扩展

```typescript
// apps/web/src/lib/api.ts (扩展)
class EmeraldClient {
  // ... 现有方法

  // Spaces
  async listSpaces(entityId: string): Promise<Space[]>
  async createSpace(name: string, emoji: string, entityId: string): Promise<Space>
  async updateSpace(tag: string, data: { name?: string; emoji?: string }): Promise<Space>
  async deleteSpace(tag: string, migrateToDefault?: boolean): Promise<void>

  // 搜索扩展：自动添加 container_tag filter
  // search() 的 filters 参数已支持
}
```

### 4.5 Mock 数据

```typescript
// apps/web/src/lib/mock-data.ts (扩展)
export const MOCK_SPACES: Space[] = [
  { containerTag: "default", name: "My Space", emoji: "📁", memoryCount: 42, ... },
  { containerTag: "work", name: "Work", emoji: "💼", memoryCount: 15, ... },
  { containerTag: "ideas", name: "Ideas", emoji: "💡", memoryCount: 8, ... },
  { containerTag: "research", name: "Research", emoji: "📚", memoryCount: 12, ... },
];

// MOCK_MEMORIES 每条增加 containerTag 字段
// getMockSearchResults 支持按 container_tag 过滤
```

---

## 5. 页面集成

### 5.1 Dashboard
- 加载时读取 `selectedSpaceTag`
- 统计卡片显示当前 Space 的记忆数量
- "Recently Saved" 列表按 Space 过滤

### 5.2 Memories 页面
- 搜索时自动传入 `filters.containerTag`
- 过滤标签栏显示当前 Space
- 记忆卡片显示所属 Space 标签

### 5.3 Graph 页面
- 搜索时自动传入 `filters.containerTag`
- 图谱节点只显示当前 Space 的记忆

### 5.4 Settings 页面
- 在 Connection 或 API Keys 区域可查看当前 Space 信息

---

## 6. 数据流

```
1. 用户打开应用
   → useAppStore.hydrateFromStorage()
   → 恢复 selectedSpaceTag (默认 "default")
   → API: GET /v1/spaces?entity_id=xxx
   → Store: setSpaces([])

2. 用户切换 Space
   → SpaceSelector 点击 → SelectSpacesModal 打开
   → 用户选择某个 Space
   → Store: setSelectedSpaceTag("work")
   → localStorage: 保存选择
   → 所有页面 reactively 更新查询

3. 用户添加记忆到 Space
   → AddMemoryModal 提交
   → API: POST /v1/memories { container_tag: "work" }

4. 用户创建 Space
   → AddSpaceModal 提交
   → API: POST /v1/spaces { name: "Ideas", emoji: "💡" }
   → Store: 刷新 spaces 列表
   → 自动切换到新 Space
```

---

## 7. 迁移策略

### 7.1 向后兼容
- 现有记忆（无 container_tag）自动归属于 `default` Space
- `container_tag` 字段有默认值 `"default"`
- Space API 自动为每个 entity_id 创建 `default` Space（如果不存在）
- 前端 `selectedSpaceTag` 默认 `"default"`
- 所有现有页面功能不受影响

### 7.2 数据库迁移
```sql
-- Alembic migration
ALTER TABLE memories ADD COLUMN container_tag VARCHAR(100) NOT NULL DEFAULT 'default';
ALTER TABLE memories ADD COLUMN container_tag_name VARCHAR(100) NOT NULL DEFAULT 'My Space';
ALTER TABLE memories ADD COLUMN container_tag_emoji VARCHAR(10) NOT NULL DEFAULT '📁';
CREATE INDEX ix_memories_container_tag ON memories (container_tag);

CREATE TABLE spaces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    container_tag VARCHAR(100) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL DEFAULT 'My Space',
    emoji VARCHAR(10) NOT NULL DEFAULT '📁',
    entity_id VARCHAR(100) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_spaces_entity_id ON spaces (entity_id);
```

---

## 8. 实现顺序

| # | 任务 | 依赖 | 预计 |
|---|------|------|------|
| 1 | 后端: Memory 模型增加 container_tag | - | ~30min |
| 2 | 后端: Space 模型 + 迁移 | 1 | ~30min |
| 3 | 后端: Spaces API 端点（CRUD） | 2 | ~1h |
| 4 | 后端: 搜索/写入支持 container_tag | 1, 3 | ~30min |
| 5 | 前端: types.ts 新增 Space 类型 | - | ~10min |
| 6 | 前端: API client 新增 spaces 方法 | 5 | ~20min |
| 7 | 前端: Zustand store 增加 space 状态 | 5 | ~20min |
| 8 | 前端: 创建 SpaceGlyph 组件 | - | ~10min |
| 9 | 前端: 创建 AddSpaceModal 组件 | 8 | ~30min |
| 10 | 前端: 创建 SelectSpacesModal 组件 | 8, 9 | ~1h |
| 11 | 前端: 创建 SpaceSelector 组件 | 10 | ~20min |
| 12 | 前端: Sidebar 集成 SpaceSelector | 11 | ~15min |
| 13 | 前端: Spaces 集成到所有页面 | 7 | ~20min |
| 14 | 前端: 更新 mock-data | 5 | ~20min |
| 15 | 完整测试验收 | 全部 | ~30min |

**总计：~5-6 小时**

---

## 9. 未涵盖的范围（后续迭代）

- 移动端 Drawer 适配（Supermemory 的 `useIsMobile` + Drawer）
- Plugin/集成 Space（Supermemory 的 `detectPluginSpace`）
- Auto Space（Nova 自动分配 Space）
- Space 内搜索（当前是整个 entity 搜索 + 过滤）
- Space 权限/共享
