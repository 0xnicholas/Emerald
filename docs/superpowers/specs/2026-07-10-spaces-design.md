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

### 2.1 后端 (Neo4j / Pydantic)

Emerald 使用 **Neo4j 图数据库**（`GraphStore` in `emerald/core/graph.py`）。
Memory 是 `:Memory` 标签节点，通过 `[:HAS_MEMORY]` 关系连接到 `:Entity` 节点。

#### Memory 节点增加属性

`create_memory()` Cypher 查询增加 `container_tag` 属性：

```cypher
MERGE (e:Entity {id: $entity_id})
CREATE (m:Memory {
    id: $id,
    entity_id: $entity_id,
    content: $content,
    container_tag: $container_tag,  -- NEW
    memory_type: $memory_type,
    confidence: $confidence,
    ...
})
CREATE (e)-[:HAS_MEMORY]->(m)
```

Memory 节点**只存 `container_tag` 字符串**（指向 Space 的标识键，如 `"work"`）。
Space 的名称和 emoji 存在独立的 Space 节点上，避免冗余和数据不一致。

#### Space 节点（新增 `:Space` 标签）

```cypher
// 创建 Space 节点 + 关联到 Entity
MERGE (e:Entity {id: $entity_id})
CREATE (s:Space {
    container_tag: $container_tag,  -- 唯一标识（如 "work", "ideas"）
    name: $name,                    -- 显示名称（如 "Work"）
    emoji: $emoji,                  -- Emoji 图标（如 "💼"）
    entity_id: $entity_id,
    created_at: datetime(),
    updated_at: datetime()
})
CREATE (e)-[:HAS_SPACE]->(s)
```

#### 关系图谱

```
(:Entity)-[:HAS_SPACE]->(:Space {container_tag: "work"})
(:Entity)-[:HAS_MEMORY]->(:Memory {..., container_tag: "work"})
```

> **设计决策**：Memory 不通过关系直连 Space。通过 `container_tag` 属性过滤 +
> Space 节点管理元信息，好处是：(1) 创建记忆时无需额外写关系；(2) Space 重命名
> 只需改 Space 节点一处；(3) 删除 Space 时只需更新 `container_tag` 属性，不改关系。

#### GraphStore 新增方法

```python
# emerald/core/graph.py (新增)
async def create_space(self, container_tag: str, name: str, emoji: str, entity_id: str) -> dict
async def list_spaces(self, entity_id: str) -> list[dict]
async def get_space(self, container_tag: str, entity_id: str) -> dict | None
async def update_space(self, container_tag: str, entity_id: str, name: str | None, emoji: str | None) -> dict
async def delete_space(self, container_tag: str, entity_id: str, migrate_to_default: bool = True) -> None
```

查询 Spaces 时带 memory_count：

```cypher
MATCH (e:Entity {id: $entity_id})-[:HAS_SPACE]->(s:Space)
OPTIONAL MATCH (m:Memory {entity_id: $entity_id, container_tag: s.container_tag})
WHERE m.is_latest = true
RETURN s.container_tag, s.name, s.emoji, s.entity_id, s.created_at, s.updated_at,
       count(m) AS memory_count
```

### 2.2 Pydantic Schema

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

### 2.3 前端 (TypeScript)

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

// Memory 类型扩展（只加 containerTag，Space 名从 Space 对象获取）
export interface Memory {
  // ... 现有字段
  containerTag?: string;
}

