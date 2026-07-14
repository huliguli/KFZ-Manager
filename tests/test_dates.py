"""German date parsing and month arithmetic."""

from datetime import date

from modules import dates


def test_parse_variants():
    assert dates.parse_date("14.07.2026") == date(2026, 7, 14)
    assert dates.parse_date("2026-07-14") == date(2026, 7, 14)
    assert dates.parse_date("03.2032") == date(2032, 3, 31)  # month/year -> last day
    assert dates.parse_date("") is None
    assert dates.parse_date("quatsch") is None


def test_add_months_clamps_day():
    assert dates.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert dates.add_months(date(2026, 12, 15), 1) == date(2027, 1, 15)
    assert dates.add_months(date(2026, 3, 31), -1) == date(2026, 2, 28)


def test_months_between_partial_months():
    assert dates.months_between(date(2026, 1, 15), date(2026, 3, 15)) == 2
    assert dates.months_between(date(2026, 1, 15), date(2026, 3, 14)) == 1


def test_shift_month_wraps():
    assert dates.shift_month(2026, 12, 1) == (2027, 1)
    assert dates.shift_month(2025, 1, -1) == (2024, 12)
