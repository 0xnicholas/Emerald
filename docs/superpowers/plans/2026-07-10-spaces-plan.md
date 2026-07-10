# Spaces Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Spaces (memory collections) feature to Emerald, allowing users to organize memories into named groups with emoji icons.

**Architecture:** Space is a Neo4j `:Space` node linked to `:Entity` via `[:HAS_SPACE]`. Memories get a `container_tag` property. Frontend uses URL query params (`?space=work`) for state, React Query for caching, and a modal-based UI (SelectSpacesModal + AddSpaceModal) matching Supermemory's pattern.

**Tech Stack:** Python/FastAPI/Neo4j (backend), TypeScript/Next.js/Radix UI/TanStack Query (frontend)

**Spec:** `docs/superpowers/specs/2026-07-10-spaces-design.md`

---

### Task 1: GraphStore — add Space methods

**Files:**
- Modify: `emerald/core/graph.py`
- Test: `tests/core/test_graph_spaces.py`

- [ ] **Step 1: Create the test file**

```python
# tests/core/test_graph_spaces.py
"""Tests for GraphStore Space CRUD operations."""

from __future__ import annotations

import pytest


@pytest.fixture
def graph():
    from emerald.core.graph import GraphStore
    g = GraphStore(use_db=False)
    return g


@pytest.mark.asyncio
async def test_create_space(graph):
    space = await graph.create_space(
        container_tag="work",
        name="Work",
        emoji="💼",
        entity_id="user_test",
    )
    assert space["container_tag"] == "work"
    assert space["name"] == "Work"
    assert space["emoji"] == "💼"


@pytest.mark.asyncio
async def test_list_spaces(graph):
    await graph.create_space("work", "Work", "💼", "user_test")
    await graph.create_space("ideas", "Ideas", "💡", "user_test")
    spaces = await graph.list_spaces("user_test")
    assert len(spaces) == 2
    tags = [s["container_tag"] for s in spaces]
    assert "work" in tags
    assert "ideas" in tags


@pytest.mark.asyncio
async def test_list_spaces_with_count(graph):
    await graph.create_space("work", "Work", "💼", "user_test")
    await graph.create_memory(
        content="test memory",
        entity_id="user_test",
        container_tag="work",
    )
    spaces = await graph.list_spaces("user_test")
    assert spaces[0]["memory_count"] >= 1


@pytest.mark.asyncio
async def test_update_space(graph):
    await graph.create_space("work", "Work", "💼", "user_test")
    updated = await graph.update_space("work", "user_test", name="Work v2", emoji="💻")
    assert updated["name"] == "Work v2"
    assert updated["emoji"] == "💻"


@pytest.mark.asyncio
async def test_delete_space(graph):
    await graph.create_space("work", "Work", "💼", "user_test")
    await graph.delete_space("work", "user_test")
    spaces = await graph.list_spaces("user_test")
    assert len(spaces) == 0


@pytest.mark.asyncio
async def test_delete_space_migrate_memories(graph):
    """Deleting a space should migrate its memories to 'default'."""
    await graph.create_space("work", "Work", "💼", "user_test")
    await graph.create_memory(
        content="test",
        entity_id="user_test",
        container_tag="work",
    )
    await graph.delete_space("work", "user_test", migrate_to_default=True)
    # Memory should now have container_tag='default'
    memories = graph._memories.get("user_test", [])
    for m in memories:
        assert m.get("container_tag") == "default"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/nicholasl/Documents/build-whatever/Emerald && python -m pytest tests/core/test_graph_spaces.py -v 2>&1 | head -20`
Expected: Import errors or function not defined

- [ ] **Step 3: Add Space methods to GraphStore**

Add to `emerald/core/graph.py`:

