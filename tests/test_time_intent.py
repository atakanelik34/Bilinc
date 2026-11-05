from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from bilinc.core.time_intent import (
    TimeIntent,
    mentions_low_signal,
    parse_time_intent,
    resolve_timezone,
)

IST = ZoneInfo("Europe/Istanbul")
BERLIN = ZoneInfo("Europe/Berlin")
# Thursday 2026-11-05 15:00 Istanbul (12:00 UTC)
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


def local(y, m, d, h=0, mi=0, tz=IST):
    return datetime(y, m, d, h, mi, tzinfo=tz).astimezone(timezone.utc)


def window(query, tz=IST, now=NOW):
    intent = parse_time_intent(query, now=now, tz=tz)
    assert intent is not None, query
    return intent


@pytest.mark.parametrize(
    "query",
    [
        "what changed today", "today's updates", "Today", "WHAT CHANGED TODAY", "today’s updates",
        "bugünün güncellemeleri", "bugün ne yaptık", "bugünkü kararlar", "bugun ne degisti",
        "BUGÜN",
    ],
)
def test_today(query):
    intent = window(query)
    assert intent.start == local(2026, 11, 5)
    assert intent.end == NOW
    assert intent.implicit is False


@pytest.mark.parametrize("query", ["yesterday's decisions", "what did we do yesterday", "dün", "dünkü kararlar", "dünün özeti", "dun ne oldu"])
def test_yesterday(query):
    intent = window(query)
    assert intent.start == local(2026, 11, 4)
    assert intent.end == local(2026, 11, 5)


@pytest.mark.parametrize("query", ["this week", "bu hafta neler oldu", "bu haftaki işler", "bu haftanın özeti"])
def test_this_week(query):
    intent = window(query)
    assert intent.start == local(2026, 11, 2)  # Monday
    assert intent.end == NOW


@pytest.mark.parametrize("query", ["last week", "geçen hafta", "geçen haftaki kararlar", "gecen haftanin ozeti"])
def test_last_week(query):
    intent = window(query)
    assert intent.start == local(2026, 10, 26)
    assert intent.end == local(2026, 11, 2)


@pytest.mark.parametrize("query", ["this month", "bu ay", "bu ayki işler"])
def test_this_month(query):
    assert window(query).start == local(2026, 11, 1)


@pytest.mark.parametrize("query", ["last month", "geçen ay", "geçen ayın kararları"])
def test_last_month(query):
    intent = window(query)
    assert intent.start == local(2026, 10, 1)
    assert intent.end == local(2026, 11, 1)


@pytest.mark.parametrize(
    "query,delta",
    [
        ("last 3 days", timedelta(days=3)), ("past 24 hours", timedelta(hours=24)),
        ("in the last 2 weeks", timedelta(weeks=2)), ("son 3 gün", timedelta(days=3)),
        ("son 3 günde F6S", timedelta(days=3)), ("son 24 saatte", timedelta(hours=24)),
        ("son 2 haftada", timedelta(weeks=2)), ("son 3 gün içinde", timedelta(days=3)),
    ],
)
def test_last_n(query, delta):
    intent = window(query)
    assert intent.start == NOW - delta
    assert intent.end == NOW


@pytest.mark.parametrize(
    "query",
    ["since Monday", "pazartesiden beri", "pazartesiden beri ne değişti", "PAZARTESİDEN BERİ"],
)
def test_since_monday(query):
    assert window(query).start == local(2026, 11, 2)


@pytest.mark.parametrize("query", ["since Tuesday", "salıdan beri", "SALIDAN BERI"])
def test_since_tuesday(query):
    assert window(query).start == local(2026, 11, 3)


def test_since_today_weekday_means_today():
    assert window("since Thursday").start == local(2026, 11, 5)
    assert window("perşembeden beri").start == local(2026, 11, 5)


@pytest.mark.parametrize("query", ["since yesterday", "dünden beri"])
def test_since_yesterday(query):
    assert window(query).start == local(2026, 11, 4)


