"""Resolve relative time phrases in a recall query into a UTC window.

English and Turkish only. Matching is done on an ASCII-folded, lower-cased copy
of the query with word boundaries, so "bugün", "BUGÜN" and "bugun" behave the
same and words such as "dünya" or "gündem" never match. Windows are computed
here in code (never by a model): [start, end) in UTC, week starts Monday.
Calendar windows (today, this week, since Monday, ...) follow the local wall
clock, so a DST change keeps "yesterday" midnight to midnight. Elapsed windows
("last 24 hours", "son 3 gün", the implicit 24 h) are exact elapsed time in UTC.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bilinc.core.text_fold import fold_text

__all__ = [
    "TimeIntent",
    "local_timezone",
    "mentions_low_signal",
    "parse_time_intent",
    "resolve_timezone",
]

_QUOTES = str.maketrans({"\u2019": "'", "`": "'"})


def _fold(text: str) -> str:
    return fold_text(str(text or "").translate(_QUOTES))


@dataclass(frozen=True)
class TimeIntent:
    start: datetime
    end: datetime
    label: str
    residual_query: str
    implicit: bool = False


def resolve_timezone(name: Optional[str]) -> tzinfo:
    if not name:
        return timezone.utc
    try:
        return ZoneInfo(str(name))
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return timezone.utc


LOCALTIME_PATH = Path("/etc/localtime")


def _valid_zone(name: Optional[str]) -> Optional[tzinfo]:
    name = (name or "").strip()
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def local_timezone(localtime_path: Optional[Path] = None) -> tzinfo:
    """Machine zone as an IANA zone: BILINC_TIMEZONE, then TZ, then /etc/localtime, else UTC."""
    zone = _valid_zone(os.environ.get("BILINC_TIMEZONE"))
    if zone is not None:
        return zone
    zone = _valid_zone((os.environ.get("TZ") or "").lstrip(":"))
    if zone is not None:
        return zone
    try:
        target = os.readlink(localtime_path if localtime_path is not None else LOCALTIME_PATH)
    except OSError:
        return timezone.utc
    marker = "zoneinfo/"
    if marker in target:
        name = target.split(marker, 1)[1]
        # posix/ and right/ are tzdata mirrors of the same zones (right/ counts leap seconds).
        for prefix in ("posix/", "right/"):
            if name.startswith(prefix):
                name = name[len(prefix):]
        zone = _valid_zone(name)
        if zone is not None:
            return zone
    return timezone.utc


_EN_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_TR_DAYS = ["pazartesi", "sali", "carsamba", "persembe", "cuma", "cumartesi", "pazar"]
_EN_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
              "september", "october", "november", "december"]
_TR_MONTHS = ["ocak", "subat", "mart", "nisan", "mayis", "haziran", "temmuz", "agustos",
              "eylul", "ekim", "kasim", "aralik"]
_ABL = r"(?:'?(?:n?dan|n?den|tan|ten))"  # Turkish ablative, optional apostrophe
_UNIT_EN = r"(hours?|days?|weeks?)"
_UNIT_TR = r"(saat|gun|hafta)"

_FILLERS = frozenset(
    """
    what whats what's changed change changes updates update updated new happened happen did do done we i my
    our the a an in on of for from about show me list any is are was were there has have tell give summary recap
    so far ne neler nedir degisti degisen degisiklik degisiklikler degisiklikleri guncelleme guncellemeler
    guncellemeleri guncellemesi yeni var yapildi yaptik yaptim oldu olan olanlar neydi bana goster ozet ozeti
    ozetle hakkinda ile ve mi mu bir kayit kayitlar kadar to date s den beri since
    """.split()
)

_LOW_SIGNAL = re.compile(
    r"\b(chats?|transcripts?|conversations?|sohbet\w*|konusma\w*|transkript\w*)\b"
)


def mentions_low_signal(query: str) -> bool:
    return bool(_LOW_SIGNAL.search(_fold(query)))


def _midnight(local_now: datetime) -> datetime:
    return local_now.replace(hour=0, minute=0, second=0, microsecond=0)


def _monday(local_now: datetime) -> datetime:
    return _midnight(local_now) - timedelta(days=local_now.weekday())


def _month_start(local_now: datetime) -> datetime:
    return _midnight(local_now).replace(day=1)


def _prev_month_start(local_now: datetime) -> datetime:
    first = _month_start(local_now)
    return (first - timedelta(days=1)).replace(day=1)


def _unit_delta(n: int, unit: str) -> timedelta:
    unit = unit.rstrip("s")
    if unit in ("hour", "saat"):
        return timedelta(hours=n)
    if unit in ("week", "hafta"):
        return timedelta(weeks=n)
    return timedelta(days=n)


def _weekday_start(local_now: datetime, weekday: int) -> datetime:
    days_back = (local_now.weekday() - weekday) % 7
    return _midnight(local_now) - timedelta(days=days_back)


def _date_local(year: int, month: int, day: int, tz: tzinfo) -> Optional[datetime]:
    try:
        return datetime(year, month, day, tzinfo=tz)
    except ValueError:
        return None


# Each rule: (regex on folded text, builder(match, local_now, tz) -> (start_local, end_local) | None, label, implicit)
Builder = Callable[[re.Match, datetime, tzinfo], Optional[tuple]]


def _today(m, now, tz):
    return _midnight(now), now


def _yesterday(m, now, tz):
    start = _midnight(now) - timedelta(days=1)
    return start, _midnight(now)


def _this_week(m, now, tz):
    return _monday(now), now


def _last_week(m, now, tz):
    return _monday(now) - timedelta(days=7), _monday(now)


def _this_month(m, now, tz):
    return _month_start(now), now


def _last_month(m, now, tz):
    return _prev_month_start(now), _month_start(now)


def _last_n(m, now, tz):
    n = int(m.group(1))
    if n <= 0 or n > 366:
        return None
    # Elapsed time: subtract in UTC, never on the local wall clock (DST).
    end = now.astimezone(timezone.utc)
    return end - _unit_delta(n, m.group(2)), end


def _since_day(names):
    def build(m, now, tz):
        return _weekday_start(now, names.index(m.group(1))), now
    return build


def _since_period(start_of):
    def build(m, now, tz):
        return start_of(now), now
    return build


def _since_yesterday(m, now, tz):
    return _midnight(now) - timedelta(days=1), now


def _since_iso(m, now, tz):
    start = _date_local(int(m.group(1)), int(m.group(2)), int(m.group(3)), tz)
    return (start, now) if start and start <= now else None


def _since_day_month(months, day_group, month_group):
    def build(m, now, tz):
        month = months.index(m.group(month_group)) + 1
        start = _date_local(now.year, month, int(m.group(day_group)), tz)
        if start and start > now:
            start = _date_local(now.year - 1, month, int(m.group(day_group)), tz)
        return (start, now) if start else None
    return build


def _implicit(m, now, tz):
    end = now.astimezone(timezone.utc)
    return end - timedelta(hours=24), end


_EN_DAY_RE = "|".join(_EN_DAYS)
_TR_DAY_RE = "|".join(_TR_DAYS)
_EN_MONTH_RE = "|".join(_EN_MONTHS)
_TR_MONTH_RE = "|".join(_TR_MONTHS)
_NO_YEAR = r"(?!\s*,?\s*\d{4}\b)"
# A day word that is part of a code identifier ("datetime.today()", "today.py") is not a time phrase.
_WORD_END = r"(?![\w(]|\.\w)"

_RULES: list[tuple[re.Pattern, Builder, str, bool]] = [
    # since … (checked first so "since yesterday" is not read as "yesterday")
    (re.compile(rf"\bsince\s+({_EN_DAY_RE})\b"), _since_day(_EN_DAYS), "since_weekday", False),
    (re.compile(rf"\b({_TR_DAY_RE}){_ABL}\s+beri\b"), _since_day(_TR_DAYS), "since_weekday", False),
    (re.compile(r"\bsince\s+yesterday\b"), _since_yesterday, "since_yesterday", False),
    (re.compile(r"\bdunden\s+beri\b"), _since_yesterday, "since_yesterday", False),
    (re.compile(r"\bsince\s+(\d{4})-(\d{2})-(\d{2})\b"), _since_iso, "since_date", False),
    (re.compile(rf"\b(\d{{4}})-(\d{{2}})-(\d{{2}}){_ABL}\s+beri\b"), _since_iso, "since_date", False),
    # a day and month without a year; a stated year is not guessed (no match)
    (re.compile(rf"\bsince\s+(\d{{1,2}})\s+({_EN_MONTH_RE})\b{_NO_YEAR}"), _since_day_month(_EN_MONTHS, 1, 2), "since_date", False),
    (re.compile(rf"\bsince\s+({_EN_MONTH_RE})\s+(\d{{1,2}})\b{_NO_YEAR}"), _since_day_month(_EN_MONTHS, 2, 1), "since_date", False),
    (re.compile(rf"\b(\d{{1,2}})\s+({_TR_MONTH_RE}){_ABL}\s+beri\b"), _since_day_month(_TR_MONTHS, 1, 2), "since_date", False),
    (re.compile(r"\bsince\s+(?:the\s+start\s+of\s+)?this\s+week\b"), _since_period(_monday), "since_period", False),
    (re.compile(r"\bsince\s+last\s+week\b(?!'?s\b)"), _since_period(lambda now: _monday(now) - timedelta(days=7)), "since_period", False),
    (re.compile(r"\bsince\s+(?:the\s+start\s+of\s+)?this\s+month\b"), _since_period(_month_start), "since_period", False),
    (re.compile(r"\bsince\s+last\s+month\b(?!'?s\b)"), _since_period(_prev_month_start), "since_period", False),
    # last / past N units
    (re.compile(rf"\b(?:in\s+the\s+)?(?:past|last)\s+(\d{{1,3}})\s+{_UNIT_EN}\b"), _last_n, "last_n", False),
    (re.compile(rf"\bson\s+(\d{{1,3}})\s+{_UNIT_TR}(?:te|ta|de|da|tir|dir|dur|tur)?(?:\s+icinde)?\b"), _last_n, "last_n", False),
    # named periods
    (re.compile(rf"(?<![\w.])today(?:'?s)?{_WORD_END}"), _today, "today", False),
    (re.compile(rf"(?<![\w.])bugun(?:ku|un)?{_WORD_END}"), _today, "today", False),
    (re.compile(rf"(?<![\w.])yesterday(?:'?s)?{_WORD_END}"), _yesterday, "yesterday", False),
    (re.compile(rf"(?<![\w.])dun(?:ku|un)?{_WORD_END}"), _yesterday, "yesterday", False),
    # "dünden kalan işler" (left over from yesterday); "dünden beri" matched above
    (re.compile(rf"(?<![\w.])dunden{_WORD_END}"), _yesterday, "yesterday", False),
    (re.compile(r"\bthis\s+week(?:'?s)?\b"), _this_week, "this_week", False),
    (re.compile(r"\bbu\s+hafta(?:ki|nin)?\b"), _this_week, "this_week", False),
    (re.compile(r"\blast\s+week(?:'?s)?\b"), _last_week, "last_week", False),
    (re.compile(r"\bgecen\s+hafta(?:ki|nin)?\b"), _last_week, "last_week", False),
    (re.compile(r"\bthis\s+month(?:'?s)?\b"), _this_month, "this_month", False),
    (re.compile(r"\bbu\s+ay(?:ki|in)?\b"), _this_month, "this_month", False),
    (re.compile(r"\blast\s+month(?:'?s)?\b"), _last_month, "last_month", False),
    (re.compile(r"\bgecen\s+ay(?:ki|in)?\b"), _last_month, "last_month", False),
    # implicit "what's new"
    (re.compile(r"\bwhat'?s\s+new\b"), _implicit, "recent", True),
    (re.compile(r"\bwhat\s+(?:has\s+)?changed\b"), _implicit, "recent", True),
    (re.compile(r"\brecent\s+(?:changes|updates)\b"), _implicit, "recent", True),
    (re.compile(r"\blatest\s+(?:changes|updates)\b"), _implicit, "recent", True),
    (re.compile(r"\byeni\s+ne\s+var\b"), _implicit, "recent", True),
    (re.compile(r"\bne\s+degisti\b"), _implicit, "recent", True),
    (re.compile(r"\bson\s+(?:degisiklik|guncelleme)\w*\b(?!\s+(?:tarih|zaman))"), _implicit, "recent", True),
    (re.compile(r"\bson\s+zamanlarda\b"), _implicit, "recent", True),
    (re.compile(r"\ben\s+son\s+ne\b"), _implicit, "recent", True),
]


# Cumulative "up to now" phrases ask for the current state of everything, not
# for what was written today, so they never route to a time window.
_GUARDS = re.compile(
    r"\bbugune\s+(?:kadar|dek)\b"
    r"|\bbugun\s+itibari(?:yla|yle)\b"
    r"|\b(?:as\s+of|until|till|up\s+to)\s+today\b"
    # A period that is negated or bounded from the other side ("before today",
    # "not today", "the day before yesterday") is not that period's window.
    r"|\b(?:before|until|till|after|not|prior\s+to|day\s+before)\s+(?:the\s+)?"
    r"(?:today|yesterday|(?:this|last)\s+(?:week|month|year)|bugun|dun)\b"
    r"|\b(?:bugun|dun)\s+degil\b"
    # "since last week's release" counts from an event, not from the period
    r"|\bsince\s+(?:this|last)\s+(?:week|month)'?s\b"
)
# "to date" and "so far" are cumulative too, unless the query names a period
# ("today so far", "this week to date"): they only veto an implicit match.
_IMPLICIT_GUARDS = re.compile(r"\bto\s+date\b|\bso\s+far\b")


def _residual(folded: str, spans: list[tuple[int, int]]) -> str:
    kept = []
    last = 0
    for start, end in sorted(spans):
        kept.append(folded[last:max(last, start)])
        last = max(last, end)
    kept.append(folded[last:])
    tokens = re.findall(r"[a-z0-9][a-z0-9'_.-]*", " ".join(kept))
    return " ".join(t.strip("'") for t in tokens if t.strip("'") not in _FILLERS)


def parse_time_intent(query: str, *, now: datetime, tz: tzinfo) -> Optional[TimeIntent]:
    folded = _fold(query)
    if not folded.strip() or _GUARDS.search(folded):
        return None
    local_now = now.astimezone(tz)
    explicit: Optional[tuple] = None
    implicit: Optional[tuple] = None
    spans: list[tuple[int, int]] = []
    for pattern, build, label, is_implicit in _RULES:
        match = pattern.search(folded)
        if not match:
            continue
        window = build(match, local_now, tz)
        if window is None:
            continue
        spans.append(match.span())
        if is_implicit:
            implicit = implicit or (window, label)
        elif explicit is None:
            explicit = (window, label)
    if explicit is None and _IMPLICIT_GUARDS.search(folded):
        return None
    chosen = explicit or implicit
    if chosen is None:
        return None
    (start_local, end_local), label = chosen
    return TimeIntent(
        start=start_local.astimezone(timezone.utc),
        end=end_local.astimezone(timezone.utc),
        label=label,
        residual_query=_residual(folded, spans),
        implicit=explicit is None,
    )