```python
async def create_space(
    self,
    container_tag: str,
    name: str,
    emoji: str,
    entity_id: str,
) -> dict:
    """Create a Space node linked to an Entity. Returns the space dict."""
    self._init_driver()
    now = datetime.now(UTC)

    if self._use_db and self._driver:
        async with self._driver.session() as session:
            result = await session.run(
                """
                MERGE (e:Entity {id: $entity_id})
                ON CREATE SET e.created_at = datetime(), e.type = "user"
                MERGE (s:Space {container_tag: $container_tag, entity_id: $entity_id})
                ON CREATE SET
                    s.name = $name,
                    s.emoji = $emoji,
                    s.entity_id = $entity_id,
                    s.created_at = datetime(),
                    s.updated_at = datetime()
                ON MATCH SET
                    s.name = $name,
                    s.emoji = $emoji,
                    s.updated_at = datetime()
                MERGE (e)-[:HAS_SPACE]->(s)
                RETURN s {.container_tag, .name, .emoji, .entity_id, .created_at, .updated_at} AS space
                """,
                container_tag=container_tag,
                name=name,
                emoji=emoji,
                entity_id=entity_id,
            )
            record = await result.single()
            return dict(record["space"]) if record else {}
    else:
        # In-memory fallback
        now_iso = now.isoformat()
        space = {
            "container_tag": container_tag,
            "name": name,
            "emoji": emoji,
            "entity_id": entity_id,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        key = f"space:{entity_id}"
        if not hasattr(self, "_spaces"):
            self._spaces: dict[str, list[dict]] = {}
        spaces = self._spaces.setdefault(key, [])
        existing = [s for s in spaces if s["container_tag"] == container_tag]
        if existing:
            existing[0].update(name=name, emoji=emoji, updated_at=now_iso)
            return existing[0]
        spaces.append(space)
        return space


async def list_spaces(self, entity_id: str) -> list[dict]:
    """List all Spaces for an entity, with memory_count per space."""
    self._init_driver()
    if self._use_db and self._driver:
        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH (e:Entity {id: $entity_id})-[:HAS_SPACE]->(s:Space)
                OPTIONAL MATCH (m:Memory {entity_id: $entity_id, container_tag: s.container_tag})
                WHERE m.is_latest = true OR m.is_latest IS NULL
                RETURN s {.container_tag, .name, .emoji, .entity_id, .created_at, .updated_at},
                       count(m) AS memory_count
                ORDER BY
                    CASE WHEN s.container_tag = 'default' THEN 0 ELSE 1 END,
                    s.name
                """,
                entity_id=entity_id,
            )
            spaces = []
            async for record in result:
                s = dict(record["s"])
                s["memory_count"] = record["memory_count"]
                spaces.append(s)
            return spaces
    else:
        key = f"space:{entity_id}"
        spaces = getattr(self, "_spaces", {}).get(key, [])
        # Add memory count from in-memory memories
        memories = self._memories.get(entity_id, [])
        for s in spaces:
            s["memory_count"] = sum(
                1 for m in memories
                if m.get("container_tag") == s["container_tag"]
                and m.get("is_latest", True)
            )
        return sorted(spaces, key=lambda s: (0 if s["container_tag"] == "default" else 1, s["name"]))


async def update_space(
    self,
    container_tag: str,
    entity_id: str,
    name: str | None = None,
    emoji: str | None = None,
) -> dict:
    """Update a Space's name and/or emoji. Returns updated space dict."""
    self._init_driver()
    if self._use_db and self._driver:
        sets = []
        params: dict = {"container_tag": container_tag, "entity_id": entity_id}
        if name is not None:
            sets.append("s.name = $name")
            params["name"] = name
        if emoji is not None:
            sets.append("s.emoji = $emoji")
            params["emoji"] = emoji
        sets.append("s.updated_at = datetime()")

        async with self._driver.session() as session:
            # NOTE: Cypher dict syntax uses {{ }} to avoid Python f-string conflicts
            match_clause = "MATCH (s:Space {{container_tag: $container_tag, entity_id: $entity_id}})"
            result = await session.run(
                match_clause + f" SET {', '.join(sets)} RETURN s {{.container_tag, .name, .emoji, .entity_id, .created_at, .updated_at}} AS space",
                **params,
            )
            record = await result.single()
            return dict(record["space"]) if record else {}
    else:
        key = f"space:{entity_id}"
        spaces = getattr(self, "_spaces", {}).get(key, [])
        for s in spaces:
            if s["container_tag"] == container_tag:
                if name is not None:
                    s["name"] = name
                if emoji is not None:
                    s["emoji"] = emoji
                s["updated_at"] = datetime.now(UTC).isoformat()
                return s
        return {}


async def delete_space(
    self,
    container_tag: str,
    entity_id: str,
    migrate_to_default: bool = True,
) -> None:
    """Delete a Space node. If migrate_to_default, reassign memories to 'default'."""
    self._init_driver()
    if self._use_db and self._driver:
        async with self._driver.session() as session:
            if migrate_to_default:
                await session.run(
                    """
                    MATCH (m:Memory {entity_id: $entity_id, container_tag: $container_tag})
                    SET m.container_tag = 'default'
                    """,
                    container_tag=container_tag,
                    entity_id=entity_id,
                )
            await session.run(
                """
                MATCH (e:Entity {id: $entity_id})-[:HAS_SPACE]->(s:Space {container_tag: $container_tag, entity_id: $entity_id})
                DETACH DELETE s
                """,
                container_tag=container_tag,
                entity_id=entity_id,
            )
    else:
        key = f"space:{entity_id}"
        spaces = getattr(self, "_spaces", {}).get(key, [])
        self._spaces[key] = [s for s in spaces if s["container_tag"] != container_tag]
        if migrate_to_default:
            for m in self._memories.get(entity_id, []):
                if m.get("container_tag") == container_tag:
                    m["container_tag"] = "default"


async def ensure_default_spaces(self) -> int:
    """Ensure every Entity has a 'default' Space. Returns count created."""
    self._init_driver()
    if not (self._use_db and self._driver):
        return 0
    async with self._driver.session() as session:
        result = await session.run(
            """
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
            """
        )
        record = await result.single()
        return record["created"] if record else 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/nicholasl/Documents/build-whatever/Emerald && python -m pytest tests/core/test_graph_spaces.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add emerald/core/graph.py tests/core/test_graph_spaces.py
git commit -m "feat(spaces): add Space CRUD methods to GraphStore"
```

---

### Task 2: Update create_memory() to accept container_tag

**Files:**
- Modify: `emerald/core/graph.py` (create_memory method)
- Test: `tests/core/test_graph_spaces.py` (already covers via test_list_spaces_with_count)

- [ ] **Step 1: Add `container_tag` parameter to `create_memory()` signature**

Add `container_tag: str = "default"` to the function signature (after `entity_id`).

- [ ] **Step 2: Update Neo4j Cypher query**

In the `create_memory` Cypher query, add `container_tag: $container_tag` to the CREATE clause. Also add the parameter.

- [ ] **Step 3: Update in-memory fallback**

In the else branch, add `"container_tag": container_tag` to the memory dict.

- [ ] **Step 4: Run tests**

