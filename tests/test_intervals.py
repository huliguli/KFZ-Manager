"""Intervall-Engine: 'alle X km und/oder Y Monate — was zuerst eintritt' plus
the calendar forecaster with all edge cases."""

from datetime import date, timedelta

from modules import intervals
from modules.fuel import OdoReading
from modules.models import CareRule

TODAY = date(2026, 7, 14)


def _rule(**kwargs) -> CareRule:
    defaults = dict(vehicle_id=1, name="Ölwechsel")
    defaults.update(kwargs)
    return CareRule(**defaults)


def _history(km_per_day: float = 30.0, current: int = 50_000) -> list[OdoReading]:
    """Synthetic history ending today with a clean daily rate."""
    return [
        OdoReading(TODAY - timedelta(days=90), current - round(90 * km_per_day)),
        OdoReading(TODAY - timedelta(days=45), current - round(45 * km_per_day)),
        OdoReading(TODAY, current),
    ]


# --- combined rule: whichever comes first --------------------------------------
def test_km_projection_beats_later_time_due():
    # 15k km interval, 3k km left at 30 km/day -> ~100 days; time due in 10 months.
    rule = _rule(intervall_km=15_000, intervall_monate=10,
                 letzte_datum="2026-05-14", letzte_km=38_000)
    status = intervals.evaluate_rule(rule, _history(), today=TODAY)
    assert status.km_remaining == 3_000
    assert status.km_projected_date == TODAY + timedelta(days=100)
    assert status.due_date == status.km_projected_date
    assert status.due_date_source == "km-prognose"


def test_time_due_beats_far_km():
    rule = _rule(intervall_km=15_000, intervall_monate=1,
                 letzte_datum="2026-07-01", letzte_km=49_500)
    status = intervals.evaluate_rule(rule, _history(), today=TODAY)
    assert status.time_due_date == date(2026, 8, 1)
    assert status.due_date == date(2026, 8, 1)
    assert status.due_date_source == "zeit"


# --- overdue / soon / ok ----------------------------------------------------------
def test_overdue_by_km():
    rule = _rule(intervall_km=10_000, letzte_datum="2026-01-01", letzte_km=39_000)
    status = intervals.evaluate_rule(rule, _history(), today=TODAY)
    assert status.km_remaining == -1_000
    assert status.status == intervals.STATUS_OVERDUE
    assert status.km_projected_date == TODAY  # already reached


def test_overdue_by_time():
    rule = _rule(intervall_monate=12, letzte_datum="2025-06-01")
    status = intervals.evaluate_rule(rule, _history(), today=TODAY)
    assert status.status == intervals.STATUS_OVERDUE


def test_soon_within_lead():
    rule = _rule(intervall_km=10_000, letzte_datum="2026-06-01", letzte_km=40_500)
    status = intervals.evaluate_rule(rule, _history(), today=TODAY)
    assert status.km_remaining == 500
    assert status.status == intervals.STATUS_SOON


def test_ok_far_away():
    rule = _rule(intervall_km=15_000, intervall_monate=24,
                 letzte_datum="2026-07-01", letzte_km=48_000)
    status = intervals.evaluate_rule(rule, _history(), today=TODAY)
    assert status.status == intervals.STATUS_OK


# --- edge cases -------------------------------------------------------------------
def test_new_vehicle_without_history_time_only():
    rule = _rule(intervall_km=15_000, intervall_monate=12,
                 letzte_datum="2026-07-01", letzte_km=100)
    status = intervals.evaluate_rule(rule, [], today=TODAY)
    assert status.km_remaining is None          # no current km known
    assert status.km_projected_date is None
    assert status.time_due_date == date(2027, 7, 1)
    assert status.due_date_source == "zeit"
    assert "km-Stände" in status.hint or "km-St" in status.hint


def test_never_completed_anchors_today():
    rule = _rule(intervall_monate=6)
    status = intervals.evaluate_rule(rule, _history(), today=TODAY)
    assert status.time_due_date == date(2027, 1, 14)
    assert status.status == intervals.STATUS_OK
    assert "Noch nie durchgeführt" in status.hint


def test_km_rule_without_anchor_km():
    rule = _rule(intervall_km=10_000)
    status = intervals.evaluate_rule(rule, _history(), today=TODAY)
    assert status.km_remaining is None
    assert status.status == intervals.STATUS_UNKNOWN


def test_no_projection_without_daily_rate():
    # Only one reading -> no rate -> km part shows remaining km without a date.
    history = [OdoReading(TODAY, 50_000)]
    rule = _rule(intervall_km=10_000, letzte_datum="2026-01-01", letzte_km=45_000)
    status = intervals.evaluate_rule(rule, history, today=TODAY)
    assert status.km_remaining == 5_000
    assert status.km_projected_date is None
    assert status.due_date is None
    assert status.status == intervals.STATUS_OK


def test_km_correction_does_not_crash_projection():
    # A downward-corrected history (max wins) still yields a sane result.
    history = [OdoReading(TODAY - timedelta(days=30), 50_000),
               OdoReading(TODAY, 50_100)]
    rule = _rule(intervall_km=1_000, letzte_datum="2026-06-01", letzte_km=49_800)
    status = intervals.evaluate_rule(rule, history, today=TODAY)
    assert status.km_remaining == 700


def test_evaluate_all_sorts_overdue_first():
    rules = [
        _rule(name="ok", intervall_monate=24, letzte_datum="2026-07-01"),
        _rule(name="überfällig", intervall_monate=1, letzte_datum="2026-01-01"),
        _rule(name="bald", intervall_monate=1, letzte_datum="2026-06-20"),
    ]
    statuses = intervals.evaluate_all(rules, _history(), today=TODAY)
    assert [s.rule.name for s in statuses] == ["überfällig", "bald", "ok"]


def test_status_text_mentions_projection():
    rule = _rule(intervall_km=15_000, letzte_datum="2026-05-14", letzte_km=38_000)
    status = intervals.evaluate_rule(rule, _history(), today=TODAY)
    text = intervals.status_text(status)
    assert "fällig in ca. 3.000 km" in text
    assert "voraussichtlich" in text
