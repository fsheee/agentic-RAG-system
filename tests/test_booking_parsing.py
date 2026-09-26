"""Date and time parsing for the booking workflow.

Natural phrasing is the point of this tool, so the formats a person would
actually type are pinned here — a date the parser misses silently becomes
"On which date and time?" instead of an error, which is easy to ship by
accident.
"""

from datetime import date, timedelta

import pytest

from app.agent.tools.booking_tool import _parse_date, _parse_time


# --- Dates ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "28th Sept 2026",
        "28 September 2026",
        "28 sept",
        "28th Sept",
        "September 28, 2026",
        "Sept 28 2026",
        "Book my appointment with Dr. Sarah at 10am on 28th Sept 2026",
    ],
)
def test_month_name_dates_parse(text):
    assert _parse_date(text) == date(2026, 9, 28)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("2026-09-28", date(2026, 9, 28)),
        ("28/09/2026", date(2026, 9, 28)),
        ("Dec 1 2026", date(2026, 12, 1)),
        ("1 January 2027", date(2027, 1, 1)),
    ],
)
def test_existing_date_formats_still_parse(text, expected):
    assert _parse_date(text) == expected


def test_relative_dates_still_parse():
    assert _parse_date("today") == date.today()
    assert _parse_date("tomorrow") == date.today() + timedelta(days=1)


def test_weekday_still_parses():
    result = _parse_date("friday")

    assert result is not None
    assert result.weekday() == 4
    assert result > date.today()


def test_year_is_optional():
    assert _parse_date("28 Sept") == date(date.today().year, 9, 28)


def test_impossible_date_is_not_guessed():
    """A real-looking but invalid date must not silently become another
    day — better to ask again than to book the wrong one."""
    assert _parse_date("31 February 2026") is None


def test_no_date_returns_none():
    assert _parse_date("Book an appointment") is None


# --- Times ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("at 10am", "10:00:00"),
        ("10:30", "10:30:00"),
        ("tomorrow at 2pm", "14:00:00"),
        ("at 10", "10:00:00"),
        ("12pm", "12:00:00"),
        ("12am", "00:00:00"),
    ],
)
def test_times_parse(text, expected):
    assert str(_parse_time(text)) == expected


def test_time_absent_returns_none():
    assert _parse_time("with Dr. Sarah") is None
