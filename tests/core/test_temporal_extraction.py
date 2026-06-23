"""Tests for deterministic temporal expression extraction.

AGENTS.md requirement:
- "时序完整性" — every fact has temporal context.
"""

from datetime import UTC, datetime

import pytest

from emerald.core.temporal import TemporalExtractor, TimeExpression


@pytest.fixture
def reference_time() -> datetime:
    return datetime(2026, 6, 23, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def extractor(reference_time: datetime) -> TemporalExtractor:
    return TemporalExtractor(reference_time=reference_time)


def _end_of_day(day: datetime) -> datetime:
    return day.replace(hour=23, minute=59, second=59, microsecond=0)


def test_parse_tomorrow(extractor: TemporalExtractor) -> None:
    """明天 / tomorrow / 明日 all resolve to reference + 1 day end-of-day."""
    cases = [
        ("我明天有考试", "明天"),
        ("I have an exam tomorrow", "tomorrow"),
        ("明日は試験です", "明日"),
    ]
    expected = _end_of_day(datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC))
    for text, matched in cases:
        result = extractor.extract(text)
        assert isinstance(result, TimeExpression)
        assert result.text == matched
        assert result.valid_until == expected


def test_parse_next_week(extractor: TemporalExtractor) -> None:
    """下周 / next week resolves to end of Sunday of the next ISO week."""
    cases = [
        ("我下周要交报告", "下周"),
        ("The report is due next week", "next week"),
    ]
    # Reference 2026-06-23 is Tuesday; next week ends on Sunday 2026-07-05.
    expected = _end_of_day(datetime(2026, 7, 5, 12, 0, 0, tzinfo=UTC))
    for text, matched in cases:
        result = extractor.extract(text)
        assert isinstance(result, TimeExpression)
        assert result.text == matched
        assert result.valid_until == expected


def test_parse_days_later(extractor: TemporalExtractor) -> None:
    """N天后 / N days later resolves to reference + N days end-of-day."""
    cases = [
        ("3天后要交作业", 3, "3天后"),
        ("Meeting 5 days later", 5, "5 days later"),
        ("大后天出发", 3, "大后天"),
        ("后天见", 2, "后天"),
    ]
    for text, days, matched in cases:
        result = extractor.extract(text)
        assert isinstance(result, TimeExpression)
        assert result.text == matched
        expected = _end_of_day(datetime(2026, 6, 23 + days, 12, 0, 0, tzinfo=UTC))
        assert result.valid_until == expected


def test_parse_iso_month(extractor: TemporalExtractor) -> None:
    """YYYY-MM or YYYY/MM resolves to the last day of that month."""
    cases = [
        ("项目截止到2026-08", "2026-08"),
        ("Project due 2026/11", "2026/11"),
    ]
    expecteds = [
        _end_of_day(datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)),
        _end_of_day(datetime(2026, 11, 30, 12, 0, 0, tzinfo=UTC)),
    ]
    for (text, matched), expected in zip(cases, expecteds, strict=True):
        result = extractor.extract(text)
        assert isinstance(result, TimeExpression)
        assert result.text == matched
        assert result.valid_until == expected


def test_parse_iso_date(extractor: TemporalExtractor) -> None:
    """YYYY-MM-DD or YYYY/MM/DD resolves to that day end-of-day."""
    cases = [
        ("会议在2026-12-25", "2026-12-25"),
        ("Meeting on 2026/10/10", "2026/10/10"),
    ]
    expecteds = [
        _end_of_day(datetime(2026, 12, 25, 12, 0, 0, tzinfo=UTC)),
        _end_of_day(datetime(2026, 10, 10, 12, 0, 0, tzinfo=UTC)),
    ]
    for (text, matched), expected in zip(cases, expecteds, strict=True):
        result = extractor.extract(text)
        assert isinstance(result, TimeExpression)
        assert result.text == matched
        assert result.valid_until == expected


def test_parse_single_digit_iso_date(extractor: TemporalExtractor) -> None:
    """Single-digit months and days are accepted in ISO date/month patterns."""
    result = extractor.extract("Deadline 2026-8-15")
    assert isinstance(result, TimeExpression)
    assert result.text == "2026-8-15"
    assert result.valid_until == _end_of_day(datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC))


def test_parse_single_digit_iso_month(extractor: TemporalExtractor) -> None:
    """Single-digit months are accepted in ISO month patterns."""
    result = extractor.extract("Deadline 2026/8")
    assert isinstance(result, TimeExpression)
    assert result.text == "2026/8"
    assert result.valid_until == _end_of_day(datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC))


def test_no_temporal_expression(extractor: TemporalExtractor) -> None:
    """Text without a future deadline returns None."""
    cases = [
        "",
        "   ",
        "This is a plain fact.",
        "我喜欢喝咖啡",
        "昨天已经做完了",
        "今天天气不错",
        "前天出去了",
        "The day before yesterday it rained",
        "0天后没有变化",
        "Meeting 0 days later",
    ]
    for text in cases:
        result = extractor.extract(text)
        assert result is None


def test_past_absolute_dates_return_none(extractor: TemporalExtractor) -> None:
    """Absolute dates/months on or before the reference date return None."""
    cases = [
        "会议在2026-06-23",
        "会议在2026-06-22",
        "截止2026-06",
        "截止2026-05",
    ]
    for text in cases:
        assert extractor.extract(text) is None


def test_invalid_absolute_dates_return_none(extractor: TemporalExtractor) -> None:
    """Invalid absolute dates return None without raising."""
    cases = [
        "截止2026-02-30",
        "截止2026-13-01",
        "截止2026-00-10",
    ]
    for text in cases:
        assert extractor.extract(text) is None


def test_numeric_relative_month(extractor: TemporalExtractor) -> None:
    """N个月后 / N months later resolves to reference + N months end-of-day."""
    text = "3个月后要发表论文"
    result = extractor.extract(text)
    assert isinstance(result, TimeExpression)
    assert result.text == "3个月后"
    expected = _end_of_day(datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC))
    assert result.valid_until == expected


def test_month_end_clamping() -> None:
    """Relative months clamp to the last valid day of the target month."""
    reference = datetime(2026, 1, 31, 12, 0, 0, tzinfo=UTC)
    extractor = TemporalExtractor(reference_time=reference)
    result = extractor.extract("1个月后到期")
    assert isinstance(result, TimeExpression)
    assert result.text == "1个月后"
    # January 31 + 1 month clamps to February 28 (non-leap 2026).
    assert result.valid_until == _end_of_day(datetime(2026, 2, 28, 12, 0, 0, tzinfo=UTC))


def test_parse_next_month(extractor: TemporalExtractor) -> None:
    """下个月 / next month resolves to the last day of next month."""
    result = extractor.extract("我下个月要旅行")
    assert isinstance(result, TimeExpression)
    assert result.text == "下个月"
    assert result.valid_until == _end_of_day(datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC))


def test_parse_next_year(extractor: TemporalExtractor) -> None:
    """明年 / next year resolves to the last day of next year."""
    result = extractor.extract("明年要买车")
    assert isinstance(result, TimeExpression)
    assert result.text == "明年"
    assert result.valid_until == _end_of_day(datetime(2027, 12, 31, 12, 0, 0, tzinfo=UTC))