@pytest.mark.parametrize(
    "query",
    [
        "since 2026-11-01", "2026-11-01'den beri", "since 1 November", "since November 1",
        "1 kasımdan beri", "1 Kasım'dan beri", "1 Kasım’dan beri",
    ],
)
def test_since_date(query):
    assert window(query).start == local(2026, 11, 1)


@pytest.mark.parametrize(
    "query",
    [
        "what's new", "whats new", "what`s new", "what changed", "recent changes", "latest updates",
        "yeni ne var", "ne değişti", "son değişiklikler", "son güncellemeler", "son zamanlarda",
        "en son ne yaptık",
    ],
)
def test_implicit(query):
    intent = window(query)
    assert intent.implicit is True
    assert intent.start == NOW - timedelta(hours=24)
    assert intent.end == NOW


@pytest.mark.parametrize(
    "query",
    [
        "dünya kupası", "dünyada yapay zeka", "gündem", "günlük rapor şablonu", "gün batımı",
        "bu gün ışığında", "since we started the company", "since the beginning", "last version of the deck",
        "last time we talked about pricing", "son karar neydi", "son sürüm", "pricing", "F6S profile",
        "weekly report template", "monthly budget", "Monday meeting notes", "pazartesi toplantısı",
        "a day in the life", "daytona deck", "dunyaca unlu",
        "what is the change log format", "changes to the API", "update the README", "new pricing",
        "the latest version of the library", "recently is an adverb", "since", "beri", "son", "last",
        "this", "bu", "geçen", "2026-11-01", "1 kasım",
        # cumulative "up to now" phrases ask for current state, not today's writes
        "bugüne kadar ne var", "bugüne kadar verilmiş kararlar", "bugüne dek yapılanlar",
        "bugün itibarıyla durum", "bugun itibariyla durum", "BUGÜNE KADAR",
        "as of today", "decisions as of today", "until today", "till today", "up to today",
        "everything up to today", "to date", "all decisions to date", "so far", "what changed so far",
        "", "   ",
    ],
)
def test_guards_do_not_trigger(query):
    assert parse_time_intent(query, now=NOW, tz=IST) is None, query


@pytest.mark.parametrize("query", ["what did we do today so far", "this week to date", "bugün şu ana kadar"])
def test_period_with_so_far_still_routes(query):
    assert parse_time_intent(query, now=NOW, tz=IST).implicit is False


@pytest.mark.parametrize("query", ["todays special", "yesterdays news site"])
def test_documented_trade_offs_do_trigger(query):
    # Possessive forms of today/yesterday are read as time questions on purpose.
    assert parse_time_intent(query, now=NOW, tz=IST) is not None


def test_residual_query_drops_time_phrase_and_fillers():
    assert window("son 3 günde F6S").residual_query == "f6s"
    assert window("what changed today in pricing").residual_query == "pricing"
    assert window("bugünün güncellemeleri").residual_query == ""
    assert window("dünkü kararlar").residual_query == "kararlar"
    assert window("dünden beri").residual_query == ""


def test_returns_timeintent_in_utc():
    intent = window("today")
    assert isinstance(intent, TimeIntent)
    assert intent.start.utcoffset() == timedelta(0)
    assert intent.end.utcoffset() == timedelta(0)
    assert intent.label == "today"


def test_utc_project_defaults():
    intent = parse_time_intent("today", now=NOW, tz=resolve_timezone(None))
    assert intent.start == datetime(2026, 11, 5, tzinfo=timezone.utc)


def test_resolve_timezone():
    assert resolve_timezone("Europe/Istanbul") == IST
    assert resolve_timezone("Mars/Olympus") == timezone.utc
    assert resolve_timezone("") == timezone.utc
    assert resolve_timezone("../etc") == timezone.utc


def test_midnight_boundary():
    just_after = datetime(2026, 11, 4, 21, 1, tzinfo=timezone.utc)  # 00:01 Istanbul on Nov 5
    assert parse_time_intent("today", now=just_after, tz=IST).start == local(2026, 11, 5)
    just_before = datetime(2026, 11, 4, 20, 59, tzinfo=timezone.utc)  # 23:59 Istanbul on Nov 4
    assert parse_time_intent("today", now=just_before, tz=IST).start == local(2026, 11, 4)


