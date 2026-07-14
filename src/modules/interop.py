"""App-family interop: discover the sister app and read its interop views.

The contract (full spec: INTEROP.md in the repo root):

    * Every family app writes an announcement file into the shared family
      folder (``<data base>/AppFamilie``) on each start:
      ``kfzmanager.json`` / ``haushaltsmanager.json`` with
      ``{app_name, app_version, interop_version, db_path, updated_at}``.
    * A sister database is read EXCLUSIVELY through its ``interop_*`` SQL
      views plus ``interop_meta`` — never through its private tables — and
      strictly read-only (``file:…?mode=ro`` + busy_timeout).
    * Handshake: the integration is active only when the sister's
      interop_version has the same MAJOR as ours; otherwise the UI shows a
      polite "bitte <App> aktualisieren" hint and stays off.

Failure philosophy: the integration is a bonus. Every error path (missing
folder, broken JSON, locked/missing DB, the WAL read-only edge case where a
WAL-mode database cannot be opened read-only) degrades to "integration off
for this session" — it NEVER crashes or blocks the app.

The Haushalt→KFZ direction (budget-context card: "Fahrzeugkosten = X % der
Monatsausgaben") is fully wired here; it activates automatically as soon as
the HaushaltsManager (v3.6+) ships its ``interop_ausgaben_monat`` view.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app_meta import APP_VERSION, database_path, family_dir
from modules.db_handler.database import INTEROP_VERSION
from modules.logging_setup import get_logger

_log = get_logger("interop")

OWN_ANNOUNCE_FILE = "kfzmanager.json"
SISTER_ANNOUNCE_FILE = "haushaltsmanager.json"
SISTER_APP_NAME = "HaushaltsManager"
# The sister's conventional data dir name — used only for the "sister exists
# but has no interop yet" detection (HaushaltsManager <= 3.5 writes no
# announcement file).
SISTER_DATA_DIRNAME = "HaushaltsManager"
SISTER_DB_FILENAME = "haushalt.db"
SISTER_MIN_VERSION_HINT = "3.6"


@dataclass(frozen=True)
class SisterState:
    """Result of the discovery/handshake for the settings/dashboard UI."""
    status: str          # 'aktiv' | 'fehlt' | 'ohne-interop' | 'version' | 'fehler'
    message: str         # German status text
    db_path: Path | None = None
    app_version: str = ""
    interop_version: int | None = None


def announce_self(db_path: Path | None = None, now: datetime | None = None) -> None:
    """Write/refresh our announcement file in the family folder.

    Called on every start. Never raises — a read-only profile or exotic
    setup must not break the app over a bonus feature.
    """
    try:
        payload = {
            "app_name": "KFZManager",
            "app_version": APP_VERSION,
            "interop_version": INTEROP_VERSION,
            "db_path": str(db_path or database_path()),
            "updated_at": (now or datetime.now(timezone.utc)).isoformat(),
        }
        target = family_dir() / OWN_ANNOUNCE_FILE
        with open(target, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        _log.warning("Familien-Ankündigung fehlgeschlagen: %s", exc)


def _legacy_sister_db() -> Path | None:
    """Detect a HaushaltsManager installation that predates the interop layer.

    Checks the conventional data location for its database file. Only used to
    show the "Integration verfügbar ab HaushaltsManager v3.6" hint.
    """
    try:
        candidate = family_dir(create=False).parent / SISTER_DATA_DIRNAME / SISTER_DB_FILENAME
        return candidate if candidate.is_file() else None
    except OSError:
        return None


def discover_sister() -> SisterState:
    """Find the sister app and validate the handshake (never raises)."""
    try:
        announce = family_dir(create=False) / SISTER_ANNOUNCE_FILE
        if not announce.is_file():
            if _legacy_sister_db() is not None:
                return SisterState(
                    status="ohne-interop",
                    message=(f"{SISTER_APP_NAME} ist installiert, unterstützt die "
                             f"Integration aber noch nicht. Verfügbar ab "
                             f"{SISTER_APP_NAME} v{SISTER_MIN_VERSION_HINT}."))
            return SisterState(
                status="fehlt",
                message=f"{SISTER_APP_NAME} wurde auf diesem Gerät nicht gefunden.")
        try:
            with open(announce, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            _log.info("Schwester-Ankündigung unlesbar: %s", exc)
            return SisterState(
                status="fehler",
                message=f"Die Ankündigungsdatei von {SISTER_APP_NAME} ist unlesbar.")

        version = data.get("interop_version")
        db_path = Path(str(data.get("db_path") or ""))
        app_version = str(data.get("app_version") or "")
        if not isinstance(version, int):
            return SisterState(
                status="fehler",
                message=f"{SISTER_APP_NAME} meldet keine gültige Interop-Version.")
        # Same-major handshake (interop versions are plain integers → the
        # integer IS the major).
        if version != INTEROP_VERSION:
            newer = version > INTEROP_VERSION
            which = "den KFZ-Manager" if newer else SISTER_APP_NAME
            return SisterState(
                status="version",
                message=(f"Die Apps sprechen verschiedene Interop-Versionen "
                         f"(hier v{INTEROP_VERSION}, dort v{version}). "
                         f"Bitte {which} aktualisieren."),
                app_version=app_version, interop_version=version)
        if not db_path.is_file():
            return SisterState(
                status="fehler",
                message=f"Die Datenbank von {SISTER_APP_NAME} wurde nicht gefunden.",
                app_version=app_version, interop_version=version)
        return SisterState(
            status="aktiv",
            message=f"Verbunden mit {SISTER_APP_NAME} v{app_version}.",
            db_path=db_path, app_version=app_version, interop_version=version)
    except Exception as exc:  # noqa: BLE001 - discovery must never crash the app
        _log.warning("Schwester-Erkennung fehlgeschlagen: %s", exc)
        return SisterState(status="fehler",
                           message="Die Familien-Erkennung ist fehlgeschlagen.")


def _open_readonly(db_path: Path) -> sqlite3.Connection | None:
    """Open a sister database strictly read-only.

    Returns None when the open fails — including the WAL edge case: a
    WAL-mode database may be unreadable in ``mode=ro`` when its ``-shm``
    sidecar cannot be created/locked. Per contract the integration then
    silently deactivates for this session instead of crashing.
    """
    try:
        uri = f"{db_path.resolve().as_uri()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=2.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 2000")
        # Touch the schema once: WAL/lock problems surface here, not later
        # in the middle of a query.
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
        return conn
    except sqlite3.Error as exc:
        _log.info("Schwester-DB nicht lesbar (Integration deaktiviert): %s", exc)
        return None


def sister_interop_version(db_path: Path) -> int | None:
    """interop_version stored INSIDE the sister DB (None when unreadable)."""
    conn = _open_readonly(db_path)
    if conn is None:
        return None
    try:
        row = conn.execute("SELECT interop_version FROM interop_meta LIMIT 1").fetchone()
        return int(row[0]) if row else None
    except (sqlite3.Error, TypeError, ValueError):
        return None
    finally:
        conn.close()


def household_month_expenses(db_path: Path, year: int, month: int) -> int | None:
    """Total household expenses for one month from the sister's view (cents).

    Reads ``interop_ausgaben_monat (jahr, monat, summe_cent)`` — the view the
    HaushaltsManager provides from v3.6 on. Returns None when the view is
    missing (older sister), unreadable or empty; the caller hides the budget
    card in that case.
    """
    conn = _open_readonly(db_path)
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT summe_cent FROM interop_ausgaben_monat "
            "WHERE jahr = ? AND monat = ?", (year, month)).fetchone()
        return int(row[0]) if row and row[0] is not None else None
    except (sqlite3.Error, TypeError, ValueError) as exc:
        _log.info("interop_ausgaben_monat nicht verfügbar: %s", exc)
        return None
    finally:
        conn.close()


def budget_context(sister: SisterState, vehicle_costs_cents: int,
                   year: int, month: int) -> str | None:
    """Budget-context sentence for the dashboard card (None = hide the card).

    Active automatically once the sister ships her views: needs an active
    handshake AND a non-None month total from ``interop_ausgaben_monat``.
    """
    if sister.status != "aktiv" or sister.db_path is None:
        return None
    household = household_month_expenses(sister.db_path, year, month)
    if household is None or household <= 0:
        return None
    share = vehicle_costs_cents / household * 100.0
    from modules.money import format_eur
    return (f"Fahrzeugkosten {format_eur(vehicle_costs_cents)} = "
            f"{share:.0f} % deiner Monatsausgaben ({format_eur(household)})")
