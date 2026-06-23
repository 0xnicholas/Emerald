"""Deterministic temporal expression parser.

Parses Chinese and English temporal expressions in fact text into absolute
``valid_until`` datetimes. No LLM calls — regex + calendar math only.

AGENTS.md requirement:
- "时序完整性" — every fact has temporal context.
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog

logger = structlog.get_logger(__name__)

__all__ = ["TemporalExtractor", "TimeExpression"]


@dataclass(frozen=True)
class TimeExpression:
    """A parsed temporal expression and its absolute deadline."""

    text: str
    valid_until: datetime


_Resolver = Callable[[re.Match[str]], datetime | None]


class TemporalExtractor:
    """Deterministically extract future deadlines from natural language text.

    Relative expressions resolve against ``reference_time`` (default ``now(UTC)``)
    to end-of-day UTC. Absolute month/year expressions resolve to the last day
    of the referenced period.
    """

    def __init__(self, reference_time: datetime | None = None) -> None:
        self.reference_time = reference_time or datetime.now(UTC)
        self._compiled_patterns: list[tuple[re.Pattern[str], _Resolver]] = [
            # Absolute dates first so "2026-08-15" beats "2026-08".
            (re.compile(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}"), self._resolve_iso_date),
            (re.compile(r"\d{4}[-/]\d{1,2}"), self._resolve_iso_month),
            # Non-future day references — explicitly short-circuit to None.
            (
                re.compile(r"今天|昨天|前天|today|yesterday|the day before yesterday"),
                self._resolve_non_future_reference,
            ),
            # Relative days (Chinese longer forms before shorter ones).
            (re.compile(r"大后天"), self._resolve_days_later_fixed(3)),
            (re.compile(r"后天"), self._resolve_days_later_fixed(2)),
            (re.compile(r"明天|明日"), self._resolve_days_later_fixed(1)),
            (re.compile(r"(\d+)天后"), self._resolve_days_later_group),
            (re.compile(r"tomorrow"), self._resolve_days_later_fixed(1)),
            (re.compile(r"(\d+) days later"), self._resolve_days_later_group),
            # Relative weeks.
            (re.compile(r"下周|next week"), self._resolve_next_week),
            # Relative months.
            (re.compile(r"下个月|next month"), self._resolve_next_month),
            (re.compile(r"(\d+)个月后"), self._resolve_months_later_group),
            (re.compile(r"(\d+) months later"), self._resolve_months_later_group),
            # Relative years.
            (re.compile(r"明年|next year"), self._resolve_next_year),
        ]

    def extract(self, text: str) -> TimeExpression | None:
        """Return the first future deadline found in *text*, or ``None``.

        Scans all registered patterns in priority order. A resolver may return
        ``None`` for non-future references (e.g. 今天/昨天/today/yesterday); in
        that case the scan continues so that later future expressions in the
        same text are still discovered.
        """
        for pattern, resolver in self._compiled_patterns:
            match = pattern.search(text)
            if not match:
                continue

            matched_text = match.group(0)
            try:
                valid_until = resolver(match)
            except ValueError:
                logger.debug("temporal.parse_failed", text=text, matched=matched_text)
                continue

            if valid_until is None:
                continue

            return TimeExpression(text=matched_text, valid_until=valid_until)

        return None

    def _end_of_day(self, day: datetime) -> datetime:
        """Return end-of-day UTC for *day*."""
        return day.replace(hour=23, minute=59, second=59, microsecond=0)

    def _resolve_non_future_reference(self, _match: re.Match[str]) -> datetime | None:
        """References to today or the past never produce a future deadline."""
        return None

    def _resolve_days_later_fixed(self, days: int) -> Callable[[re.Match[str]], datetime]:
        def _resolve(_match: re.Match[str]) -> datetime:
            return self._end_of_day(self.reference_time + timedelta(days=days))

        return _resolve

    def _resolve_days_later_group(self, match: re.Match[str]) -> datetime | None:
        days = int(match.group(1))
        if days <= 0:
            return None
        return self._end_of_day(self.reference_time + timedelta(days=days))

    def _resolve_next_week(self, _match: re.Match[str]) -> datetime:
        """End of Sunday of the next ISO week (ISO weeks start on Monday)."""
        # Days from reference to the Sunday at the end of next week.
        isoweekday = self.reference_time.isoweekday()  # Monday=1 ... Sunday=7
        days_ahead = 14 - isoweekday
        sunday = self.reference_time + timedelta(days=days_ahead)
        return self._end_of_day(sunday)

    def _resolve_next_month(self, _match: re.Match[str]) -> datetime:
        year = self.reference_time.year
        month = self.reference_time.month + 1
        if month > 12:
            year += 1
            month -= 12
        last_day = calendar.monthrange(year, month)[1]
        return self._end_of_day(self.reference_time.replace(year=year, month=month, day=last_day))

    def _resolve_months_later_group(self, match: re.Match[str]) -> datetime:
        months = int(match.group(1))
        year = self.reference_time.year
        month = self.reference_time.month + months
        year += (month - 1) // 12
        month = ((month - 1) % 12) + 1
        last_day = calendar.monthrange(year, month)[1]
        day = min(self.reference_time.day, last_day)
        return self._end_of_day(self.reference_time.replace(year=year, month=month, day=day))

    def _resolve_next_year(self, _match: re.Match[str]) -> datetime:
        year = self.reference_time.year + 1
        last_day = calendar.monthrange(year, 12)[1]
        return self._end_of_day(self.reference_time.replace(year=year, month=12, day=last_day))

    def _resolve_iso_date(self, match: re.Match[str]) -> datetime | None:
        raw = match.group(0)
        normalized = raw.replace("/", "-")
        try:
            parsed = datetime.strptime(normalized, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            return None
        if parsed.date() <= self.reference_time.date():
            return None
        return self._end_of_day(parsed)

    def _resolve_iso_month(self, match: re.Match[str]) -> datetime | None:
        raw = match.group(0)
        normalized = raw.replace("/", "-")
        try:
            parsed = datetime.strptime(normalized, "%Y-%m").replace(tzinfo=UTC)
        except ValueError:
            return None
        if (parsed.year, parsed.month) <= (self.reference_time.year, self.reference_time.month):
            return None
        last_day = calendar.monthrange(parsed.year, parsed.month)[1]
        return self._end_of_day(parsed.replace(day=last_day))
