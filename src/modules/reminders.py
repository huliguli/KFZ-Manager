"""Startup reminders: which appointments and care rules deserve attention now.

Collects due/soon items across ALL vehicles for the reminder dialog shown at
app start (lead time configurable in Settings, mirroring the sister app's
startup-notice pattern). Pure logic, Qt-free.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from modules import dates, intervals
from modules.fuel import OdoReading, current_km
from modules.models import Appointment, CareRule, Vehicle

STATUS_OVERDUE = intervals.STATUS_OVERDUE
STATUS_SOON = intervals.STATUS_SOON
STATUS_OK = intervals.STATUS_OK


@dataclass(frozen=True)
class ReminderItem:
    """One line in the startup reminder / Termine table."""
    vehicle: Vehicle
    kind: str          # 'termin' | 'pflege'
    title: str
    status: str        # STATUS_* key
    detail: str        # German due text


def appointment_status(appt: Appointment, km_now: int | None,
                       today: date | None = None,
                       lead_days: int = 30, lead_km: int = 1000) -> tuple[str, str]:
    """Traffic-light status + due text for one appointment.

    Due by date and/or km — whichever is closer decides. An appointment with
    neither criterion is always "ok" (a note, not a deadline).
    """
    today = today or dates.today()
    status = STATUS_OK
    parts: list[str] = []

    due = dates.parse_date(appt.faellig_datum)
    if due is not None:
        if due < today:
            status = STATUS_OVERDUE
            parts.append(f"überfällig seit {dates.format_date(due)}")
        else:
            if due <= today + timedelta(days=lead_days):
                status = STATUS_SOON
            parts.append(f"fällig am {dates.format_date(due)}")

    if appt.faellig_km is not None and km_now is not None:
        remaining = appt.faellig_km - km_now
        if remaining <= 0:
            status = STATUS_OVERDUE
            parts.append(f"km-Stand erreicht ({km_now:,} km)".replace(",", "."))
        else:
            if remaining <= lead_km and status != STATUS_OVERDUE:
                status = STATUS_SOON
            parts.append(f"in {remaining:,} km".replace(",", "."))
    elif appt.faellig_km is not None:
        parts.append(f"bei {appt.faellig_km:,} km".replace(",", "."))

    return status, " · ".join(parts) if parts else "ohne Fälligkeit"


def collect(vehicles: list[Vehicle],
            appointments_by_vehicle: dict[int, list[Appointment]],
            rules_by_vehicle: dict[int, list[CareRule]],
            history_by_vehicle: dict[int, list[OdoReading]],
            today: date | None = None,
            lead_days: int = 30, lead_km: int = 1000) -> list[ReminderItem]:
    """All items that are due or due soon, most urgent first."""
    items: list[ReminderItem] = []
    for vehicle in vehicles:
        if vehicle.id is None:
            continue
        history = history_by_vehicle.get(vehicle.id, [])
        km_now = current_km(history)
        for appt in appointments_by_vehicle.get(vehicle.id, []):
            if appt.erledigt:
                continue
            status, detail = appointment_status(
                appt, km_now, today, lead_days, lead_km)
            if status in (STATUS_OVERDUE, STATUS_SOON):
                items.append(ReminderItem(vehicle, "termin", appt.typ, status, detail))
        for rule_status in intervals.evaluate_all(
                rules_by_vehicle.get(vehicle.id, []), history, today,
                lead_days, lead_km):
            if rule_status.status in (STATUS_OVERDUE, STATUS_SOON):
                items.append(ReminderItem(
                    vehicle, "pflege", rule_status.rule.name,
                    rule_status.status, intervals.status_text(rule_status)))
    order = {STATUS_OVERDUE: 0, STATUS_SOON: 1}
    items.sort(key=lambda i: (order.get(i.status, 2), i.vehicle.name.lower(), i.title.lower()))
    return items
