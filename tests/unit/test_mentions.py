"""Unit tests for deterministic rule-based mention extraction (B3 NER, #22).

The rule/mock extraction path must produce mentions deterministically
without any LLM call — the quality suite's 提及精度 section relies on this.
"""

from __future__ import annotations

from emerald.core.mentions import (
    DEFAULT_KNOWN_ENTITIES,
    VALID_MENTION_TYPES,
    Mention,
    RuleMentionExtractor,
)


class TestMention:
    def test_mention_fields(self):
        m = Mention(
            surface_form="谷歌",
            canonical_form="Google",
            type="organization",
            confidence=0.9,
        )
        assert m.surface_form == "谷歌"
        assert m.canonical_form == "Google"
        assert m.type == "organization"
        assert m.confidence == 0.9

    def test_mention_defaults(self):
        m = Mention(surface_form="X")
        assert m.canonical_form == "X"
        assert m.type == "concept"
        assert m.confidence == 0.9

    def test_to_dict_roundtrip(self):
        m = Mention(surface_form="谷歌", canonical_form="Google", type="organization")
        assert m.to_dict() == {
            "surface_form": "谷歌",
            "canonical_form": "Google",
            "type": "organization",
            "confidence": 0.9,
        }

    def test_valid_mention_types_is_a_closed_taxonomy(self):
        assert {
            "person",
            "organization",
            "location",
            "technology",
            "datetime",
            "role",
            "concept",
        } == VALID_MENTION_TYPES


class TestRuleMentionExtractor:
    def test_extracts_known_entities_with_correct_types(self):
        mentions = RuleMentionExtractor().extract("用户用 Python 写代码，在 Google 工作")
        assert [m.canonical_form for m in mentions] == ["Python", "Google"]
        assert [m.type for m in mentions] == ["technology", "organization"]

    def test_empty_text_returns_empty(self):
        assert RuleMentionExtractor().extract("") == []
        assert RuleMentionExtractor().extract("   ") == []

    def test_no_match_returns_empty(self):
        assert RuleMentionExtractor().extract("没有已知实体的一段话") == []

    def test_same_entity_yields_one_mention_per_text(self):
        mentions = RuleMentionExtractor().extract("Python 很好，但 Python 也有缺点")
        assert len(mentions) == 1

    def test_preserves_original_surface_casing(self):
        mentions = RuleMentionExtractor().extract("我用 GOOGLE 搜索")
        assert mentions[0].surface_form == "GOOGLE"
        assert mentions[0].canonical_form == "Google"

    def test_order_is_by_first_occurrence(self):
        mentions = RuleMentionExtractor().extract("Stripe 用 Rust，Google 用 Python")
        assert [m.canonical_form for m in mentions] == [
            "Stripe",
            "Rust",
            "Google",
            "Python",
        ]

    def test_custom_gazetteer_overrides_default(self):
        ext = RuleMentionExtractor(known_entities={"北京": ("北京", "location")})
        mentions = ext.extract("用户住在北京")
        assert len(mentions) == 1
        assert mentions[0].canonical_form == "北京"
        assert mentions[0].type == "location"
        # The default gazetteer must not leak in.
        assert ext.extract("用户用 Python 写代码") == []

    def test_deterministic_across_runs(self):
        ext = RuleMentionExtractor()
        text = "用户在 Google 用 Python，也在 Stripe 用 Rust"
        assert ext.extract(text) == ext.extract(text)

    def test_no_false_positive_inside_longer_ascii_words(self):
        """Word boundaries: 'rust' must not fire inside 'trust'."""
        mentions = RuleMentionExtractor().extract("We trust the process")
        assert mentions == []

    def test_boundaries_respect_adjacent_punctuation(self):
        """Punctuation-adjacent mentions still match ('Python' etc.)."""
        mentions = RuleMentionExtractor().extract("(Python) 是门好语言")
        assert [m.canonical_form for m in mentions] == ["Python"]

    def test_cjk_keys_need_no_ascii_boundary(self):
        ext = RuleMentionExtractor(known_entities={"北京": ("北京", "location")})
        assert len(ext.extract("用户住在北京市")) == 1
        assert ext.extract("用户住在北京市")[0].surface_form == "北京"

    def test_default_gazetteer_is_populated(self):
        assert "python" in DEFAULT_KNOWN_ENTITIES
        assert "google" in DEFAULT_KNOWN_ENTITIES
