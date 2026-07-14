"""Interop: Familienordner, Handshake, read-only-Zugriff, Fehlerpfade.

Simuliert die Schwester (HaushaltsManager) über echte Dateien im per-Test
umgeleiteten APPDATA — genau wie im Produktionslayout.
"""

import json
import sqlite3
from pathlib import Path

from app_meta import family_dir
from modules import interop
from modules.db_handler.database import INTEROP_VERSION


def _announce_sister(db_path: Path, interop_version: int = INTEROP_VERSION,
                     app_version: str = "3.6.0", **overrides) -> Path:
    payload = {
        "app_name": "HaushaltsManager",
        "app_version": app_version,
        "interop_version": interop_version,
        "db_path": str(db_path),
        "updated_at": "2026-07-14T00:00:00+00:00",
    }
    payload.update(overrides)
    target = family_dir() / interop.SISTER_ANNOUNCE_FILE
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


def _sister_db(tmp_path: Path, with_view: bool = True) -> Path:
    """Minimal sister database exposing the v3.6 interop contract."""
    path = tmp_path / "haushalt.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE interop_meta (interop_version INTEGER NOT NULL)")
    conn.execute("INSERT INTO interop_meta VALUES (?)", (INTEROP_VERSION,))
    if with_view:
        conn.execute("CREATE TABLE ausgaben (jahr INT, monat INT, summe_cent INT)")
        conn.execute("INSERT INTO ausgaben VALUES (2026, 7, 250000)")
        conn.execute("CREATE VIEW interop_ausgaben_monat AS "
                     "SELECT jahr, monat, summe_cent FROM ausgaben")
    conn.commit()
    conn.close()
    return path


def test_announce_self_writes_json(tmp_path):
    interop.announce_self(tmp_path / "kfz.db")
    data = json.loads((family_dir() / interop.OWN_ANNOUNCE_FILE).read_text("utf-8"))
    assert data["app_name"] == "KFZManager"
    assert data["interop_version"] == INTEROP_VERSION
    assert data["db_path"].endswith("kfz.db")


def test_discover_missing_sister():
    state = interop.discover_sister()
    assert state.status == "fehlt"


def test_discover_legacy_sister_without_interop(tmp_path):
    # HaushaltsManager <= 3.5: data dir + db exist, but no announcement file.
    legacy = family_dir(create=False).parent / interop.SISTER_DATA_DIRNAME
    legacy.mkdir(parents=True, exist_ok=True)
    (legacy / interop.SISTER_DB_FILENAME).write_bytes(b"sqlite")
    state = interop.discover_sister()
    assert state.status == "ohne-interop"
    assert "v3.6" in state.message


def test_discover_broken_json(tmp_path):
    target = family_dir() / interop.SISTER_ANNOUNCE_FILE
    target.write_text("{kaputt", encoding="utf-8")
    state = interop.discover_sister()
    assert state.status == "fehler"


def test_discover_version_mismatch(tmp_path):
    db = _sister_db(tmp_path)
    _announce_sister(db, interop_version=INTEROP_VERSION + 1)
    state = interop.discover_sister()
    assert state.status == "version"
    assert "aktualisieren" in state.message


def test_discover_active_handshake(tmp_path):
    db = _sister_db(tmp_path)
    _announce_sister(db)
    state = interop.discover_sister()
    assert state.status == "aktiv"
    assert state.db_path == db


def test_discover_missing_db_file(tmp_path):
    _announce_sister(tmp_path / "gibtsnicht.db")
    state = interop.discover_sister()
    assert state.status == "fehler"


def test_household_expenses_read_only(tmp_path):
    db = _sister_db(tmp_path)
    assert interop.household_month_expenses(db, 2026, 7) == 250000
    assert interop.household_month_expenses(db, 2026, 1) is None
    # The sister file must remain byte-identical (strictly read-only access).
    assert interop.sister_interop_version(db) == INTEROP_VERSION


def test_household_expenses_missing_view(tmp_path):
    db = _sister_db(tmp_path, with_view=False)
    assert interop.household_month_expenses(db, 2026, 7) is None


def test_unreadable_db_degrades_silently(tmp_path):
    fake = tmp_path / "haushalt.db"
    fake.write_bytes(b"keine datenbank")
    # Both helpers must return None instead of raising.
    assert interop.sister_interop_version(fake) is None
    assert interop.household_month_expenses(fake, 2026, 7) is None


def test_budget_context_active_and_inactive(tmp_path):
    db = _sister_db(tmp_path)
    _announce_sister(db)
    state = interop.discover_sister()
    text = interop.budget_context(state, 50000, 2026, 7)
    assert text is not None and "20 %" in text  # 500 € von 2.500 €
    # No sister -> no card.
    assert interop.budget_context(
        interop.SisterState(status="fehlt", message=""), 50000, 2026, 7) is None
    # Sister without the view -> no card (activates automatically with v3.6).
    sub = tmp_path / "sub"
    sub.mkdir()
    db2 = _sister_db(sub, with_view=False)
    _announce_sister(db2)
    state2 = interop.discover_sister()
    assert interop.budget_context(state2, 50000, 2026, 7) is None