Run: `cd /Users/nicholasl/Documents/build-whatever/Emerald && python -m pytest tests/core/test_graph_spaces.py tests/core/test_graph.py -v`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add emerald/core/graph.py
git commit -m "feat(spaces): add container_tag param to create_memory()"
```

---

### Task 3: Spaces API routes

**Files:**
- Create: `emerald/api/routes/v1/spaces.py`
- Create: `emerald/api/schemas/spaces.py`
- Modify: `emerald/api/schemas/__init__.py`
- Modify: `emerald/api/app.py` (register router)
- Test: `tests/api/test_spaces_api.py`

- [ ] **Step 1: Create schemas**

```python
# emerald/api/schemas/spaces.py
"""Space API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SpaceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    emoji: str = Field(default="📁", max_length=10)
    entity_id: str


class SpaceUpdateRequest(BaseModel):
    name: str | None = None
    emoji: str | None = None


class SpaceResponse(BaseModel):
    container_tag: str
    name: str
    emoji: str
    entity_id: str
    memory_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SpaceListResponse(BaseModel):
    spaces: list[SpaceResponse]
```

- [ ] **Step 2: Export from schemas __init__**

Add to `emerald/api/schemas/__init__.py`:
```python
from emerald.api.schemas.spaces import SpaceCreateRequest, SpaceUpdateRequest, SpaceResponse, SpaceListResponse
```

- [ ] **Step 3: Create the router**

```python
# emerald/api/routes/v1/spaces.py
"""Space routes — CRUD /v1/spaces."""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request

from emerald.api.dependencies import api_key_auth, authorize_entity, rate_limit, require_write_permission
from emerald.api.schemas.spaces import SpaceCreateRequest, SpaceUpdateRequest, SpaceResponse, SpaceListResponse

router = APIRouter(tags=["Spaces"])


def _get_engine(request: Request):
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Memory engine not configured")
    return engine


@router.get("/spaces", dependencies=[Depends(api_key_auth), Depends(rate_limit)])
async def list_spaces(entity_id: str, request: Request) -> dict:
    """List all Spaces for an entity."""
    start = time.perf_counter()
    engine = _get_engine(request)
    authorize_entity(request, entity_id)

    raw = await engine.graph.list_spaces(entity_id)
    spaces = [SpaceResponse(**s) for s in raw]

    return {
        "data": spaces,
        "meta": {
            "request_id": getattr(request.state, "request_id", str(uuid.uuid4())[:8]),
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }


@router.post("/spaces", status_code=201, dependencies=[Depends(api_key_auth), Depends(require_write_permission), Depends(rate_limit)])
async def create_space(body: SpaceCreateRequest, request: Request) -> dict:
    """Create a new Space."""
    start = time.perf_counter()
    authorize_entity(request, body.entity_id)
    engine = _get_engine(request)

    space = await engine.graph.create_space(
        container_tag=body.name.lower().replace(" ", "-"),
        name=body.name,
        emoji=body.emoji,
        entity_id=body.entity_id,
    )

    return {
        "data": SpaceResponse(**space).model_dump(),
        "meta": {
            "request_id": getattr(request.state, "request_id", str(uuid.uuid4())[:8]),
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }


@router.patch("/spaces/{container_tag}", dependencies=[Depends(api_key_auth), Depends(require_write_permission), Depends(rate_limit)])
async def update_space(container_tag: str, body: SpaceUpdateRequest, request: Request) -> dict:
    """Update a Space's name and/or emoji."""
    start = time.perf_counter()
    engine = _get_engine(request)

    # We need entity_id to authorize — get it from query param
    entity_id = request.query_params.get("entity_id", "")
    if not entity_id:
        raise HTTPException(status_code=422, detail="entity_id query parameter required")
    authorize_entity(request, entity_id)

    space = await engine.graph.update_space(
        container_tag=container_tag,
        entity_id=entity_id,
        name=body.name,
        emoji=body.emoji,
    )
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")

    return {
        "data": SpaceResponse(**space).model_dump(),
        "meta": {
            "request_id": getattr(request.state, "request_id", str(uuid.uuid4())[:8]),
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }


@router.delete("/spaces/{container_tag}", dependencies=[Depends(api_key_auth), Depends(require_write_permission), Depends(rate_limit)])
async def delete_space(
    container_tag: str,
    request: Request,
    entity_id: str = "",
    migrate_to_default: bool = True,
) -> dict:
    """Delete a Space. Memories migrate to 'default' by default."""
    start = time.perf_counter()
    if not entity_id:
        raise HTTPException(status_code=422, detail="entity_id query parameter required")
    authorize_entity(request, entity_id)
    engine = _get_engine(request)

    await engine.graph.delete_space(container_tag, entity_id, migrate_to_default=migrate_to_default)

    return {
        "data": {"deleted": True, "container_tag": container_tag},
        "meta": {
            "request_id": getattr(request.state, "request_id", str(uuid.uuid4())[:8]),
            "took_ms": int((time.perf_counter() - start) * 1000),
        },
    }
```

- [ ] **Step 4: Register the router in app.py**

In `emerald/api/app.py`, add:
```python
    from emerald.api.routes.v1 import (
        ...
        spaces as v1_spaces,
        ...
    )
    ...
    app.include_router(v1_spaces.router, prefix="/v1")
```

Also add `authorize_entity` import.

- [ ] **Step 5: Run existing tests to verify no regression**

Run: `cd /Users/nicholasl/Documents/build-whatever/Emerald && python -m pytest tests/ -x -q 2>&1 | tail -10`
Expected: All tests pass (or known failures only)

- [ ] **Step 6: Commit**

```bash
git add emerald/api/schemas/spaces.py emerald/api/schemas/__init__.py emerald/api/routes/v1/spaces.py emerald/api/app.py
git commit -m "feat(spaces): add Spaces CRUD API routes"
```

---

### Task 5: API — search and memory write support container_tag

**Files:**
- Modify: `emerald/api/schemas/memories.py` (AddMemoryRequest + MemoryResponse + route handler)
- Modify: `emerald/api/routes/v1/memories.py` (pass container_tag to engine.add, map in get_memory)
- Modify: `emerald/api/schemas/search.py` (SearchResultItem add container_tag)

- [ ] **Step 1: Add container_tag to AddMemoryRequest**

In `emerald/api/schemas/memories.py`, add:
```python
    container_tag: str | None = Field(
        default=None,
        description="Optional space/container tag to associate this memory with.",
    )
```

- [ ] **Step 2: Update MemoryResponse to include container_tag**

In `emerald/api/schemas/memories.py`:
```python
    container_tag: str = "default"
```

- [ ] **Step 3: Map container_tag in get_memory route handler**

In `emerald/api/routes/v1/memories.py`, in `get_memory()`, add to `MemoryResponse`:
```python
safe = MemoryResponse(
    ...
    container_tag=memory.get("container_tag", "default"),
)
```

- [ ] **Step 4: Add container_tag to SearchResultItem schema**

In `emerald/api/schemas/search.py`, add:
```python
    container_tag: str = "default"
```

- [ ] **Step 5: Pass container_tag through engine.add in route handler**

In `emerald/api/routes/v1/memories.py`, `add_memory()` function, add the new parameter:
```python
result = await engine.add(
    content=body.content,
    entity_id=body.entity_id,
    ...
    container_tag=body.container_tag,  # NEW
)
```

- [ ] **Step 6: Run tests**

Run: `cd /Users/nicholasl/Documents/build-whatever/Emerald && python -m pytest tests/ -x -q 2>&1 | tail -10`
Expected: All tests pass

- [ ] **Step 7: Commit**

```bash
git add emerald/api/schemas/memories.py emerald/api/schemas/search.py emerald/api/routes/v1/memories.py
git commit -m "feat(spaces): add container_tag to memory/search schemas and API"
```

---

### Task 6: Frontend — types and API client

**Files:**
- Modify: `apps/web/src/lib/types.ts`
- Modify: `apps/web/src/lib/api.ts`

- [ ] **Step 1: Add Space interface to types.ts**

```typescript
// apps/web/src/lib/types.ts
export interface Space {
  containerTag: string;
  name: string;
  emoji: string;
  entityId: string;
  memoryCount: number;
  createdAt: string;
  updatedAt: string;
}
```

- [ ] **Step 2: Add containerTag to Memory and SearchMemory**

```typescript
export interface Memory {
  // ... existing fields
  containerTag?: string;
}

export interface SearchMemory {
  // ... existing fields
  containerTag?: string;
}
```

- [ ] **Step 3: Add Space methods to EmeraldClient**

```typescript
// apps/web/src/lib/api.ts
class EmeraldClient {
  // ... existing methods

  async listSpaces(entityId: string): Promise<Space[]> {
    const data = await this.request<{ data: Space[] }>(
      "GET",
      `/v1/spaces?entity_id=${encodeURIComponent(entityId)}`
    );
    return data.data;
  }

  async createSpace(name: string, emoji: string, entityId: string): Promise<Space> {
    const data = await this.request<{ data: Space }>(
      "POST",
      "/v1/spaces",
      { name, emoji, entity_id: entityId }
    );
    return data.data;
  }

  async updateSpace(tag: string, entityId: string, data: { name?: string; emoji?: string }): Promise<Space> {
    const res = await this.request<{ data: Space }>(
      "PATCH",
      `/v1/spaces/${encodeURIComponent(tag)}?entity_id=${encodeURIComponent(entityId)}`,
      data
    );
    return res.data;
  }

  async deleteSpace(tag: string, entityId: string, migrateToDefault = true): Promise<void> {
    await this.request(
      "DELETE",
      `/v1/spaces/${encodeURIComponent(tag)}?entity_id=${encodeURIComponent(entityId)}&migrate_to_default=${migrateToDefault}`
    );
  }
}
```

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/lib/types.ts apps/web/src/lib/api.ts
git commit -m "feat(spaces): add Space types and API client methods"
```

---

### Task 7: Frontend — hooks (useSelectedSpace, useContainerTags, useProjectMutations)

**Files:**
- Create: `apps/web/src/hooks/use-space.ts`
- Create: `apps/web/src/hooks/use-container-tags.ts`
- Create: `apps/web/src/hooks/use-project-mutations.ts`
- Create: `apps/web/src/lib/spaces.ts`

- [ ] **Step 1: Create useSelectedSpace hook**

```typescript
// apps/web/src/hooks/use-space.ts
"use client";

import { useSearchParams, useRouter } from "next/navigation";
import { useCallback } from "react";

export const DEFAULT_SPACE_TAG = "default";
const SPACE_PARAM = "space";

export function useSelectedSpace() {
  const searchParams = useSearchParams();
  const router = useRouter();

  const selectedSpaceTag = searchParams.get(SPACE_PARAM) ?? DEFAULT_SPACE_TAG;

  const setSelectedSpaceTag = useCallback(
    (tag: string) => {
      const params = new URLSearchParams(searchParams.toString());
      if (tag === DEFAULT_SPACE_TAG) {
        params.delete(SPACE_PARAM);
      } else {
        params.set(SPACE_PARAM, tag);
      }
      const next = params.toString();
      router.replace(next ? `?${next}` : window.location.pathname, { scroll: false });
    },
    [searchParams, router]
  );

  return { selectedSpaceTag, setSelectedSpaceTag };
}
```

- [ ] **Step 2: Create useContainerTags hook**

```typescript
// apps/web/src/hooks/use-container-tags.ts
"use client";

import { useQuery } from "@tanstack/react-query";
import { getClient } from "@/lib/api";
import { useAppStore } from "@/stores/app";
import type { Space } from "@/lib/types";

export function useContainerTags() {
  const entityId = useAppStore((s) => s.entityId);

  const { data: spaces = [], isLoading } = useQuery({
    queryKey: ["container-tags", entityId],
    queryFn: () => getClient().listSpaces(entityId),
    enabled: !!entityId,
    staleTime: 30_000,
  });

  return { spaces, isLoading };
}
```

- [ ] **Step 3: Create spaces utility functions**

```typescript
// apps/web/src/lib/spaces.ts
import type { Space } from "@/lib/types";

export const DEFAULT_SPACE_TAG = "default";

export function compareSpaces(a: Space, b: Space): number {
  if (a.containerTag === DEFAULT_SPACE_TAG) return -1;
  if (b.containerTag === DEFAULT_SPACE_TAG) return 1;
  const aAuto = a.name === `Space ${a.containerTag}`;
  const bAuto = b.name === `Space ${b.containerTag}`;
  if (aAuto && !bAuto) return 1;
  if (!aAuto && bAuto) return -1;
  return a.name.localeCompare(b.name);
}

export function getSpaceLabel(spaces: Space[], tag: string): string {
  return spaces.find((s) => s.containerTag === tag)?.name ?? tag;
}
```

- [ ] **Step 4: Create useProjectMutations hook**

```typescript
// apps/web/src/hooks/use-project-mutations.ts
"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { getClient } from "@/lib/api";
import type { Space } from "@/lib/types";
import { useSelectedSpace, DEFAULT_SPACE_TAG } from "./use-space";

export function useProjectMutations() {
  const queryClient = useQueryClient();
  const { selectedSpaceTag, setSelectedSpaceTag } = useSelectedSpace();

  const createSpaceMutation = useMutation({
    mutationFn: ({ name, emoji, entityId }: { name: string; emoji: string; entityId: string }) =>
      getClient().createSpace(name, emoji, entityId),
    onSuccess: (data) => {
      toast.success("Space created!");
      queryClient.invalidateQueries({ queryKey: ["container-tags"] });
      if (data?.containerTag) {
        setSelectedSpaceTag(data.containerTag);
      }
    },
    onError: (err) => {
      toast.error("Failed to create space", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    },
  });

  const updateSpaceMutation = useMutation({
    mutationFn: ({ tag, entityId, name, emoji }: { tag: string; entityId: string; name?: string; emoji?: string }) =>
      getClient().updateSpace(tag, entityId, { name, emoji }),
    onMutate: async ({ tag, name }) => {
      await queryClient.cancelQueries({ queryKey: ["container-tags"] });
      const previous = queryClient.getQueryData<Space[]>(["container-tags"]);
      if (name) {
        queryClient.setQueryData<Space[]>(["container-tags"], (old) =>
          old?.map((s) => (s.containerTag === tag ? { ...s, name: name! } : s))
        );
      }
      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(["container-tags"], context.previous);
      }
      toast.error("Failed to rename space");
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["container-tags"] });
    },
  });

  const deleteSpaceMutation = useMutation({
    mutationFn: ({ tag, entityId }: { tag: string; entityId: string }) =>
      getClient().deleteSpace(tag, entityId),
    onSuccess: () => {
      toast.success("Space deleted");
      queryClient.invalidateQueries({ queryKey: ["container-tags"] });
      if (selectedSpaceTag !== DEFAULT_SPACE_TAG) {
        setSelectedSpaceTag(DEFAULT_SPACE_TAG);
      }
    },
    onError: (err) => {
      toast.error("Failed to delete space", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    },
  });

  return { createSpaceMutation, updateSpaceMutation, deleteSpaceMutation };
}
```

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/hooks/use-space.ts apps/web/src/hooks/use-container-tags.ts apps/web/src/hooks/use-project-mutations.ts apps/web/src/lib/spaces.ts
git commit -m "feat(spaces): add frontend hooks and utilities"
```

---

### Task 8: Frontend — SpaceGlyph and AddSpaceModal components

**Files:**
- Create: `apps/web/src/components/spaces/space-glyph.tsx`
- Create: `apps/web/src/components/spaces/add-space-modal.tsx`

- [ ] **Step 1: Create SpaceGlyph component**

```typescript
// apps/web/src/components/spaces/space-glyph.tsx
"use client";

import { cn } from "@/lib/utils";

interface SpaceGlyphProps {
  emoji: string | null | undefined;
  size?: number;
  className?: string;
}

export function SpaceGlyph({ emoji, size = 18, className }: SpaceGlyphProps) {
  return (
    <span
      className={cn("flex items-center justify-center shrink-0", className)}
      style={{ width: size, height: size, fontSize: size * 0.8 }}
      aria-hidden
    >
      {emoji || "📁"}
    </span>
  );
}
```

- [ ] **Step 2: Create AddSpaceModal component**

```typescript
// apps/web/src/components/spaces/add-space-modal.tsx
"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { X, Loader } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/typography";
import { SpaceGlyph } from "./space-glyph";
import { useProjectMutations } from "@/hooks/use-project-mutations";
import { useAppStore } from "@/stores/app";
import { toast } from "sonner";

const EMOJI_LIST = [
  "📁", "📂", "🗂️", "📚", "📖", "📝", "✏️", "📌",
  "🎯", "🚀", "💡", "⭐", "🔥", "💎", "🎨", "🎵",
  "🏠", "💼", "🛠️", "⚙️", "🔧", "📊", "📈", "💰",
  "🌟", "✨", "🌈", "🌸", "🌿", "🌴", "🐶", "🦊",
  "🦁", "🐼", "🦄", "❤️", "💙", "💚", "💛", "🧡",
];

interface AddSpaceModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function AddSpaceModal({ isOpen, onClose }: AddSpaceModalProps) {
  const [name, setName] = useState("");
  const [emoji, setEmoji] = useState("📁");
  const entityId = useAppStore((s) => s.entityId);
  const { createSpaceMutation } = useProjectMutations();

  const handleClose = () => {
    onClose();
    setName("");
    setEmoji("📁");
  };

  const handleCreate = () => {
    if (!name.trim() || !entityId) return;
    createSpaceMutation.mutate(
      { name: name.trim(), emoji, entityId },
      {
        onSuccess: () => handleClose(),
      }
    );
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
          onClick={handleClose}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            transition={{ duration: 0.15 }}
            className="w-full max-w-md rounded-[18px] border border-surface-border bg-surface-card/80 shadow-lg backdrop-blur-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-surface-border/50 p-4">
              <h2 className="text-lg font-semibold text-fg-primary">Create Space</h2>
              <button onClick={handleClose} className="flex h-8 w-8 items-center justify-center rounded-lg text-fg-muted hover:bg-surface-hover">
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="p-4 space-y-4">
              <div className="flex gap-3 items-center">
                <button
                  type="button"
                  className="flex items-center justify-center w-12 h-12 rounded-xl bg-surface-hover border border-surface-border text-2xl hover:bg-surface-skeleton transition-colors"
                  onClick={() => {}}
                  title="Pick emoji"
                >
                  {emoji}
                </button>
                <div className="flex-1">
                  <Label>Space name</Label>
                  <Input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="My new space"
                    className="mt-1"
                    onKeyDown={(e) => e.key === "Enter" && handleCreate()}
                  />
                </div>
              </div>

              {/* Emoji picker grid */}
              <div>
                <Label level="3" className="text-fg-faint mb-2 block">Choose an icon</Label>
                <div className="grid grid-cols-8 gap-1">
                  {EMOJI_LIST.map((e) => (
                    <button
                      key={e}
                      type="button"
                      onClick={() => setEmoji(e)}
                      className={`w-9 h-9 flex items-center justify-center rounded-lg text-lg transition-colors hover:bg-surface-hover ${
                        emoji === e ? "bg-brand-accent-subtle ring-1 ring-brand-accent" : ""
                      }`}
                    >
                      {e}
                    </button>
                  ))}
                </div>
              </div>

              <div className="flex justify-end gap-3 pt-2">
                <Button variant="ghost" onClick={handleClose}>Cancel</Button>
                <Button onClick={handleCreate} disabled={!name.trim() || createSpaceMutation.isPending}>
                  {createSpaceMutation.isPending ? <Loader className="h-4 w-4 animate-spin mr-1" /> : null}
                  Create Space
                </Button>
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/components/spaces/
git commit -m "feat(spaces): add SpaceGlyph and AddSpaceModal components"
```

---

### Task 9: Frontend — SelectSpacesModal component

**Files:**
- Create: `apps/web/src/components/spaces/select-spaces-modal.tsx`

This is the largest component. It renders a full dialog with:
- Search input
- List of spaces with radio selection
- Recently used spaces
- Edit/rename inline
- Bulk delete mode
- New space button (opens AddSpaceModal)

- [ ] **Step 1: Write the component**

```typescript
// apps/web/src/components/spaces/select-spaces-modal.tsx
"use client";

import { useState, useMemo, useCallback, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  X, Search, Clock, Plus, Trash2, Pencil, Check, Loader,
} from "lucide-react";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/stores/app";
import { useSelectedSpace, DEFAULT_SPACE_TAG } from "@/hooks/use-space";
import { useContainerTags } from "@/hooks/use-container-tags";
import { useProjectMutations } from "@/hooks/use-project-mutations";
import { compareSpaces, getSpaceLabel } from "@/lib/spaces";
import { SpaceGlyph } from "./space-glyph";
import { AddSpaceModal } from "./add-space-modal";
import type { Space } from "@/lib/types";

const RECENTS_KEY = "emerald:space-recents";
const RECENTS_MAX = 5;

interface SelectSpacesModalProps {
  isOpen: boolean;
  onClose: () => void;
}

function readRecents(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(RECENTS_KEY);
    return raw ? JSON.parse(raw).filter((x: unknown) => typeof x === "string") : [];
  } catch { return []; }
}

function writeRecents(tags: string[]) {
  try { localStorage.setItem(RECENTS_KEY, JSON.stringify(tags)); } catch { /* noop */ }
}

function pushRecent(tag: string) {
  const next = [tag, ...readRecents().filter((t) => t !== tag)].slice(0, RECENTS_MAX);
  writeRecents(next);
}

export function SelectSpacesModal({ isOpen, onClose }: SelectSpacesModalProps) {
  const entityId = useAppStore((s) => s.entityId);
  const { selectedSpaceTag, setSelectedSpaceTag } = useSelectedSpace();
  const { spaces, isLoading } = useContainerTags();
  const { deleteSpaceMutation, updateSpaceMutation } = useProjectMutations();

  const [searchQuery, setSearchQuery] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [isBulkMode, setIsBulkMode] = useState(false);
  const [bulkTags, setBulkTags] = useState<Set<string>>(new Set());
  const [editingTag, setEditingTag] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const editRef = useRef<HTMLInputElement>(null);

  const sortedSpaces = useMemo(() => [...spaces].sort(compareSpaces), [spaces]);

  const filteredSpaces = useMemo(() => {
    if (!searchQuery.trim()) return sortedSpaces;
    const q = searchQuery.toLowerCase();
    return sortedSpaces.filter(
      (s) => s.name.toLowerCase().includes(q) || s.containerTag.toLowerCase().includes(q)
    );
  }, [sortedSpaces, searchQuery]);

  const recents = useMemo(
    () => readRecents().map((tag) => spaces.find((s) => s.containerTag === tag)).filter(Boolean) as Space[],
    [spaces]
  );

  const mainList = useMemo(
    () => filteredSpaces.filter((s) => !recents.some((r) => r.containerTag === s.containerTag)),
    [filteredSpaces, recents]
  );

  const handleSelect = useCallback(
    (tag: string) => {
      if (isBulkMode) return;
      setSelectedSpaceTag(tag);
      pushRecent(tag);
      onClose();
    },
    [isBulkMode, setSelectedSpaceTag, onClose]
  );

  const handleBulkToggle = useCallback((tag: string) => {
    setBulkTags((prev) => {
      const next = new Set(prev);
      if (next.has(tag)) next.delete(tag);
      else next.add(tag);
      return next;
    });
  }, []);

  const handleBulkDelete = useCallback(async () => {
    for (const tag of bulkTags) {
      await deleteSpaceMutation.mutateAsync({ tag, entityId });
    }
    setBulkTags(new Set());
    setIsBulkMode(false);
  }, [bulkTags, deleteSpaceMutation, entityId]);

  const startEditing = useCallback((space: Space) => {
    setEditingTag(space.containerTag);
    setEditName(space.name);
  }, []);

  const saveEditing = useCallback(() => {
    if (editingTag && editName.trim()) {
      updateSpaceMutation.mutate({ tag: editingTag, entityId, name: editName.trim() });
    }
    setEditingTag(null);
  }, [editingTag, editName, entityId, updateSpaceMutation]);

  useEffect(() => {
    if (editingTag) editRef.current?.focus();
  }, [editingTag]);

  useEffect(() => {
    if (!isOpen) {
      setSearchQuery("");
      setEditingTag(null);
      setIsBulkMode(false);
      setBulkTags(new Set());
    }
  }, [isOpen]);

  return (
    <>
      <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
        <DialogContent className="sm:max-w-[500px] p-0 gap-0 overflow-hidden rounded-[18px] border-surface-border bg-surface-card/95 backdrop-blur-xl">
          <div className="flex items-center justify-between p-4 border-b border-surface-border/50">
            <div>
              <DialogTitle className="text-base font-semibold text-fg-primary">
                {isBulkMode ? "Delete Spaces" : "Select Space"}
              </DialogTitle>
              <p className="text-xs text-fg-muted mt-0.5">
                {isBulkMode ? "Choose spaces to permanently delete" : "Filter your memories by space"}
              </p>
            </div>
            <div className="flex items-center gap-2">
              {!isBulkMode && (
                <button
                  onClick={() => setIsBulkMode(true)}
                  className="flex items-center gap-1 px-2.5 py-1.5 rounded-full bg-surface-hover text-xs text-fg-muted hover:text-fg-primary transition-colors"
                >
                  <Trash2 className="h-3 w-3" />
                  Bulk delete
                </button>
              )}
              <button onClick={onClose} className="flex h-7 w-7 items-center justify-center rounded-full bg-surface-hover text-fg-muted hover:text-fg-primary">
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>

          <div className="p-4 space-y-3">
            {!isBulkMode && (
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-fg-muted" />
                <input
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search spaces..."
                  className="w-full rounded-xl bg-surface-hover border border-surface-border pl-9 pr-3 py-2 text-sm text-fg-primary placeholder:text-fg-faint focus:outline-none focus:ring-1 focus:ring-surface-ring"
                />
              </div>
            )}

            {isLoading ? (
              <div className="flex justify-center py-8">
                <Loader className="h-5 w-5 animate-spin text-fg-muted" />
              </div>
            ) : (
              <div className="max-h-80 overflow-y-auto space-y-0.5">
                {/* Recently used */}
                {!searchQuery && !isBulkMode && recents.length > 0 && (
                  <>
                    <div className="flex items-center gap-1.5 px-2 py-1 text-[10px] uppercase tracking-wider text-fg-faint">
                      <Clock className="h-3 w-3" />
                      Recently used
                    </div>
                    {recents.map((space) => renderRow(space))}
                    <div className="my-1.5 mx-2 h-px bg-surface-border/50" />
                  </>
                )}

                {/* Main list */}
                {mainList.map((space) => renderRow(space))}
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between border-t border-surface-border/50 p-3">
            {isBulkMode ? (
              <>
                <span className="text-xs text-fg-muted">
                  {bulkTags.size === 0 ? "No spaces selected" : `${bulkTags.size} selected`}
                </span>
                <div className="flex gap-2">
                  <button
                    onClick={() => { setIsBulkMode(false); setBulkTags(new Set()); }}
                    className="text-xs text-fg-muted hover:text-fg-primary px-3 py-1.5"
                  >
                    Cancel
                  </button>
                  <Button
                    size="sm"
                    disabled={bulkTags.size === 0 || deleteSpaceMutation.isPending}
                    onClick={handleBulkDelete}
                    className="bg-red-600 hover:bg-red-700 text-white text-xs"
                  >
                    {deleteSpaceMutation.isPending ? <Loader className="h-3 w-3 animate-spin mr-1" /> : null}
                    Delete selected
                  </Button>
                </div>
              </>
            ) : (
              <>
                <span />
                <button
                  onClick={() => setShowCreate(true)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-surface-hover text-xs text-fg-primary hover:bg-surface-skeleton transition-colors"
                >
                  <Plus className="h-3.5 w-3.5" />
                  New space
                </button>
              </>
            )}
          </div>
        </DialogContent>
      </Dialog>

      <AddSpaceModal isOpen={showCreate} onClose={() => setShowCreate(false)} />
    </>
  );

  function renderRow(space: Space) {
    const isSelected = selectedSpaceTag === space.containerTag;
    const isDefault = space.containerTag === DEFAULT_SPACE_TAG;
    const isEditing = editingTag === space.containerTag;

    if (isEditing) {
      return (
        <div key={space.containerTag} className="flex items-center gap-2 px-2 py-2">
          <SpaceGlyph emoji={space.emoji} size={18} />
          <input
            ref={editRef}
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") saveEditing();
              if (e.key === "Escape") setEditingTag(null);
            }}
            className="flex-1 rounded-lg bg-surface-hover border border-surface-border px-2 py-1 text-sm text-fg-primary focus:outline-none focus:ring-1 focus:ring-surface-ring"
          />
          <button onClick={saveEditing} className="p-1 text-brand-accent hover:bg-surface-hover rounded">
            <Check className="h-3.5 w-3.5" />
          </button>
          <button onClick={() => setEditingTag(null)} className="p-1 text-fg-muted hover:bg-surface-hover rounded">
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      );
    }

    return (
      <div
        key={space.containerTag}
        className={`group flex items-center gap-3 px-3 py-2.5 rounded-xl transition-colors cursor-pointer ${
          isBulkMode
            ? "hover:bg-surface-hover"
            : isSelected
              ? "bg-surface-hover"
              : "hover:bg-surface-hover/50"
        } ${isBulkMode && isDefault ? "opacity-40 cursor-not-allowed" : ""}`}
        onClick={() => {
          if (isBulkMode) {
            if (!isDefault) handleBulkToggle(space.containerTag);
          } else {
            handleSelect(space.containerTag);
          }
        }}
      >
        {/* Radio / Checkbox */}
        <div className={`w-4 h-4 rounded-full border-2 flex items-center justify-center shrink-0 ${
          isBulkMode
            ? bulkTags.has(space.containerTag)
              ? "border-red-400 bg-red-400/10"
              : "border-fg-faint"
            : isSelected
              ? "border-brand-accent"
              : "border-fg-faint"
        }`}>
          {isBulkMode ? (
            bulkTags.has(space.containerTag) && <Check className="h-3 w-3 text-red-300" />
          ) : (
            isSelected && <div className="w-2 h-2 rounded-full bg-brand-accent" />
          )}
        </div>

        <SpaceGlyph emoji={space.emoji} size={20} />
        <span className="flex-1 min-w-0 text-sm text-fg-primary truncate">{space.name}</span>
        {space.memoryCount > 0 && (
          <span className="text-xs text-fg-faint tabular-nums">{space.memoryCount}</span>
        )}

        {/* Edit button */}
        {!isBulkMode && !isDefault && (
          <button
            onClick={(e) => { e.stopPropagation(); startEditing(space); }}
            className="opacity-0 group-hover:opacity-100 p-1 rounded text-fg-muted hover:bg-surface-hover transition-all"
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
        )}
        {!isBulkMode && !isDefault && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              deleteSpaceMutation.mutate({ tag: space.containerTag, entityId });
            }}
            className="opacity-0 group-hover:opacity-100 p-1 rounded text-red-400 hover:bg-surface-hover transition-all"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    );
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add apps/web/src/components/spaces/select-spaces-modal.tsx
git commit -m "feat(spaces): add SelectSpacesModal component"
```

---

### Task 10: Frontend — SpaceSelector and Sidebar integration

**Files:**
- Create: `apps/web/src/components/spaces/space-selector.tsx`
- Modify: `apps/web/src/components/layout/sidebar.tsx`

- [ ] **Step 1: Create SpaceSelector component**

```typescript
// apps/web/src/components/spaces/space-selector.tsx
"use client";

import { useState } from "react";
import { ChevronDown, Loader } from "lucide-react";
import { cn } from "@/lib/utils";
import { useSelectedSpace, DEFAULT_SPACE_TAG } from "@/hooks/use-space";
import { useContainerTags } from "@/hooks/use-container-tags";
import { getSpaceLabel } from "@/lib/spaces";
import { SpaceGlyph } from "./space-glyph";
import { SelectSpacesModal } from "./select-spaces-modal";

export function SpaceSelector() {
  const [modalOpen, setModalOpen] = useState(false);
  const { selectedSpaceTag } = useSelectedSpace();
  const { spaces, isLoading } = useContainerTags();

  const space = spaces.find((s) => s.containerTag === selectedSpaceTag);
  const label = space?.name ?? getSpaceLabel(spaces, selectedSpaceTag);
  const emoji = space?.emoji ?? "📁";

  return (
    <>
      <button
        onClick={() => setModalOpen(true)}
        className="flex items-center gap-2 w-full px-3 py-2 rounded-xl bg-surface-hover/50 border border-surface-border/50 hover:bg-surface-hover hover:border-surface-border transition-all text-left"
        disabled={isLoading}
      >
        {isLoading ? (
          <Loader className="h-4 w-4 animate-spin text-fg-muted shrink-0" />
        ) : (
          <SpaceGlyph emoji={emoji} size={18} />
        )}
        <span className="flex-1 min-w-0 text-sm font-medium text-fg-primary truncate">
          {isLoading ? "Loading..." : label}
        </span>
        <ChevronDown className="h-3.5 w-3.5 text-fg-faint shrink-0" />
      </button>

      <SelectSpacesModal isOpen={modalOpen} onClose={() => setModalOpen(false)} />
    </>
  );
}
```

- [ ] **Step 2: Integrate into Sidebar**

In `apps/web/src/components/layout/sidebar.tsx`:

After the Logo div and before the nav items, add:
```tsx
{sidebarOpen && (
  <div className="px-3 py-2">
    <SpaceSelector />
  </div>
)}
```

And import `SpaceSelector`:
```typescript
import { SpaceSelector } from "@/components/spaces/space-selector";
```

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/components/spaces/space-selector.tsx apps/web/src/components/layout/sidebar.tsx
git commit -m "feat(spaces): add SpaceSelector and integrate into Sidebar"
```

---

### Task 11: Frontend — integrate Spaces into pages (Dashboard, Memories, Graph)

**Files:**
- Modify: `apps/web/src/app/page.tsx` (Dashboard)
- Modify: `apps/web/src/app/memories/page.tsx`
- Modify: `apps/web/src/app/graph/page.tsx`

For each page, the change is:
1. Import `useSelectedSpace` and `useContainerTags`
2. Pass `container_tag: selectedSpaceTag` as a filter to search queries
3. Display current space label in the UI

- [ ] **Step 1: Update Dashboard**

In `apps/web/src/app/page.tsx`, in `AppShell()`:
- Import `useSelectedSpace`, `useContainerTags`, `getSpaceLabel`
- Get `selectedSpaceTag` and spaces
- Pass `container_tag: selectedSpaceTag` to search filters
- Display current space label in the welcome text

- [ ] **Step 2: Update Memories page**

In `apps/web/src/app/memories/page.tsx`:
- Import `useSelectedSpace`
- Get `selectedSpaceTag`
- Pass `filters: { container_tag: selectedSpaceTag }` to `getClient().search()`

- [ ] **Step 3: Update Graph page**

In `apps/web/src/app/graph/page.tsx`:
- Same pattern as Memories page

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/app/page.tsx apps/web/src/app/memories/page.tsx apps/web/src/app/graph/page.tsx
git commit -m "feat(spaces): integrate Spaces filtering into Dashboard, Memories, and Graph pages"
```

---

### Task 12: Frontend — update mock data

**Files:**
- Modify: `apps/web/src/lib/mock-data.ts`

- [ ] **Step 1: Add MOCK_SPACES**

```typescript
export const MOCK_SPACES: Space[] = [
  { containerTag: "default", name: "My Space", emoji: "📁", entityId: "demo_user", memoryCount: 17, createdAt: "2026-01-01T00:00:00Z", updatedAt: "2026-07-10T00:00:00Z" },
  { containerTag: "work", name: "Work", emoji: "💼", entityId: "demo_user", memoryCount: 12, createdAt: "2026-02-15T00:00:00Z", updatedAt: "2026-07-09T00:00:00Z" },
  { containerTag: "ideas", name: "Ideas", emoji: "💡", entityId: "demo_user", memoryCount: 8, createdAt: "2026-03-10T00:00:00Z", updatedAt: "2026-07-08T00:00:00Z" },
  { containerTag: "research", name: "Research", emoji: "📚", entityId: "demo_user", memoryCount: 5, createdAt: "2026-04-01T00:00:00Z", updatedAt: "2026-07-07T00:00:00Z" },
];
```

- [ ] **Step 2: Add containerTag to existing mock memories**

Distribute MOCK_MEMORIES across spaces (some "work", some "ideas", etc.)

- [ ] **Step 3: Update getMockSearchResults to filter by container_tag**

```typescript
export function getMockSearchResults(
  query: string,
  typeFilter?: string,
  containerTag?: string,
): { results: SearchMemory[]; search_mode: string } {
  let filtered = [...baseMemories];
  if (containerTag && containerTag !== "default") {
    filtered = filtered.filter((m) => m.containerTag === containerTag);
  }
  // ... existing filters
}
```

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/lib/mock-data.ts
git commit -m "feat(spaces): update mock data with spaces support"
```

---

### Task 13: Run full test suite

**Files:** N/A — verification only

- [ ] **Step 1: Run all backend tests**

Run: `cd /Users/nicholasl/Documents/build-whatever/Emerald && python -m pytest tests/ -x -q 2>&1 | tail -20`
Expected: All tests pass

- [ ] **Step 2: Build frontend to verify**

Run: `cd /Users/nicholasl/Documents/build-whatever/Emerald/apps/web && npx next build 2>&1 | tail -20`
Expected: Build succeeds with no TypeScript errors

- [ ] **Step 3: Commit any final fixes**

```bash
git add -A
git commit -m "fix(spaces): final adjustments after test suite"
```

---

### Implementation Order Summary

```
Task 1:  GraphStore Space methods (backend)        [~45min]
Task 2:  create_memory container_tag param           [~15min]
Task 3:  Spaces API routes (backend)                 [~1h]
Task 4:  Search/write container_tag support          [~20min]
Task 5:  Frontend types + API client                 [~30min]
Task 6:  Frontend hooks (useSelectedSpace, etc.)     [~30min]
Task 7:  SpaceGlyph + AddSpaceModal components       [~40min]
Task 8:  SelectSpacesModal component                 [~1h]
Task 9:  SpaceSelector + Sidebar integration         [~35min]
Task 10: Integrate Spaces into pages (Dashboard etc.) [~20min]
Task 11: Update mock data                            [~20min]
Task 12: Full test suite                             [~30min]
──────────────────────────────────────────────────────────
Total:  ~6 hours
```
