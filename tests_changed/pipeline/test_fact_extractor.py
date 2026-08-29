"""Tests for DeepSeekFactExtractor."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from emerald.pipeline.chunking.fact_extractor import DeepSeekFactExtractor


class TestDeepSeekFactExtractor:
    @pytest.fixture
    def extractor(self):
        return DeepSeekFactExtractor(api_key="test-key")

    # ---- helpers ----

    @staticmethod
    def _mock_api_response(*facts: dict) -> AsyncMock:
        """Build an AsyncMock that returns a valid chat completions JSON."""
        mock_post = AsyncMock()
        # Use MagicMock for the response since .json() is a sync method (not async)
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"facts": list(facts)}),
                    }
                }
            ]
        }
        mock_post.return_value = mock_response
        return mock_post

    # ---- tests ----

    @pytest.mark.asyncio
    async def test_extracts_facts_from_valid_response(self, extractor):
        mock_post = self._mock_api_response(
            {"text": "Alex works at Stripe", "type": "fact", "confidence": 0.9,
             "summary": "Job at Stripe"},
            {"text": "Alex prefers morning meetings", "type": "preference",
             "confidence": 0.85, "summary": "Meeting preference"},
        )

        with patch("httpx.AsyncClient.post", new=mock_post):
            facts = await extractor.extract("Alex works at Stripe. He prefers morning meetings.")

        assert len(facts) == 2
        assert facts[0].text == "Alex works at Stripe"
        assert facts[0].memory_type == "fact"
        assert facts[0].confidence == 0.9
        assert facts[0].summary == "Job at Stripe"
        assert facts[1].text == "Alex prefers morning meetings"
        assert facts[1].memory_type == "preference"
        assert facts[1].confidence == 0.85
        assert facts[1].summary == "Meeting preference"

    @pytest.mark.asyncio
    async def test_empty_text_returns_empty(self, extractor):
        facts = await extractor.extract("")
        assert facts == []

    @pytest.mark.asyncio
    async def test_api_failure_returns_empty(self, extractor):
        with patch("httpx.AsyncClient.post", side_effect=Exception("API error")):
            facts = await extractor.extract("Some text")
        assert facts == []

    @pytest.mark.asyncio
    async def test_invalid_type_coerces_to_fact(self, extractor):
        mock_post = self._mock_api_response(
            {"text": "test", "type": "opinion", "confidence": 0.5, "summary": "s"},
        )

        with patch("httpx.AsyncClient.post", new=mock_post):
            facts = await extractor.extract("test")

        assert len(facts) == 1
        assert facts[0].memory_type == "fact"

    @pytest.mark.asyncio
    async def test_confidence_clamped(self, extractor):
        mock_post = self._mock_api_response(
            {"text": "high confidence", "type": "fact", "confidence": 1.5, "summary": "s1"},
            {"text": "low confidence", "type": "fact", "confidence": -0.5, "summary": "s2"},
        )

        with patch("httpx.AsyncClient.post", new=mock_post):
            facts = await extractor.extract("test")

        assert len(facts) == 2
        assert facts[0].confidence == 1.0
        assert facts[1].confidence == 0.0

    @pytest.mark.asyncio
    async def test_empty_text_in_fact_skipped(self, extractor):
        mock_post = self._mock_api_response(
            {"text": "", "type": "fact", "confidence": 0.5, "summary": "s"},
            {"text": "valid", "type": "fact", "confidence": 0.5, "summary": "s"},
        )

        with patch("httpx.AsyncClient.post", new=mock_post):
            facts = await extractor.extract("test")

        assert len(facts) == 1
        assert facts[0].text == "valid"

    @pytest.mark.asyncio
    async def test_duplicate_facts_deduped(self, extractor):
        mock_post = self._mock_api_response(
            {"text": "same fact", "type": "fact", "confidence": 0.5, "summary": "s1"},
            {"text": "same fact", "type": "fact", "confidence": 0.5, "summary": "s2"},
        )

        with patch("httpx.AsyncClient.post", new=mock_post):
            facts = await extractor.extract("test")

        assert len(facts) == 1

    @pytest.mark.asyncio
    async def test_whitespace_only_text_skipped(self, extractor):
        mock_post = self._mock_api_response(
            {"text": "   ", "type": "fact", "confidence": 0.5, "summary": "s"},
            {"text": "valid", "type": "fact", "confidence": 0.5, "summary": "s"},
        )

        with patch("httpx.AsyncClient.post", new=mock_post):
            facts = await extractor.extract("test")

        assert len(facts) == 1
        assert facts[0].text == "valid"

    @pytest.mark.asyncio
    async def test_truncated_at_max_facts(self, extractor):
        """When LLM returns more facts than max_facts, extra are truncated."""
        extractor_small = DeepSeekFactExtractor(api_key="test-key", max_facts=2)
        facts_data = [
            {"text": f"fact {i}", "type": "fact", "confidence": 0.8, "summary": f"s{i}"}
            for i in range(5)
        ]
        mock_post = self._mock_api_response(*facts_data)

        with patch("httpx.AsyncClient.post", new=mock_post):
            facts = await extractor_small.extract("test")

        assert len(facts) == 2

    @pytest.mark.asyncio
    async def test_none_facts_field_returns_empty(self, extractor):
        """If API response has no 'facts' key, returns empty list."""
        mock_post = AsyncMock()
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": json.dumps({})}}]
        }
        mock_post.return_value = mock_response

        with patch("httpx.AsyncClient.post", new=mock_post):
            facts = await extractor.extract("test")

        assert facts == []

    @pytest.mark.asyncio
    async def test_episodic_type_preserved(self, extractor):
        mock_post = self._mock_api_response(
            {"text": "Met Alex for coffee", "type": "episodic", "confidence": 0.7,
             "summary": "Coffee meeting"},
        )

        with patch("httpx.AsyncClient.post", new=mock_post):
            facts = await extractor.extract("test")

        assert len(facts) == 1
        assert facts[0].memory_type == "episodic"

    @pytest.mark.asyncio
    async def test_valid_until_parsed_from_iso8601(self, extractor):
        mock_post = self._mock_api_response(
            {
                "text": "Exam tomorrow",
                "type": "episodic",
                "confidence": 0.9,
                "summary": "Exam",
                "valid_until": "2026-06-24T23:59:59Z",
            },
        )

        with patch("httpx.AsyncClient.post", new=mock_post):
            facts = await extractor.extract("test")

        assert len(facts) == 1
        assert facts[0].valid_until == datetime(2026, 6, 24, 23, 59, 59, tzinfo=UTC)

    @pytest.mark.asyncio
    async def test_internal_type_preserved(self, extractor):
        mock_post = self._mock_api_response(
            {
                "text": "Decided to migrate the database to PostgreSQL 16",
                "type": "fact",
                "internal_type": "decision",
                "confidence": 0.9,
                "summary": "Database migration decision",
            },
        )

        with patch("httpx.AsyncClient.post", new=mock_post):
            facts = await extractor.extract("test")

        assert len(facts) == 1
        assert facts[0].internal_type == "decision"

    @pytest.mark.asyncio
    async def test_invalid_internal_type_coerced_to_none(self, extractor):
        mock_post = self._mock_api_response(
            {
                "text": "Some fact",
                "type": "fact",
                "internal_type": "invalid_type",
                "confidence": 0.8,
                "summary": "s",
            },
        )

        with patch("httpx.AsyncClient.post", new=mock_post):
            facts = await extractor.extract("test")

        assert len(facts) == 1
        assert facts[0].internal_type is None

    @pytest.mark.asyncio
    async def test_valid_until_parsed_without_z(self, extractor):
        mock_post = self._mock_api_response(
            {
                "text": "Report due",
                "type": "episodic",
                "confidence": 0.85,
                "summary": "Report",
                "valid_until": "2026-07-01T12:00:00+08:00",
            },
        )

        with patch("httpx.AsyncClient.post", new=mock_post):
            facts = await extractor.extract("test")

        assert len(facts) == 1
        assert facts[0].valid_until == datetime(2026, 7, 1, 4, 0, 0, tzinfo=UTC)

    @pytest.mark.asyncio
    async def test_invalid_valid_until_ignored(self, extractor):
        mock_post = self._mock_api_response(
            {
                "text": "Plain fact",
                "type": "fact",
                "confidence": 0.8,
                "summary": "Plain",
                "valid_until": "not-a-date",
            },
        )

        with patch("httpx.AsyncClient.post", new=mock_post):
            facts = await extractor.extract("test")

        assert len(facts) == 1
        assert facts[0].valid_until is None


# ---------------------------------------------------------------------------
# Mentions (B3 NER, ticket #22) — LLM path requests them and degrades
# gracefully when they are missing or malformed.
# ---------------------------------------------------------------------------


class TestMentions(TestDeepSeekFactExtractor):
    @pytest.fixture
    def extractor(self):
        return DeepSeekFactExtractor(api_key="test-key")

    @pytest.mark.asyncio
    async def test_mentions_parsed_from_valid_response(self, extractor):
        mock_post = self._mock_api_response(
            {
                "text": "Alex works at Stripe",
                "type": "fact",
                "confidence": 0.9,
                "summary": "Job",
                "mentions": [
                    {"surface_form": "Stripe", "canonical_form": "Stripe",
                     "type": "organization", "confidence": 0.95},
                    {"surface_form": "Alex", "canonical_form": "Alex",
                     "type": "person", "confidence": 0.9},
                ],
            },
        )

        with patch("httpx.AsyncClient.post", new=mock_post):
            facts = await extractor.extract("Alex works at Stripe.")

        assert len(facts) == 1
        assert len(facts[0].mentions) == 2
        stripe, alex = facts[0].mentions
        assert stripe.surface_form == "Stripe"
        assert stripe.canonical_form == "Stripe"
        assert stripe.type == "organization"
        assert stripe.confidence == 0.95
        assert alex.type == "person"

    @pytest.mark.asyncio
    async def test_missing_mentions_field_is_graceful(self, extractor):
        """No mentions key at all → zero mentions, fact still ingested."""
        mock_post = self._mock_api_response(
            {"text": "用户喜欢喝咖啡", "type": "preference",
             "confidence": 0.85, "summary": "咖啡"},
        )
        with patch("httpx.AsyncClient.post", new=mock_post):
            facts = await extractor.extract("用户喜欢喝咖啡")
        assert len(facts) == 1
        assert facts[0].mentions == []

    @pytest.mark.asyncio
    async def test_none_mentions_field_is_graceful(self, extractor):
        mock_post = self._mock_api_response(
            {"text": "text", "type": "fact", "confidence": 0.8,
             "summary": "s", "mentions": None},
        )
        with patch("httpx.AsyncClient.post", new=mock_post):
            facts = await extractor.extract("text")
        assert len(facts) == 1
        assert facts[0].mentions == []

    @pytest.mark.asyncio
    async def test_malformed_mentions_are_skipped(self, extractor):
        mock_post = self._mock_api_response(
            {
                "text": "text",
                "type": "fact",
                "confidence": 0.8,
                "summary": "s",
                "mentions": [
                    "not-a-dict",
                    {"surface_form": "", "canonical_form": "X",
                     "type": "organization", "confidence": 0.9},
                    {"surface_form": "Google", "canonical_form": "Google",
                     "type": "organization", "confidence": 0.9},
                ],
            },
        )
        with patch("httpx.AsyncClient.post", new=mock_post):
            facts = await extractor.extract("text")
        assert len(facts) == 1
        assert len(facts[0].mentions) == 1
        assert facts[0].mentions[0].surface_form == "Google"

    @pytest.mark.asyncio
    async def test_mention_canonical_falls_back_to_surface(self, extractor):
        mock_post = self._mock_api_response(
            {
                "text": "我在用 Gmail",
                "type": "fact",
                "confidence": 0.8,
                "summary": "s",
                "mentions": [
                    {"surface_form": "Gmail", "type": "technology",
                     "confidence": 0.9},
                ],
            },
        )
        with patch("httpx.AsyncClient.post", new=mock_post):
            facts = await extractor.extract("我在用 Gmail")
        mention = facts[0].mentions[0]
        assert mention.surface_form == "Gmail"
        assert mention.canonical_form == "Gmail"

    @pytest.mark.asyncio
    async def test_mention_type_missing_defaults_to_concept(self, extractor):
        mock_post = self._mock_api_response(
            {
                "text": "text",
                "type": "fact",
                "confidence": 0.8,
                "summary": "s",
                "mentions": [
                    {"surface_form": "某物", "canonical_form": "某物",
                     "confidence": 0.9},
                ],
            },
        )
        with patch("httpx.AsyncClient.post", new=mock_post):
            facts = await extractor.extract("text")
        assert facts[0].mentions[0].type == "concept"

    @pytest.mark.asyncio
    async def test_mention_confidence_clamped_and_garbage_safe(self, extractor):
        mock_post = self._mock_api_response(
            {
                "text": "text",
                "type": "fact",
                "confidence": 0.8,
                "summary": "s",
                "mentions": [
                    {"surface_form": "A", "canonical_form": "A",
                     "type": "organization", "confidence": 2.0},
                    {"surface_form": "B", "canonical_form": "B",
                     "type": "organization", "confidence": "oops"},
                ],
            },
        )
        with patch("httpx.AsyncClient.post", new=mock_post):
            facts = await extractor.extract("text")
        assert len(facts[0].mentions) == 2
        assert facts[0].mentions[0].confidence == 1.0
        assert facts[0].mentions[1].confidence == 0.9

    @pytest.mark.asyncio
    async def test_mention_prompt_requests_mentions(self, extractor):
        """The system prompt instructs the LLM to return mentions."""
        captured = {}

        async def capturing_post(*_args, **kwargs):
            captured["messages"] = kwargs["json"]["messages"]
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = {
                "choices": [{"message": {"content": json.dumps({"facts": []})}}],
            }
            return mock_response

        with patch("httpx.AsyncClient.post", new=capturing_post):
            await extractor.extract("text")

        system_prompt = captured["messages"][0]["content"]
        assert "mentions" in system_prompt
        assert "surface_form" in system_prompt
        assert "canonical_form" in system_prompt
