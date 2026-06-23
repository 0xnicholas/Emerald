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
