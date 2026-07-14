"""Laufzeit-Checks: stündlicher Update-Check + 5-Minuten-Familien-Erkennung.

Die App läuft oft tagelang — Updates und die Schwester-App müssen deshalb
auch OHNE Neustart ankommen: Update-Prüfung wiederholt sich stündlich (mit
Sitzungs-„Später“), der Familienordner wird alle 5 Minuten neu gelesen.
"""

import json
import os
import sqlite3

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from modules.db_handler.database import INTEROP_VERSION  # noqa: E402

# Keep the QApplication referenced for the whole module lifetime.
_APP = None


def _window(tmp_path, monkeypatch):
    global _APP
    monkeypatch.setenv("APPDATA", str(tmp_path))
    try:
        from PyQt6.QtWidgets import QApplication
    except Exception as exc:  # pragma: no cover - Qt unavailable in this env
        import pytest
        pytest.skip(f"Qt nicht verfügbar: {exc}")
    _APP = QApplication.instance() or QApplication([])

    from modules.config import Config
    from modules.db_handler.database import Database
    from ui.app_context import AppContext
    from ui.main_window import MainWindow

    db = Database(tmp_path / "bg.db")
    ctx = AppContext(db, Config())
    return MainWindow(ctx), ctx, db


def _info(tag: str = "v99.0.0"):
    from modules.updater.updater import UpdateInfo
    return UpdateInfo(version=tag.lstrip("v"), tag=tag, notes="",
                      asset_url="https://github.com/x/Setup.exe",
                      html_url="https://github.com/x")


def _spy(window):
    calls = []
    settings = window._views[-1]
    settings.auto_install = lambda info: calls.append(("auto", info.tag))
    settings.show_update_dialog = lambda info: calls.append(("dialog", info.tag))
    return calls


def _announce_sister(tmp_path):
    """Fake HaushaltsManager: announcement + minimal contract DB."""
    from app_meta import family_dir
    from modules import interop
    db_path = tmp_path / "haushalt.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE interop_meta (interop_version INTEGER NOT NULL)")
    conn.execute("INSERT INTO interop_meta VALUES (?)", (INTEROP_VERSION,))
    conn.commit()
    conn.close()
    (family_dir() / interop.SISTER_ANNOUNCE_FILE).write_text(json.dumps({
        "app_name": "HaushaltsManager", "app_version": "3.7.0",
        "interop_version": INTEROP_VERSION, "db_path": str(db_path),
        "updated_at": "2026-07-14T00:00:00+00:00"}), encoding="utf-8")


def test_background_timers_armed(tmp_path, monkeypatch):
    window, ctx, db = _window(tmp_path, monkeypatch)
    assert window._update_timer.isActive()
    assert window._update_timer.interval() == window.UPDATE_CHECK_INTERVAL_MS == 3_600_000
    assert window._family_timer.isActive()
    assert window._family_timer.interval() == window.FAMILY_POLL_INTERVAL_MS == 300_000
    window.close()
    db.close()


def test_session_later_silences_hourly_recheck(tmp_path, monkeypatch):
    window, ctx, db = _window(tmp_path, monkeypatch)
    calls = _spy(window)
    window._views[-1].session_dismissed.add("v99.0.0")
    window._on_startup_update(_info())
    assert calls == []
    # A different version still surfaces.
    window._on_startup_update(_info("v99.0.1"))
    assert calls == [("dialog", "v99.0.1")]
    window.close()
    db.close()


def test_periodic_check_respects_active_flow(tmp_path, monkeypatch):
    window, ctx, db = _window(tmp_path, monkeypatch)
    settings = window._views[-1]
    settings._dialog_open = True
    window._update_checker = None
    window._periodic_update_check()
    assert window._update_checker is None  # no second flow while dialog is open
    window.close()
    db.close()


def test_family_tick_picks_up_new_sister_live(tmp_path, monkeypatch):
    window, ctx, db = _window(tmp_path, monkeypatch)
    assert ctx.sister.status in ("fehlt", "ohne-interop")
    _announce_sister(tmp_path)
    window._family_tick()
    assert ctx.sister.status == "aktiv"
    # Our own announcement was refreshed by the tick too.
    from app_meta import family_dir
    from modules import interop
    assert (family_dir() / interop.OWN_ANNOUNCE_FILE).is_file()
    window.close()
    db.close()
