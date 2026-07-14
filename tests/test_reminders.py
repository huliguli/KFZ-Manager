"""Termin-Status und Start-Erinnerungen."""

from datetime import date

from modules import reminders
from modules.fuel import OdoReading
from modules.models import Appointment, CareRule, Vehicle

TODAY = date(2026, 7, 14)


def _appt(**kwargs) -> Appointment:
    defaults = dict(vehicle_id=1, typ="TÜV/HU")
    defaults.update(kwargs)
    return Appointment(**defaults)


def test_date_overdue_and_soon():
    status, text = reminders.appointment_status(
        _appt(faellig_datum="2026-07-01"), None, TODAY)
    assert status == reminders.STATUS_OVERDUE and "überfällig" in text

    status, _ = reminders.appointment_status(
        _appt(faellig_datum="2026-08-01"), None, TODAY, lead_days=30)
    assert status == reminders.STATUS_SOON

    status, _ = reminders.appointment_status(
        _appt(faellig_datum="2026-12-24"), None, TODAY, lead_days=30)
    assert status == reminders.STATUS_OK


def test_km_due():
    status, text = reminders.appointment_status(
        _appt(faellig_km=50_000), km_now=50_500, today=TODAY)
    assert status == reminders.STATUS_OVERDUE

    status, _ = reminders.appointment_status(
        _appt(faellig_km=50_000), km_now=49_500, today=TODAY, lead_km=1000)
    assert status == reminders.STATUS_SOON

    status, text = reminders.appointment_status(
        _appt(faellig_km=50_000), km_now=None, today=TODAY)
    assert status == reminders.STATUS_OK and "bei 50.000 km" in text


def test_whichever_comes_first_wins():
    # Date fine, km overdue -> overdue.
    status, _ = reminders.appointment_status(
        _appt(faellig_datum="2026-12-24", faellig_km=40_000),
        km_now=41_000, today=TODAY)
    assert status == reminders.STATUS_OVERDUE


def test_collect_sorts_overdue_first():
    v = Vehicle(name="Golf", id=1)
    appts = {1: [_appt(faellig_datum="2026-08-01"),          # soon
                 _appt(typ="Inspektion", faellig_datum="2026-07-01")]}  # overdue
    rules = {1: [CareRule(vehicle_id=1, name="Öl", intervall_monate=1,
                          letzte_datum="2026-01-01")]}        # overdue
    history = {1: [OdoReading(TODAY, 10_000)]}
    items = reminders.collect([v], appts, rules, history, today=TODAY)
    assert [i.status for i in items] == [
        reminders.STATUS_OVERDUE, reminders.STATUS_OVERDUE, reminders.STATUS_SOON]
    # Completed appointments never appear.
    appts_done = {1: [_appt(faellig_datum="2026-07-01", erledigt=True)]}
    assert reminders.collect([v], appts_done, {1: []}, history, today=TODAY) == []
