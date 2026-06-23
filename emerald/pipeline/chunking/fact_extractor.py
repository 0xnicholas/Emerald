"""LLM-driven fact extraction from text/conversation content.

Extracts structured facts (type, confidence, summary) using DeepSeek V4-Flash.
Falls back gracefully on any API failure.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
import structlog

from emerald.config import get_settings

logger = structlog.get_logger(__name__)

# Template prompt — format with max_facts before sending.
# The braces {{ and }} are literal JSON braces; .format() renders them as { and }.
_SYSTEM_PROMPT_TEMPLATE = """你是事实提取引擎。从对话/文本中提取细粒度、独立的事实。
每条事实归入以下类型之一：

- fact：实体属性（工作、地点、技能、关系等）
- preference：偏好、习惯、倾向
- episodic：事件/互动记录（临时性）

规则：
1. 每条事实 1-2 句话，脱离上下文可独立理解
2. 不提取问候语、闲聊填充词、纯情感表达
3. 明确陈述 → confidence 0.8-0.95
4. 隐含可推断 → confidence 0.5-0.7
5. 新旧矛盾信息都提取——由关系引擎后续处理
6. 最多 {max_facts} 条。无事实时返回空数组
7. summary 字段为 1 句话简短摘要（与原文保持相同语言），用于搜索/画像展示
8. 若事实有明确 temporal deadline（如 明天、下周、2025-06），
   添加可选 valid_until 字段，ISO-8601 格式（如 2025-06-30T23:59:59Z）

输出严格 JSON：
{{"facts": [
  {{"text": "...", "type": "fact|preference|episodic", "confidence": 0.85,
   "summary": "...", "valid_until": "..."}}
]}}"""


@dataclass
class Fact:
    """A single extracted fact."""

    text: str
    memory_type: str  # "fact" | "preference" | "episodic"
    confidence: float  # 0.0 - 1.0
    summary: str  # Brief summary for search/profile display
    valid_until: datetime | None = None  # Temporal expiry if known


class FactExtractor:
    """Abstract base for LLM-driven fact extraction."""

    async def extract(
        self, text: str, *, entity_context: str | None = None
    ) -> list[Fact]:
        raise NotImplementedError


class DeepSeekFactExtractor(FactExtractor):
    """Fact extraction via DeepSeek V4-Flash (OpenAI-compatible API)."""

    VALID_TYPES = frozenset({"fact", "preference", "episodic"})

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-v4-flash",
        base_url: str = "https://api.deepseek.com",
        max_facts: int = 20,
        timeout: float = 15.0,
        temperature: float = 0.1,
        max_tokens: int = 2000,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._max_facts = max_facts
        self._timeout = timeout
        self._temperature = temperature
        self._max_tokens = max_tokens

    async def extract(
        self, text: str, *, entity_context: str | None = None
    ) -> list[Fact]:
        if not text.strip():
            return []

        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(max_facts=self._max_facts)

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
        ]

        user_content = text
        if entity_context:
            user_content = f"上下文提示：{entity_context}\n\n文本：{text}"
        messages.append({"role": "user", "content": user_content})

        raw = await self._call_api(messages)
        if raw is None:
            return []

        return self._parse_and_validate(raw)

    async def _call_api(
        self,
        messages: list[dict[str, str]],
    ) -> dict[str, Any] | None:
        """Call DeepSeek API. Returns parsed JSON dict, or None on failure.

        First attempts response_format: json_object. On JSON parse failure,
        strips markdown code fences from the raw content string and re-parses.
        """
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._model,
                        "messages": messages,
                        "response_format": {"type": "json_object"},
                        "temperature": self._temperature,
                        "max_tokens": self._max_tokens,
                    },
                )
                response.raise_for_status()
                data = response.json()
                raw_content = data["choices"][0]["message"]["content"]
                return json.loads(raw_content)
        except json.JSONDecodeError:
            logger.warning("fact_extraction.json_parse_failed, trying code fences")
            return self._strip_code_fences(raw_content)
        except KeyError as e:
            logger.warning("fact_extraction.unexpected_api_response", error=str(e))
            return None
        except Exception:
            logger.warning("fact_extraction.api_failed", exc_info=True)
            return None

    @staticmethod
    def _strip_code_fences(raw_content: str) -> dict[str, Any] | None:
        """Strip markdown code fences from raw LLM output, then parse as JSON."""
        stripped = re.sub(r"^```(?:json)?\s*", "", raw_content.strip())
        stripped = re.sub(r"\s*```$", "", stripped)
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return None

    def _parse_and_validate(self, raw: dict[str, Any]) -> list[Fact]:
        """Parse LLM output, validate each fact, return clean list."""
        raw_facts = raw.get("facts", [])
        if not isinstance(raw_facts, list):
            return []

        facts: list[Fact] = []
        seen_texts: set[str] = set()

        for item in raw_facts:
            if not isinstance(item, dict):
                continue

            text = str(item.get("text", "")).strip()
            if not text:
                logger.warning("fact_extraction.empty_text_skipped")
                continue

            # Dedup by normalized text (collapse whitespace to single spaces, lowercase)
            normalized = " ".join(text.split()).lower()
            if normalized in seen_texts:
                continue
            seen_texts.add(normalized)

            # Validate type
            memory_type = str(item.get("type", "fact")).lower()
            if memory_type not in self.VALID_TYPES:
                logger.warning("fact_extraction.invalid_type", type=memory_type)
                memory_type = "fact"

            # Clamp confidence to [0.0, 1.0]
            confidence = float(item.get("confidence", 0.8))
            confidence = max(0.0, min(1.0, confidence))

            summary = str(item.get("summary", ""))[:200]

            valid_until: datetime | None = None
            raw_valid_until = item.get("valid_until")
            if raw_valid_until:
                iso_str = str(raw_valid_until)
                if iso_str.endswith("Z"):
                    iso_str = iso_str[:-1] + "+00:00"
                try:
                    valid_until = datetime.fromisoformat(iso_str)
                except ValueError:
                    logger.debug(
                        "fact_extraction.invalid_valid_until",
                        valid_until=raw_valid_until,
                    )

            facts.append(
                Fact(
                    text=text,
                    memory_type=memory_type,
                    confidence=confidence,
                    summary=summary,
                    valid_until=valid_until,
                )
            )

            if len(facts) >= self._max_facts:
                break

        return facts


def get_fact_extractor() -> FactExtractor | None:
    """Create a DeepSeekFactExtractor if API key is configured, else None."""
    settings = get_settings()
    if not settings.deepseek_api_key:
        logger.info("fact_extraction.disabled", reason="no_api_key")
        return None
    return DeepSeekFactExtractor(
        api_key=settings.deepseek_api_key,
        model=settings.fact_extraction_model,
        base_url=settings.fact_extraction_base_url,
        max_facts=settings.fact_extraction_max_facts,
        timeout=settings.fact_extraction_timeout,
        temperature=settings.fact_extraction_temperature,
        max_tokens=settings.fact_extraction_max_tokens,
    )
