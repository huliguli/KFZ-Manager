"""Tankbuch maths: km history, monotonic validation, daily-mileage average,
full-to-full consumption and charge statistics."""

from datetime import date

from modules import fuel
from modules.models import TankEntry, Vehicle


def _entry(day: str, odo: int, ml: int | None = None, voll: bool = True,
           art: str = "kraftstoff", wh: int | None = None,
           cents: int = 0) -> TankEntry:
    return TankEntry(vehicle_id=1, date=day, odo_km=odo, art=art,
                     menge_ml=ml, energie_wh=wh, betrag_cent=cents, voll=voll)


def _vehicle(**kwargs) -> Vehicle:
    return Vehicle(name="Test", **kwargs)


# --- km history ------------------------------------------------------------
def test_km_history_merges_sources_and_sorts():
    v = _vehicle(km_stand=50_000, km_stand_datum="2026-03-01")
    entries = [_entry("2026-01-10", 48_000, 40_000), _entry("2026-02-10", 49_000, 40_000)]
    extra = [fuel.OdoReading(date(2026, 4, 1), 51_000)]
    history = fuel.km_history(v, entries, extra)
    assert [r.km for r in history] == [48_000, 49_000, 50_000, 51_000]
    assert fuel.current_km(history) == 51_000


def test_km_history_same_day_keeps_highest():
    v = _vehicle()
    entries = [_entry("2026-01-10", 1000, 10_000), _entry("2026-01-10", 1100, 10_000)]
    history = fuel.km_history(v, entries)
    assert len(history) == 1 and history[0].km == 1100


def test_validate_odo_monotonic():
    history = [fuel.OdoReading(date(2026, 1, 1), 10_000),
               fuel.OdoReading(date(2026, 2, 1), 11_000)]
    # Lower than an earlier reading -> error.
    assert fuel.validate_odo(history, date(2026, 2, 15), 10_500) is not None
    # Higher than a later reading -> error.
    assert fuel.validate_odo(history, date(2026, 1, 15), 12_000) is not None
    # Fits between -> ok.
    assert fuel.validate_odo(history, date(2026, 1, 15), 10_500) is None
    # Same-day readings are exempt (multiple fills per day).
    assert fuel.validate_odo(history, date(2026, 2, 1), 10_900) is None
    # Corrections: ignore the reading of the edited day.
    assert fuel.validate_odo(history, date(2026, 2, 1), 10_500,
                             ignore_date=date(2026, 2, 1)) is None


# --- daily mileage -----------------------------------------------------------
def test_average_uses_sliding_window():
    # Old phase: 10 km/day; recent 90 days: 50 km/day. The window must see ~50.
    history = [
        fuel.OdoReading(date(2025, 1, 1), 0),
        fuel.OdoReading(date(2025, 12, 1), 3340),   # ~10 km/Tag davor
        fuel.OdoReading(date(2026, 1, 1), 4890),
        fuel.OdoReading(date(2026, 3, 1), 7840),    # 50 km/Tag zuletzt
    ]
    rate = fuel.average_km_per_day(history, today=date(2026, 3, 1))
    assert rate is not None and 45 <= rate <= 55


def test_average_needs_minimum_span():
    history = [fuel.OdoReading(date(2026, 3, 1), 1000),
               fuel.OdoReading(date(2026, 3, 3), 1100)]  # nur 2 Tage
    assert fuel.average_km_per_day(history, today=date(2026, 3, 3)) is None


def test_average_none_without_data():
    assert fuel.average_km_per_day([], today=date(2026, 1, 1)) is None
    assert fuel.average_km_per_day([fuel.OdoReading(date(2026, 1, 1), 5)]) is None


def test_average_ignores_stagnation():
    history = [fuel.OdoReading(date(2026, 1, 1), 1000),
               fuel.OdoReading(date(2026, 3, 1), 1000)]  # kein Fortschritt
    assert fuel.average_km_per_day(history, today=date(2026, 3, 1)) is None


# --- consumption ---------------------------------------------------------------
def test_full_to_full_consumption_with_partial_fill():
    entries = [
        _entry("2026-01-01", 10_000, 40_000, voll=True),   # baseline full
        _entry("2026-01-10", 10_400, 20_000, voll=False),  # partial
        _entry("2026-01-20", 10_800, 25_000, voll=True),   # closes the segment
    ]
    # Segment: 800 km, 45 l -> 5.625 l/100km... nein: 45_000 ml / 800 km
    value = fuel.consumption_l_per_100km(entries)
    assert value is not None
    assert abs(value - (45.0 / 800 * 100)) < 0.001


def test_consumption_ignores_leading_partials_and_zero_km():
    entries = [
        _entry("2026-01-01", 10_000, 30_000, voll=False),  # unknown start level
        _entry("2026-01-05", 10_300, 20_000, voll=True),   # baseline
        _entry("2026-01-05", 10_300, 5_000, voll=True),    # same odo -> skipped
    ]
    assert fuel.consumption_l_per_100km(entries) is None


def test_charge_kwh_per_100km():
    entries = [
        _entry("2026-01-01", 20_000, art="strom", wh=30_000),
        _entry("2026-01-08", 20_300, art="strom", wh=45_000),
        _entry("2026-01-15", 20_600, art="strom", wh=60_000),
    ]
    value = fuel.charge_kwh_per_100km(entries)
    # 600 km, 105 kWh geladen (Eintrag 2+3) -> 17.5 kWh/100km
    assert value is not None and abs(value - 17.5) < 0.001


def test_stats_cost_per_km():
    entries = [
        _entry("2026-01-01", 10_000, 40_000, cents=6000),
        _entry("2026-02-01", 11_000, 40_000, cents=6000),
    ]
    stats = fuel.stats(entries)
    assert stats.total_km == 1000
    assert stats.total_cost_cents == 12000
    assert abs(stats.cost_per_km_cent - 12.0) < 0.001


def test_parse_decimal_german_and_plain():
    assert fuel.parse_decimal("42,5") == 42.5
    assert fuel.parse_decimal("42.5") == 42.5
    assert fuel.parse_decimal("") is None
    assert fuel.parse_decimal("abc") is None
