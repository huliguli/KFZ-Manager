"""Tank-/Ladebuch maths and the vehicle's odometer history.

Consumption follows the standard full-to-full method: a full refuel consumes
everything filled since the PREVIOUS full refuel (partial fills in between are
summed onto the segment). Charge entries are simpler — kWh between consecutive
readings — because "full" is fuzzy for batteries and the spec explicitly keeps
the Ladebuch lean.

The odometer history assembled here (tank entries + the profile's manual km
reading) is the data basis for every due-date forecast: ``average_km_per_day``
derives the vehicle's recent daily mileage with a ~90-day sliding window, so
irregular use (holiday, seasonal cars) converges to the current pattern
instead of a lifetime average.

All quantities are integers (ml / Wh / cents); floats appear only in derived
display values (l/100 km, €/km).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from modules import dates
from modules.models import TankEntry, Vehicle

# Sliding window for the daily-mileage average. ~90 days matches "the last
# season" — long enough to smooth weekly noise, short enough to track a
# changed commute.
AVG_WINDOW_DAYS = 90

# Below this time span a km/day figure would be dominated by noise (two
# readings on neighbouring days), so we refuse to extrapolate from it.
MIN_SPAN_DAYS = 7


@dataclass(frozen=True)
class OdoReading:
    """One odometer observation (date + km)."""
    date: date
    km: int


@dataclass(frozen=True)
class ConsumptionStats:
    """Aggregated Tankbuch figures for the stats header."""
    fuel_l_per_100km: float | None      # Ø over all full-to-full segments
    energy_kwh_per_100km: float | None  # Ø over consecutive charge entries
    cost_per_km_cent: float | None      # total spend / km driven (tank entries)
    total_cost_cents: int
    total_km: int


def km_history(vehicle: Vehicle, entries: list[TankEntry],
               extra: list[OdoReading] | None = None) -> list[OdoReading]:
    """All known odometer readings, chronologically sorted.

    Sources: tank/charge entries, the vehicle profile's manual km reading and
    optional extra readings (e.g. logbook entries with km). Duplicate
    same-date readings keep the highest km (the later observation of the day).
    """
    readings: dict[date, int] = {}

    def _add(d: date | None, km: int | None) -> None:
        if d is None or km is None:
            return
        readings[d] = max(km, readings.get(d, 0))

    for entry in entries:
        _add(dates.parse_date(entry.date), entry.odo_km)
    if vehicle.km_stand is not None:
        # A profile reading without a date is anchored "today" at entry time;
        # fall back to today so it still participates in the history.
        _add(dates.parse_date(vehicle.km_stand_datum) or dates.today(), vehicle.km_stand)
    for reading in extra or []:
        _add(reading.date, reading.km)

    return [OdoReading(d, km) for d, km in sorted(readings.items())]


def current_km(history: list[OdoReading]) -> int | None:
    """Best-known current odometer value (highest reading ever seen)."""
    if not history:
        return None
    return max(r.km for r in history)


def validate_odo(history: list[OdoReading], entry_date: date, odo_km: int,
                 ignore_date: date | None = None) -> str | None:
    """Check that a new reading keeps the history monotonically increasing.

    Returns a German error message, or None when the reading fits. A reading
    must not be lower than any earlier reading nor higher than any later one.
    ``ignore_date`` excludes the reading being edited (a correction may
    replace the value recorded for that same day).
    """
    for reading in history:
        if ignore_date is not None and reading.date == ignore_date:
            continue
        # Same-day readings are exempt: several fills on one day may carry
        # increasing km in any entry order.
        if reading.date < entry_date and reading.km > odo_km:
            return (f"Der km-Stand ({odo_km:,} km) liegt unter dem früheren Stand "
                    f"vom {dates.format_date(reading.date)} ({reading.km:,} km)."
                    ).replace(",", ".")
        if reading.date > entry_date and reading.km < odo_km:
            return (f"Der km-Stand ({odo_km:,} km) liegt über dem späteren Stand "
                    f"vom {dates.format_date(reading.date)} ({reading.km:,} km)."
                    ).replace(",", ".")
    return None


def average_km_per_day(history: list[OdoReading],
                       window_days: int = AVG_WINDOW_DAYS,
                       today: date | None = None) -> float | None:
    """Recent daily mileage from a sliding window over the km history.

    Uses the readings inside the last ``window_days`` (measured back from the
    newest reading, capped at today); falls back to the whole history when the
    window holds fewer than two readings. Returns None when no reliable figure
    exists (fewer than two readings, span shorter than MIN_SPAN_DAYS, or no
    forward movement) — callers must then show the time-based rule only.
    """
    if len(history) < 2:
        return None
    newest = history[-1]
    anchor = min(newest.date, today or dates.today())
    window_start = anchor - timedelta(days=window_days)
    windowed = [r for r in history if r.date >= window_start]
    if len(windowed) < 2:
        windowed = history
    first, last = windowed[0], windowed[-1]
    span = (last.date - first.date).days
    km = last.km - first.km
    if span < MIN_SPAN_DAYS or km <= 0:
        # Fall back to the full history before giving up (e.g. two clusters of
        # readings straddling the window edge).
        first, last = history[0], history[-1]
        span = (last.date - first.date).days
        km = last.km - first.km
        if span < MIN_SPAN_DAYS or km <= 0:
            return None
    return km / span


# --- consumption -------------------------------------------------------------
def fuel_segments(entries: list[TankEntry]) -> list[tuple[TankEntry, int, int]]:
    """Full-to-full consumption segments from chronological fuel entries.

    Returns ``(full_entry, km_driven, ml_consumed)`` per segment: everything
    filled after the previous FULL refuel up to and including this full refuel
    was consumed over the km between the two fulls. Segments with missing or
    non-positive km are skipped (odometer corrections must not produce
    negative consumption).
    """
    fuel = [e for e in entries if e.art == "kraftstoff" and (e.menge_ml or 0) > 0]
    segments: list[tuple[TankEntry, int, int]] = []
    last_full: TankEntry | None = None
    pending_ml = 0
    for entry in fuel:
        if last_full is None:
            # Everything before the first full refuel has an unknown start level.
            if entry.voll:
                last_full = entry
                pending_ml = 0
            continue
        pending_ml += entry.menge_ml or 0
        if entry.voll:
            km = entry.odo_km - last_full.odo_km
            if km > 0:
                segments.append((entry, km, pending_ml))
            last_full = entry
            pending_ml = 0
    return segments


def consumption_l_per_100km(entries: list[TankEntry]) -> float | None:
    """Average l/100 km over all full-to-full segments (None without data)."""
    segments = fuel_segments(entries)
    total_km = sum(km for _e, km, _ml in segments)
    total_ml = sum(ml for _e, _km, ml in segments)
    if total_km <= 0 or total_ml <= 0:
        return None
    return (total_ml / 1000.0) / total_km * 100.0


def segment_consumption(entries: list[TankEntry]) -> dict[int, float]:
    """Per-entry consumption for the table: entry id -> l/100 km of its segment."""
    return {e.id: (ml / 1000.0) / km * 100.0
            for e, km, ml in fuel_segments(entries) if e.id is not None}


def charge_kwh_per_100km(entries: list[TankEntry]) -> float | None:
    """Average kWh/100 km over consecutive charge entries.

    Charge entry N is attributed to the km driven since charge entry N-1 —
    lean by design (no charge-curve maths, per spec).
    """
    charges = [e for e in entries if e.art == "strom" and (e.energie_wh or 0) > 0]
    total_km = 0
    total_wh = 0
    for prev, cur in zip(charges, charges[1:]):
        km = cur.odo_km - prev.odo_km
        if km > 0:
            total_km += km
            total_wh += cur.energie_wh or 0
    if total_km <= 0 or total_wh <= 0:
        return None
    return (total_wh / 1000.0) / total_km * 100.0


def stats(entries_chronological: list[TankEntry]) -> ConsumptionStats:
    """Aggregate Tankbuch statistics for the header cards."""
    entries = entries_chronological
    total_cost = sum(e.betrag_cent for e in entries)
    km = 0
    if len(entries) >= 2:
        km = max(0, entries[-1].odo_km - entries[0].odo_km)
    cost_per_km = (total_cost / km) if km > 0 else None
    return ConsumptionStats(
        fuel_l_per_100km=consumption_l_per_100km(entries),
        energy_kwh_per_100km=charge_kwh_per_100km(entries),
        cost_per_km_cent=cost_per_km,
        total_cost_cents=total_cost,
        total_km=km,
    )


# --- German number helpers (display only) --------------------------------------
def format_km(km: int | None) -> str:
    if km is None:
        return "—"
    return f"{km:,} km".replace(",", ".")


def format_liters(ml: int | None) -> str:
    if not ml:
        return "—"
    return f"{ml / 1000:.2f} l".replace(".", ",")


def format_kwh(wh: int | None) -> str:
    if not wh:
        return "—"
    return f"{wh / 1000:.2f} kWh".replace(".", ",")


def format_consumption(value: float | None, unit: str) -> str:
    if value is None:
        return "—"
    return f"{value:.1f} {unit}".replace(".", ",")


def parse_decimal(text: str) -> float | None:
    """Parse a German/plain decimal ('42,5' or '42.5'). None when invalid."""
    s = (text or "").strip().replace(" ", "")
    if not s:
        return None
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None