def test_dst_fall_back_calendar_and_elapsed_windows():
    # Europe/Berlin leaves DST on 2026-10-25 (01:00 UTC): that local day is 25 hours long.
    now = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
    today = parse_time_intent("today", now=now, tz=BERLIN)
    assert today.start == datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc)
    assert today.end == now
    yesterday = parse_time_intent("yesterday", now=now, tz=BERLIN)
    assert yesterday.start == datetime(2026, 10, 23, 22, 0, tzinfo=timezone.utc)
    assert yesterday.end == datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc)
    since_yesterday = parse_time_intent("since yesterday", now=now, tz=BERLIN)
    assert since_yesterday.start == yesterday.start
    # Elapsed windows are exact elapsed time, not wall-clock arithmetic across the change.
    assert parse_time_intent("last 24 hours", now=now, tz=BERLIN).start == now - timedelta(hours=24)
    assert parse_time_intent("last 2 days", now=now, tz=BERLIN).start == now - timedelta(days=2)
    assert parse_time_intent("what's new", now=now, tz=BERLIN).start == now - timedelta(hours=24)


def test_dst_spring_forward_elapsed_window_is_exact():
    # Europe/Berlin enters DST on 2026-03-29 (01:00 UTC).
    now = datetime(2026, 3, 29, 12, 0, tzinfo=timezone.utc)
    assert parse_time_intent("past 24 hours", now=now, tz=BERLIN).start == now - timedelta(hours=24)
    assert parse_time_intent("today", now=now, tz=BERLIN).start == datetime(2026, 3, 28, 23, 0, tzinfo=timezone.utc)


def test_future_date_since_is_rejected_or_rolled_back():
    # A "since <day month>" later than now means last year; an impossible date is no match.
    assert window("since 25 December").start == local(2025, 12, 25)
    assert parse_time_intent("since 31 February", now=NOW, tz=IST) is None
    assert parse_time_intent("since 2026-12-01", now=NOW, tz=IST) is None


def test_last_n_bounds():
    assert parse_time_intent("last 0 days", now=NOW, tz=IST) is None
    assert parse_time_intent("last 999 days", now=NOW, tz=IST) is None


def test_mentions_low_signal():
    assert mentions_low_signal("bugünkü sohbetler")
    assert mentions_low_signal("today's chat transcripts")
    assert mentions_low_signal("konuşma kayıtları")
    assert not mentions_low_signal("bugünkü kararlar")


@pytest.mark.parametrize(
    "query",
    [
        "decisions before today", "before yesterday", "until yesterday", "not today",
        "the day before yesterday deploy", "prior to today", "after yesterday's call",
        "since 12 march 2025", "since march 5, 2025", "since 2 may 2025",
        "datetime.today() usage", "date.today", "today.py bug",
        "son güncelleme tarihi", "son değişiklik zamanı",
    ],
)
def test_review_false_positives_do_not_trigger(query):
    assert parse_time_intent(query, now=NOW, tz=IST) is None, query


def test_since_last_week_and_month_run_to_now():
    assert (window("since last week").start, window("since last week").end) == (local(2026, 10, 26), NOW)
    assert window("since this week").start == local(2026, 11, 2)
    assert (window("since last month").start, window("since last month").end) == (local(2026, 10, 1), NOW)
    assert window("since last week").residual_query == ""


def test_day_word_at_sentence_end_still_triggers():
    assert window("what changed today.").start == local(2026, 11, 5)


def test_since_weekday_on_that_weekday_means_today():
    monday = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)
    assert parse_time_intent("since Monday", now=monday, tz=IST).start == local(2026, 11, 2)


@pytest.mark.parametrize(
    "query,expected",
    [("since sunday's release", "release"), ("this month to date", ""), ("dün'den beri", "")],
)
def test_residual_drops_time_leftovers(query, expected):
    assert window(query).residual_query == expected


