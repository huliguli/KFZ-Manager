"""Headless UI smoke test.

The rest of the suite covers pure logic but never constructs a widget, so an
ImportError, a missing colour token, a broken icon or a QSS typo would only
surface as a start-up crash for the user while the suite stays green. This test
builds the whole window, visits every view (running each refresh()) and toggles
the theme — under the offscreen Qt platform so it runs without a display/CI.
"""

import os

# Must be set before the first QApplication is created.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_mainwindow_and_all_views_construct(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))

    try:
        from PyQt6.QtWidgets import QApplication
    except Exception as exc:  # pragma: no cover - Qt unavailable in this env
        import pytest
        pytest.skip(f"Qt nicht verfügbar: {exc}")

    from modules.config import Config
    from modules.db_handler.database import Database
    from modules.db_handler.repositories import (
        CareRuleRepository,
        CostRepository,
        TankRepository,
        VehicleRepository,
    )
    from modules.models import CareRule, Cost, TankEntry, Vehicle
    from ui import theme
    from ui.app_context import AppContext
    from ui.main_window import _NAV, MainWindow

    app = QApplication.instance() or QApplication([])
    db = Database(tmp_path / "smoke.db")

    # Realistic content so every view renders data paths, not just empty states.
    vid = VehicleRepository(db).add(Vehicle(
        name="Golf", kraftstoff="diesel", partikelfilter="dpf",
        direkteinspritzung=True, fahrprofil="kurzstrecke", km_stand=50_000,
        km_stand_datum="2026-07-01", erstzulassung="2015-06-01"))
    TankRepository(db).add(TankEntry(vehicle_id=vid, date="2026-06-01",
                                     odo_km=49_000, menge_ml=45_000,
                                     betrag_cent=7200))
    TankRepository(db).add(TankEntry(vehicle_id=vid, date="2026-07-01",
                                     odo_km=50_000, menge_ml=42_000,
                                     betrag_cent=6800))
    CostRepository(db).add(Cost(vehicle_id=vid, date="2026-07-05",
                                kategorie="Werkstatt", betrag_cent=12000))
    CareRuleRepository(db).add(CareRule(vehicle_id=vid, name="Ölwechsel",
                                        intervall_km=15_000, intervall_monate=12,
                                        letzte_datum="2026-01-01", letzte_km=45_000))

    ctx = AppContext(db, Config())
    app.setStyleSheet(theme.build_qss(ctx.colors))

    window = MainWindow(ctx)
    # Visiting each view runs its refresh()/build path.
    for index in range(len(_NAV)):
        window._select(index)
    # Toggling the theme rebuilds the QSS and re-tints/refreshes every view.
    ctx.set_theme("dark")
    ctx.set_theme("light")

    window.close()
    db.close()
