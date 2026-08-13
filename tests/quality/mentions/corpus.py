"""Deterministic corpus + gazetteer for the mention-precision suite (B3 T1).

The gazetteer drives the rule/mock extraction path — no LLM, fully
deterministic. The corpus labels, for each piece of content, the exact
(canonical_form, type) mentions expected in first-occurrence order.
"""

from __future__ import annotations

# surface key (matched case-insensitively) → (canonical form, mention type)
CORPUS_GAZETTEER: dict[str, tuple[str, str]] = {
    "python": ("Python", "technology"),
    "google": ("Google", "organization"),
    "stripe": ("Stripe", "organization"),
    "alice": ("Alice", "person"),
    "北京": ("北京", "location"),
}

# (content, [(canonical_form, type), ...]) — mention order = first occurrence.
HAPPY_PATH_CORPUS: list[tuple[str, list[tuple[str, str]]]] = [
    ("用户用 Python 写数据管线", [("Python", "technology")]),
    ("用户在 Google 工作", [("Google", "organization")]),
    ("用户在 Stripe 工作", [("Stripe", "organization")]),
    ("Alice 和用户用 Python 写后端", [("Alice", "person"), ("Python", "technology")]),
    (
        "用户用 Python 写后端，同时在 Google 工作",
        [("Python", "technology"), ("Google", "organization")],
    ),
    ("用户住在北京", [("北京", "location")]),
    # No named entities → zero mentions, memory still ingested.
    ("用户喜欢喝咖啡", []),
    ("产品会议改到下周再开", []),
]