@pytest.mark.parametrize(
    "query,label",
    [
        ("what changed today after this deploy", "today"),
        ("what did we do yesterday before this migration", "yesterday"),
        ("what happened last week after the last release", "last_week"),
    ],
)
def test_ordinary_this_or_last_does_not_veto(query, label):
    assert window(query).label == label


@pytest.mark.parametrize("query", ["bugün değil", "dün değil, geçen hafta"])
def test_turkish_negation_vetoes(query):
    assert parse_time_intent(query, now=NOW, tz=IST) is None


def test_since_last_weeks_event_is_not_since_last_week():
    assert parse_time_intent("since last week's release", now=NOW, tz=IST) is None
    assert parse_time_intent("since last months launch", now=NOW, tz=IST) is None


# --- local_timezone ---------------------------------------------------------

def _tzname(tz):
    return getattr(tz, "key", None) or str(tz)


def test_local_timezone_prefers_bilinc_timezone(monkeypatch, tmp_path):
    from bilinc.core.time_intent import local_timezone

    monkeypatch.setenv("BILINC_TIMEZONE", "Europe/Berlin")
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    assert _tzname(local_timezone(localtime_path=tmp_path / "none")) == "Europe/Berlin"


def test_local_timezone_invalid_bilinc_timezone_falls_to_tz(monkeypatch, tmp_path):
    from bilinc.core.time_intent import local_timezone

    monkeypatch.setenv("BILINC_TIMEZONE", "Not/AZone")
    monkeypatch.setenv("TZ", ":Europe/Istanbul")
    assert _tzname(local_timezone(localtime_path=tmp_path / "none")) == "Europe/Istanbul"


def test_local_timezone_uses_localtime_symlink(monkeypatch, tmp_path):
    from bilinc.core.time_intent import local_timezone

    monkeypatch.delenv("BILINC_TIMEZONE", raising=False)
    monkeypatch.setenv("TZ", "garbage/zone")
    link = tmp_path / "localtime"
    link.symlink_to("/usr/share/zoneinfo/Asia/Tokyo")
    assert _tzname(local_timezone(localtime_path=link)) == "Asia/Tokyo"


@pytest.mark.parametrize("target", ["/usr/share/zoneinfo/posix/Asia/Tokyo", "/usr/share/zoneinfo/right/Asia/Tokyo",
                                    "../usr/share/zoneinfo/Asia/Tokyo"])
def test_local_timezone_symlink_variants(monkeypatch, tmp_path, target):
    from bilinc.core.time_intent import local_timezone

    monkeypatch.delenv("BILINC_TIMEZONE", raising=False)
    monkeypatch.delenv("TZ", raising=False)
    link = tmp_path / "localtime"
    link.symlink_to(target)
    assert _tzname(local_timezone(localtime_path=link)) == "Asia/Tokyo"


def test_local_timezone_invalid_symlink_target_is_utc(monkeypatch, tmp_path):
    from bilinc.core.time_intent import local_timezone

    monkeypatch.delenv("BILINC_TIMEZONE", raising=False)
    monkeypatch.delenv("TZ", raising=False)
    link = tmp_path / "localtime"
    link.symlink_to("/usr/share/zoneinfo/Not/AZone")
    assert local_timezone(localtime_path=link) is timezone.utc
    plain = tmp_path / "plain"
    plain.write_text("x")
    assert local_timezone(localtime_path=plain) is timezone.utc


def test_local_timezone_missing_localtime_is_utc(monkeypatch, tmp_path):
    from bilinc.core.time_intent import local_timezone

    monkeypatch.delenv("BILINC_TIMEZONE", raising=False)
    monkeypatch.delenv("TZ", raising=False)
    assert local_timezone(localtime_path=tmp_path / "missing") is timezone.utc


def test_standalone_dunden_is_yesterday():
    intent = window("dünden kalan işler")
    assert (intent.start, intent.end) == (local(2026, 11, 4), local(2026, 11, 5))
    assert window("dünden beri").label == "since_yesterday"
