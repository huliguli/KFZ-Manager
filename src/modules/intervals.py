"""Pflegeplaner — the interval engine and the calendar forecaster.

A care rule reads "alle X km UND/ODER alle Y Monate — was zuerst eintritt",
measured from the last completion (date + odometer back then). This module
turns such a rule plus the vehicle's km history into one concrete status:

    * how many km remain until the km part is due (and whether it is overdue),
    * when the time part is due,
    * and — the heart of the feature — a *calendar projection* of the km part:
      the recent daily mileage (modules.fuel.average_km_per_day) converts
      "fällig in ca. 1.800 km" into "voraussichtlich am 03.09.2026".

The overall due date is the EARLIER of the time rule and the projected km
rule. Edge cases are explicit states, never crashes: a brand-new vehicle
without history has no km projection (time rule only, with a hint), a rule
that was never completed anchors at its creation… nothing extrapolates from
unusable data (see MIN_SPAN_DAYS in modules.fuel).

Pure logic, Qt-free, fully unit-tested.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from modules import dates
from modules.fuel import OdoReading, average_km_per_day, current_km
from modules.models import CareRule

# Status keys map onto the app-wide traffic-light pills.
STATUS_OVERDUE = "overdue"    # red    — at least one part is due/over
STATUS_SOON = "soon"          # amber  — due within the lead window
STATUS_OK = "ok"              # green  — comfortably away
STATUS_UNKNOWN = "unknown"    # grey   — rule has no usable base data

# "Due soon" thresholds (lead window). Kept as module constants so the UI and
# the startup reminder use identical semantics.
LEAD_DAYS = 30
LEAD_KM = 1000


@dataclass(frozen=True)
class RuleStatus:
    """Evaluated state of one care rule against one vehicle."""
    rule: CareRule
    status: str                       # STATUS_* key
    due_date: date | None             # earliest projected/scheduled due date
    due_date_source: str              # 'zeit' | 'km-prognose' | ''
    km_remaining: int | None          # km until the km part is due (negative = over)
    time_due_date: date | None        # due date of the time part
    km_projected_date: date | None    # km part converted to a calendar date
    km_per_day: float | None          # daily mileage used for the projection
    hint: str                         # German hint for edge cases ('' = none)


def _anchor(rule: CareRule) -> tuple[date | None, int | None]:
    """Base point of the interval: the last completion (date, km).

    A rule that was never completed has no anchor km; its time part anchors at
    the rule's creation date via letzte_datum being NULL — the caller passes
    the rule row that keeps created_at out of the dataclass, so we simply
    treat "no last date" as "unknown" and report STATUS_UNKNOWN unless the
    interval can be evaluated another way.
    """
    return dates.parse_date(rule.letzte_datum), rule.letzte_km


def evaluate_rule(rule: CareRule, history: list[OdoReading],
                  today: date | None = None,
                  lead_days: int = LEAD_DAYS,
                  lead_km: int = LEAD_KM) -> RuleStatus:
    """Evaluate one rule: remaining km, time due date, calendar projection.

    ``history`` is the vehicle's odometer history (modules.fuel.km_history).
    """
    today = today or dates.today()
    last_date, last_km = _anchor(rule)
    km_now = current_km(history)
    km_rate = average_km_per_day(history, today=today)

    hint = ""

    # --- time part ---------------------------------------------------------
    time_due: date | None = None
    if rule.intervall_monate:
        base = last_date or today
        time_due = dates.add_months(base, rule.intervall_monate)
        if last_date is None:
            hint = ("Noch nie durchgeführt — die Zeitregel zählt ab heute. "
                    "Beim ersten Erledigen wird das Intervall verankert.")

    # --- km part -------------------------------------------------------------
    km_remaining: int | None = None
    km_projected: date | None = None
    if rule.intervall_km:
        if last_km is not None and km_now is not None:
            km_remaining = (last_km + rule.intervall_km) - km_now
            if km_rate is not None and km_rate > 0:
                if km_remaining <= 0:
                    km_projected = today  # already reached
                else:
                    km_projected = today + timedelta(days=round(km_remaining / km_rate))
            elif not hint:
                hint = ("Für eine Datums-Prognose der km-Regel fehlen aktuelle "
                        "km-Stände — Tankbuch-Einträge liefern die Datenbasis.")
        elif not hint:
            if last_km is None:
                hint = ("Noch kein km-Stand der letzten Durchführung hinterlegt — "
                        "die km-Regel startet mit dem ersten Erledigen.")
            else:
                hint = ("Noch keine km-Stände erfasst — bitte einen aktuellen "
                        "km-Stand im Fahrzeugprofil oder Tankbuch eintragen.")

    # --- combine: what comes first ------------------------------------------
    candidates: list[tuple[date, str]] = []
    if time_due is not None:
        candidates.append((time_due, "zeit"))
    if km_projected is not None:
        candidates.append((km_projected, "km-prognose"))
    if candidates:
        due_date, source = min(candidates, key=lambda c: c[0])
    else:
        due_date, source = None, ""

    # --- status traffic light ---------------------------------------------------
    overdue = ((time_due is not None and time_due <= today)
               or (km_remaining is not None and km_remaining <= 0))
    soon = ((time_due is not None and time_due <= today + timedelta(days=lead_days))
            or (km_remaining is not None and km_remaining <= lead_km))
    if overdue:
        status = STATUS_OVERDUE
    elif soon:
        status = STATUS_SOON
    elif due_date is not None or km_remaining is not None:
        status = STATUS_OK
    else:
        status = STATUS_UNKNOWN

    return RuleStatus(
        rule=rule, status=status, due_date=due_date, due_date_source=source,
        km_remaining=km_remaining, time_due_date=time_due,
        km_projected_date=km_projected, km_per_day=km_rate, hint=hint,
    )


def evaluate_all(rules: list[CareRule], history: list[OdoReading],
                 today: date | None = None,
                 lead_days: int = LEAD_DAYS,
                 lead_km: int = LEAD_KM) -> list[RuleStatus]:
    """Evaluate every rule and sort: overdue first, then by due date."""
    order = {STATUS_OVERDUE: 0, STATUS_SOON: 1, STATUS_OK: 2, STATUS_UNKNOWN: 3}
    result = [evaluate_rule(r, history, today, lead_days, lead_km) for r in rules]
    result.sort(key=lambda s: (order.get(s.status, 9),
                               s.due_date or date.max, s.rule.name.lower()))
    return result


def status_text(s: RuleStatus) -> str:
    """One-line German summary, e.g. 'fällig in ca. 1.800 km ≈ 03.09.2026'."""
    if s.status == STATUS_UNKNOWN:
        return "keine Datenbasis"
    parts: list[str] = []
    if s.km_remaining is not None:
        if s.km_remaining <= 0:
            over = -s.km_remaining
            parts.append("km-Intervall erreicht" if over == 0 else
                         f"überfällig seit {over:,} km".replace(",", "."))
        else:
            km_txt = f"fällig in ca. {s.km_remaining:,} km".replace(",", ".")
            if s.km_projected_date is not None:
                km_txt += f" ≈ voraussichtlich {dates.format_date(s.km_projected_date)}"
            parts.append(km_txt)
    if s.time_due_date is not None:
        if s.time_due_date <= dates.today():
            parts.append(f"Zeitintervall fällig seit {dates.format_date(s.time_due_date)}")
        else:
            parts.append(f"spätestens am {dates.format_date(s.time_due_date)}")
    return " · ".join(parts) if parts else "keine Datenbasis"
