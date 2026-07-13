"""Content-date extraction: date-line, ISO, and month-name formats."""

from datetime import date

from app.services.content_dates import extract_date


def test_date_line():
    assert extract_date("Date: 2026-01-15\nToday we discussed ...") == date(2026, 1, 15)


def test_iso_near_top():
    assert extract_date("2026-07-03 — a quiet morning, wrote for an hour.") == date(2026, 7, 3)


def test_month_name_dmy():
    assert extract_date("July 3, 2026\nDear diary,") == date(2026, 7, 3)
    assert extract_date("Entry for 3 July 2026: rain again.") == date(2026, 7, 3)


def test_no_date_returns_none():
    assert extract_date("The Time Traveller (for so it will be convenient to speak of him)") is None
    # a bare number must not be mistaken for a date
    assert extract_date("We processed 40000 events per second at peak.") is None
