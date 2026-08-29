"""
Emerald API load test (Locust).

Simulates realistic traffic patterns:
- 70% search queries (read-heavy, most common)
- 15% memory ingestion (add facts)
- 10% profile fetches
- 5% file list

Usage:
    # Start Emerald API first, then:
    locust -f tests/load/locustfile.py --host http://localhost:8000

    # CI smoke test (headless, short run):
    locust -f tests/load/locustfile.py --host http://localhost:8000 \\
        --headless --users 10 --spawn-rate 5 --run-time 30s \\
        --csv reports/load-test

Environment variables:
    EMERALD_API_KEY  — API key for authentication (default: test key)
    EMERALD_ENTITY_ID — Entity to test against (default: load-test-entity)
"""

from __future__ import annotations

import os
import random
import uuid

from locust import HttpUser, between, task
from locust.exception import StopUser

API_KEY = os.environ.get("EMERALD_API_KEY", "em_test1234567890abcdef1234567890ab")
ENTITY_ID = os.environ.get("EMERALD_ENTITY_ID", "load-test-entity")
HEADERS = {"Authorization": f"Bearer {API_KEY}"}

SEARCH_QUERIES = [
    "用户偏好",
    "如何部署",
    "Python 性能优化",
    "数据库连接池配置",
    "API 认证方式",
    "错误处理最佳实践",
    "memory management",
    "分布式系统设计",
    "编码规范",
    "测试策略",
]

MEMORY_CONTENTS = [
    "用户偏好 TypeScript 和函数式编程风格",
    "项目使用 PostgreSQL 作为主数据库",
    "需要支持多语言国际化",
    "每周五下午进行代码审查",
    "系统部署在 AWS us-east-1 区域",
    "API 响应时间要求在 100ms 以内",
]


class EmeraldUser(HttpUser):
    """Simulated Emerald API user with realistic behavior patterns."""

    wait_time = between(0.5, 3.0)  # Think time between operations

    def on_start(self):
        """Verify API is healthy before starting load."""
        with self.client.get("/v1/health", catch_response=True) as resp:
            if resp.status_code != 200:
                resp.failure("Health check failed — API not ready")
                raise StopUser()

    @task(35)
    def search_memory(self):
        """Search the memory graph — most common operation."""
        query = random.choice(SEARCH_QUERIES)
        payload = {
            "q": query,
            "entity_id": ENTITY_ID,
            "search_mode": "memory",
            "top_k": 10,
        }
        with self.client.post(
            "/v1/search",
            json=payload,
            headers=HEADERS,
            catch_response=True,
        ) as resp:
            if resp.status_code == 429:
                resp.success()  # Rate limited is expected under load
            elif resp.status_code not in (200, 401, 404, 422):
                resp.failure(f"Search failed: {resp.status_code} {resp.text[:200]}")

    @task(10)
    def add_memory(self):
        """Ingest a new memory."""
        content = random.choice(MEMORY_CONTENTS)
        payload = {
            "content": content,
            "entity_id": ENTITY_ID,
        }
        with self.client.post(
            "/v1/memories",
            json=payload,
            headers=HEADERS,
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 409, 422):
                resp.success()
            elif resp.status_code == 429:
                resp.success()
            elif resp.status_code not in (401,):
                resp.failure(f"Add failed: {resp.status_code} {resp.text[:200]}")

    @task(7)
    def get_profile(self):
        """Fetch entity profile."""
        with self.client.get(
            f"/v1/profiles/{ENTITY_ID}",
            headers=HEADERS,
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 404):
                resp.success()
            elif resp.status_code not in (401, 429):
                resp.failure(f"Profile failed: {resp.status_code}")

    @task(3)
    def list_files(self):
        """List uploaded files (cursor pagination)."""
        with self.client.get(
            f"/v1/files?entity_id={ENTITY_ID}&page_size=5",
            headers=HEADERS,
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 404):
                resp.success()
            elif resp.status_code not in (401, 429):
                resp.failure(f"List files failed: {resp.status_code}")