export interface SearchMemory {
  // ... 现有字段
  containerTag?: string;
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

### 4.3 Space 状态管理：URL 优先（对齐 Supermemory）

与 Supermemory 一致，使用 **URL query param** 存储当前选中的 Space：

```typescript
// apps/web/src/hooks/use-space.ts (新增)
import { useSearchParams } from "next/navigation"
import { useCallback } from "react"

export const DEFAULT_SPACE_TAG = "default"
const SPACE_PARAM = "space"

export function useSelectedSpace() {
  const [searchParams, setSearchParams] = useSearchParams()
  const selectedSpaceTag = searchParams.get(SPACE_PARAM) ?? DEFAULT_SPACE_TAG

  const setSelectedSpaceTag = useCallback((tag: string) => {
    const next = new URLSearchParams(searchParams.toString())
    if (tag === DEFAULT_SPACE_TAG) {
      next.delete(SPACE_PARAM)
    } else {
      next.set(SPACE_PARAM, tag)
    }
    setSearchParams(next, { scroll: false })
  }, [searchParams, setSearchParams])

  return { selectedSpaceTag, setSelectedSpaceTag }
}
```

> **理由**：URL 方式让 Space 选择反映在 URL（`?space=work`），可分享、可刷新保留，
> 浏览器前进/后退自动切换 Space。default Space 不显示在 URL 中保持简洁。

#### 配套 Hook：useContainerTags

```typescript
// apps/web/src/hooks/use-container-tags.ts (新增)
export function useContainerTags(entityId: string) {
  const { data: spaces = [], isLoading } = useQuery({
    queryKey: ["container-tags", entityId],
    queryFn: () => getClient().listSpaces(entityId),
    staleTime: 30_000,
  })
  return { spaces, isLoading }
}
```

#### Space 排序规则

```typescript
// apps/web/src/lib/spaces.ts (新增)
export function compareSpaces(a: Space, b: Space): number {
  // 1. default 始终在第一位
  if (a.containerTag === "default") return -1
  if (b.containerTag === "default") return 1
  // 2. 用户创建的有名 Space 其次
  // 3. 自动创建的 Space（name === `Space ${tag}`）排最后
  const aAuto = a.name === `Space ${a.containerTag}`
  const bAuto = b.name === `Space ${b.containerTag}`
  if (aAuto && !bAuto) return 1
  if (!aAuto && bAuto) return -1
  // 4. 按名称字母序
  return a.name.localeCompare(b.name)
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
- 页面从 URL 读取 `selectedSpaceTag`（`useSelectedSpace()`）
- 顶部区域显示当前 Space 名称作为上下文标识
- 统计卡片显示当前 Space 的记忆数量
- "Recently Saved" 列表按 Space 过滤
- 空 Space 显示 "This space is empty. Add your first memory!" 提示

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
1. 用户打开应用（/ 或 /memories）
   → URL 参数 ?space=work（若无则默认 "default"）
   → API: GET /v1/spaces?entity_id=xxx
   → React Query 缓存 spaces 列表
   → 各页面根据 selectedSpaceTag 过滤查询

2. 用户切换 Space
   → SpaceSelector 点击 → SelectSpacesModal 打开
   → 用户选择某个 Space
   → useSelectedSpace().setSelectedSpaceTag("work")
   → URL 更新为 ?space=work
   → React Query keys 变化 → 所有页面自动重新查询

3. 用户添加记忆到 Space
   → AddMemoryModal 提交，携带当前 selectedSpaceTag
   → API: POST /v1/memories { container_tag: "work" }
   → 成功后 invalidate 查询

4. 用户创建 Space
   → AddSpaceModal 提交
   → API: POST /v1/spaces { name: "Ideas", emoji: "💡" }
   → invalidateQueries(["container-tags"])
   → URL 切换到新 Space（setSelectedSpaceTag(newTag)）

5. 用户重命名 Space（乐观更新）
   → mutate 立即更新缓存中的 Space 名称
   → API: PATCH /v1/spaces/{tag}
   → 成功：保持更新
   → 失败：回滚缓存，toast 提示错误
```

#### 乐观更新模式（重命名）

```typescript
// hooks/use-project-mutations.ts
const renameSpaceMutation = useMutation({
  mutationFn: ({ tag, name }: { tag: string; name: string }) =>
    getClient().updateSpace(tag, { name }),
  onMutate: async ({ tag, name }) => {
    await queryClient.cancelQueries({ queryKey: ["container-tags"] })
    const previous = queryClient.getQueryData(["container-tags"])
    queryClient.setQueryData<Space[]>(["container-tags"], (old) =>
      old?.map(s => s.containerTag === tag ? { ...s, name } : s)
    )
    return { previous }
  },
  onError: (_err, _vars, context) => {
    if (context?.previous) {
      queryClient.setQueryData(["container-tags"], context.previous)
    }
    toast.error("Failed to rename space")
  },
  onSettled: () => {
    queryClient.invalidateQueries({ queryKey: ["container-tags"] })
  },
})
```

#### 批量删除流程

```
1. SelectSpacesModal 中点击 "Bulk delete" 按钮
   → 切换到批量删除模式：checkbox 替代 radio
   → 底部显示 "Delete selected" 按钮
2. 用户选择多个 Space（default 不可选）
   → 支持 Shift 范围多选
3. 点击 "Delete selected"
   → Dialog 确认：列出所选 Space，输入 DELETE 确认
   → 逐条调用 DELETE /v1/spaces/{tag}
   → 显示进度，完成后 invalidate
```

---

## 7. 迁移策略

### 7.1 向后兼容
- 现有记忆（无 container_tag）自动归属于 `default` Space
- `container_tag` 字段有默认值 `"default"`
- Space API 自动为每个 entity_id 创建 `default` Space（如果不存在）
- 前端 `selectedSpaceTag` 默认 `"default"`
- 所有现有页面功能不受影响

### 7.2 Neo4j 迁移

Neo4j 是 schema-less 的，不需要传统 migration。只需：

1. **应用启动时**：为所有已有 Entity 创建对应的 `default` Space 节点（如果不存在）：

```python
# emerald/core/graph.py
async def ensure_default_spaces(self) -> None:
    """Ensure every Entity has a default Space."""
    result = await self._driver.session().run("""
        MATCH (e:Entity)
        WHERE NOT (e)-[:HAS_SPACE]->(:Space {container_tag: 'default'})
        CREATE (s:Space {
            container_tag: 'default',
            name: 'My Space',
            emoji: '📁',
            entity_id: e.id,
            created_at: datetime(),
            updated_at: datetime()
        })
        CREATE (e)-[:HAS_SPACE]->(s)
        RETURN count(s) AS created
    """)
```

2. **已有 Memory 节点**不需要改动——`container_tag` 属性不存在时，代码按默认值 `"default"` 处理。

3. **可选**：在后续查询中补全缺失的 `container_tag`：

```cypher
MATCH (m:Memory) WHERE m.container_tag IS NULL
SET m.container_tag = 'default'
```

---

## 8. 实现顺序

| # | 任务 | 依赖 | 预计 |
|---|------|------|------|
| 1 | 后端: GraphStore 新增 Space 方法（create/list/update/delete） | - | ~45min |
| 2 | 后端: create_memory() 增加 container_tag 参数 | 1 | ~15min |
| 3 | 后端: Spaces API 端点（CRUD + list） | 1 | ~1h |
| 4 | 后端: 搜索/写入 API 支持 container_tag | 2 | ~20min |
| 5 | 后端: 启动时 ensure_default_spaces | 1 | ~10min |
| 6 | 前端: types.ts 新增 Space 类型 | - | ~10min |
| 7 | 前端: API client 新增 spaces 方法 | 6 | ~20min |
| 8 | 前端: hooks/use-space.ts (URL query state) | - | ~15min |
| 9 | 前端: hooks/use-container-tags.ts | 7 | ~15min |
| 10 | 前端: lib/spaces.ts (排序 + 工具函数) | 6 | ~10min |
| 11 | 前端: 创建 SpaceGlyph 组件 | - | ~10min |
| 12 | 前端: 创建 AddSpaceModal 组件 | 11 | ~30min |
| 13 | 前端: 创建 SelectSpacesModal 组件 | 11, 12 | ~1h |
| 14 | 前端: 创建 SpaceSelector 组件 | 13 | ~20min |
| 15 | 前端: Sidebar 集成 SpaceSelector | 14 | ~15min |
| 16 | 前端: Spaces 集成到所有页面（Dashboard/Memories/Graph） | 8, 9 | ~20min |
| 17 | 前端: 更新 mock-data | 6 | ~20min |
| 18 | 完整测试验收 | 全部 | ~30min |

**总计：~5-6 小时**

---

## 9. 未涵盖的范围（后续迭代）

- 移动端 Drawer 适配（Supermemory 的 `useIsMobile` + Drawer）
- Plugin/集成 Space（Supermemory 的 `detectPluginSpace`）
- Auto Space（Nova 自动分配 Space）
- Space 内搜索（当前是整个 entity 搜索 + 过滤）
- Space 权限/共享
