"""Backup, restore and integrity checking — database PLUS attachments (Qt-free).

A KFZ-Manager backup must cover more than the SQLite file: the Scheckheft's
attachment files live next to the database and belong to the data. Each
backup is therefore a single ZIP archive::

    kfz-YYYYMMDD-HHMMSS-<label>.zip
        kfz.db              — consistent snapshot (SQLite online backup API)
        attachments/...     — every stored attachment file

The database snapshot uses ``Connection.backup`` so it is consistent even
while the shared connection is in use (WAL mode) — no file-level copy races.
Backups live in ``<data_dir>/backups``; a small rotation keeps the newest
``MAX_BACKUPS``. Everything here is platform-neutral (pathlib + sqlite3 +
zipfile only) so Windows and macOS behave identically.

ZIP extraction is hardened: only ``kfz.db`` and members under
``attachments/`` are honoured, each resolved target must stay inside its
destination folder (no traversal via crafted names).
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from app_meta import attachments_dir, data_dir
from modules.logging_setup import get_logger

_log = get_logger("backup")

MAX_BACKUPS = 10

DB_MEMBER = "kfz.db"
ATTACH_PREFIX = "attachments/"

# Labels are part of the filename, so keep them to a safe character set.
_LABEL_RE = re.compile(r"[^a-z0-9\-]")
_NAME_RE = re.compile(r"^kfz-(\d{8})-(\d{6})(?:-(\d+))?-([a-z0-9\-]+)\.zip$")

# Human-readable label texts for the restore picker.
LABEL_TEXTS = {
    "start": "Automatisch (Programmstart)",
    "manuell": "Manuell erstellt",
    "vor-migration": "Vor Daten-Aktualisierung",
    "vor-loeschen": "Vor dem Löschen aller Daten",
    "vor-wiederherstellung": "Vor einer Wiederherstellung",
}


class BackupError(RuntimeError):
    """A backup or restore step failed; message is user-presentable German."""


def backups_dir(db_path: Path | None = None) -> Path:
    """Backup folder for the given database (next to the .db file).

    Backups live BESIDE the database they protect: in production that is
    ``<data_dir>/backups``, and a test database in a temp folder gets its
    backups there too — a test run can never write into the real profile.
    """
    base = Path(db_path).parent if db_path else data_dir()
    path = base / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    created: datetime
    label: str
    size_bytes: int

    @property
    def label_text(self) -> str:
        return LABEL_TEXTS.get(self.label, self.label)


def _sanitize_label(label: str) -> str:
    cleaned = _LABEL_RE.sub("-", label.lower()).strip("-") or "manuell"
    return cleaned[:40]


def _backup_filename(directory: Path, now: datetime, label: str) -> Path:
    stamp = now.strftime("%Y%m%d-%H%M%S")
    candidate = directory / f"kfz-{stamp}-{label}.zip"
    # Two backups within the same second (e.g. tests) get a counter suffix.
    counter = 1
    while candidate.exists():
        candidate = directory / f"kfz-{stamp}-{counter}-{label}.zip"
        counter += 1
    return candidate


def create_backup(
    conn: sqlite3.Connection,
    label: str = "manuell",
    directory: Path | None = None,
    now: datetime | None = None,
    attachments_root: Path | None = None,
) -> Path:
    """Snapshot database + attachments into a new ZIP and rotate.

    Raises :class:`BackupError` when the snapshot cannot be written — callers
    that are about to do something destructive (wipe, restore) must treat that
    as a hard stop (fail closed), not as a warning.
    """
    directory = directory or backups_dir()
    directory.mkdir(parents=True, exist_ok=True)
    target = _backup_filename(directory, now or datetime.now(), _sanitize_label(label))
    attachments_root = attachments_root or attachments_dir()

    tmp_db = None
    try:
        # 1) Consistent DB snapshot into a temp file via the online backup API.
        fd, tmp_name = tempfile.mkstemp(suffix=".db", prefix="kfz-backup-")
        os.close(fd)
        tmp_db = Path(tmp_name)
        dest = sqlite3.connect(tmp_db)
        try:
            conn.backup(dest)
        finally:
            dest.close()
        # 2) Zip snapshot + attachment files.
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(tmp_db, DB_MEMBER)
            if attachments_root.is_dir():
                for path in sorted(attachments_root.rglob("*")):
                    if path.is_file():
                        rel = path.relative_to(attachments_root).as_posix()
                        zf.write(path, ATTACH_PREFIX + rel)
    except (sqlite3.Error, OSError) as exc:
        # Never leave a half-written archive behind — it would look like a
        # valid backup in the restore picker.
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        raise BackupError(f"Sicherung konnte nicht erstellt werden: {exc}") from exc
    finally:
        if tmp_db is not None:
            try:
                tmp_db.unlink(missing_ok=True)
            except OSError:
                pass
    _log.info("Backup erstellt: %s", target.name)
    _rotate(directory)
    return target


def _rotate(directory: Path, keep: int = MAX_BACKUPS) -> None:
    backups = list_backups(directory)
    for info in backups[keep:]:
        try:
            info.path.unlink()
            _log.info("Altes Backup entfernt: %s", info.path.name)
        except OSError:
            pass  # a locked/undeletable old backup must never block the new one


def list_backups(directory: Path | None = None) -> list[BackupInfo]:
    """All recognised backups, newest first."""
    directory = directory or backups_dir()
    result: list[BackupInfo] = []
    try:
        entries = sorted(directory.glob("kfz-*.zip"))
    except OSError:
        return []
    for path in entries:
        match = _NAME_RE.match(path.name)
        if not match:
            continue
        day, clock, counter, label = match.groups()
        try:
            created = datetime.strptime(f"{day}{clock}", "%Y%m%d%H%M%S")
            size = path.stat().st_size
        except (ValueError, OSError):
            continue
        # The counter only orders same-second backups; fold it into microseconds
        # so sorting stays purely chronological.
        if counter:
            created = created.replace(microsecond=min(999_999, int(counter)))
        result.append(BackupInfo(path=path, created=created, label=label, size_bytes=size))
    result.sort(key=lambda info: (info.created, info.path.name), reverse=True)
    return result


def startup_backup(conn: sqlite3.Connection, directory: Path | None = None) -> Path | None:
    """Create the automatic start-of-day backup (at most one per calendar day).

    Never raises: a failing automatic backup must not block the app start —
    it is logged, and manual backups from the settings remain available.
    """
    try:
        directory = directory or backups_dir()
        today = date.today()
        for info in list_backups(directory):
            if info.label == "start" and info.created.date() == today:
                return None  # already covered for today
        return create_backup(conn, label="start", directory=directory)
    except Exception as exc:  # noqa: BLE001 - deliberately never blocks startup
        _log.warning("Automatisches Start-Backup fehlgeschlagen: %s", exc)
        return None


def integrity_ok(conn: sqlite3.Connection) -> bool:
    """Fast structural check of the open database (PRAGMA quick_check)."""
    try:
        row = conn.execute("PRAGMA quick_check(1)").fetchone()
        return bool(row) and str(row[0]).lower() == "ok"
    except sqlite3.Error:
        return False


def _safe_extract_member(zf: zipfile.ZipFile, member: str, dest: Path,
                         arcname: str | None = None) -> Path:
    """Extract one member below ``dest`` with traversal protection.

    ``member`` is the RELATIVE target path below ``dest``; ``arcname`` is the
    (possibly prefixed) name inside the archive — they differ for attachment
    members, whose ``attachments/`` prefix is stripped for the target.
    """
    target = (dest / member).resolve()
    if not target.is_relative_to(dest.resolve()):
        raise BackupError(f"Unsicherer Pfad im Backup-Archiv: {member}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with zf.open(arcname or member) as src, open(target, "wb") as out:
        shutil.copyfileobj(src, out)
    return target


def _extract_db_to_temp(backup_path: Path) -> Path:
    """Pull the DB snapshot out of a backup ZIP into a temp file."""
    if not backup_path.exists():
        raise BackupError("Die Sicherungsdatei existiert nicht mehr.")
    try:
        with zipfile.ZipFile(backup_path) as zf:
            if DB_MEMBER not in zf.namelist():
                raise BackupError("Die Sicherung enthält keine Datenbank.")
            tmp_dir = Path(tempfile.mkdtemp(prefix="kfz-restore-"))
            return _safe_extract_member(zf, DB_MEMBER, tmp_dir)
    except (zipfile.BadZipFile, OSError) as exc:
        raise BackupError(f"Sicherung kann nicht geöffnet werden: {exc}") from exc


def backup_schema_version(path: Path) -> int | None:
    """Stored schema version of a backup archive (None when unreadable)."""
    try:
        tmp_db = _extract_db_to_temp(path)
    except BackupError:
        return None
    try:
        src = sqlite3.connect(f"{tmp_db.resolve().as_uri()}?mode=ro", uri=True)
        try:
            row = src.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            return int(row[0]) if row else None
        finally:
            src.close()
    except (sqlite3.Error, ValueError, TypeError, OSError):
        return None
    finally:
        shutil.rmtree(tmp_db.parent, ignore_errors=True)


def _restore_attachments(backup_path: Path, attachments_root: Path) -> None:
    """Replace the attachment store with the archive's content.

    Staged: extract into a temp folder first, then swap — a broken archive
    can never leave a half-emptied store behind.
    """
    staging = Path(tempfile.mkdtemp(prefix="kfz-attach-restore-"))
    try:
        with zipfile.ZipFile(backup_path) as zf:
            for member in zf.namelist():
                if member.endswith("/") or not member.startswith(ATTACH_PREFIX):
                    continue
                rel = member[len(ATTACH_PREFIX):]
                if not rel:
                    continue
                _safe_extract_member(zf, rel, staging, arcname=member)
        # Swap: clear the live store, then move the staged tree in.
        if attachments_root.exists():
            shutil.rmtree(attachments_root, ignore_errors=True)
        attachments_root.mkdir(parents=True, exist_ok=True)
        for path in staging.rglob("*"):
            if path.is_file():
                rel = path.relative_to(staging)
                target = attachments_root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), target)
    except (zipfile.BadZipFile, OSError) as exc:
        raise BackupError(
            f"Anhänge konnten nicht wiederhergestellt werden: {exc}") from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def restore_into_connection(conn: sqlite3.Connection, backup_path: Path,
                            attachments_root: Path | None = None) -> None:
    """Replace the live database content AND attachments with a backup.

    Uses the backup API in reverse (snapshot file -> live connection), so the
    shared connection object every repository holds stays valid — no file
    swapping, no reopening. The caller must re-run schema initialisation
    afterwards (an older backup may predate the current schema) and refresh
    the UI.

    Raises :class:`BackupError` with a user-presentable German message when
    the archive is unreadable or damaged; the live data is only touched after
    the snapshot passed its own integrity check.
    """
    tmp_db = _extract_db_to_temp(backup_path)
    try:
        try:
            src = sqlite3.connect(f"{tmp_db.resolve().as_uri()}?mode=ro", uri=True)
        except (sqlite3.Error, OSError) as exc:
            raise BackupError(f"Sicherung kann nicht geöffnet werden: {exc}") from exc
        try:
            row = src.execute("PRAGMA quick_check(1)").fetchone()
            if not row or str(row[0]).lower() != "ok":
                raise BackupError(
                    "Die Sicherungsdatei ist beschädigt und kann nicht "
                    "wiederhergestellt werden.")
            src.backup(conn)
            conn.commit()
        except sqlite3.Error as exc:
            raise BackupError(f"Wiederherstellung fehlgeschlagen: {exc}") from exc
        finally:
            src.close()
    finally:
        shutil.rmtree(tmp_db.parent, ignore_errors=True)

    _restore_attachments(backup_path, attachments_root or attachments_dir())
    _log.info("Datenbank + Anhänge aus Backup wiederhergestellt: %s", backup_path.name)


def replace_database_file(db_path: Path, backup_path: Path,
                          attachments_root: Path | None = None) -> Path:
    """File-level recovery for a database that cannot even be opened.

    Only for the corruption path at startup, where no usable connection
    exists: the damaged file is renamed aside (never deleted — it may still
    hold forensically recoverable data), its WAL/SHM sidecars are removed
    (they belong to the damaged state), and the snapshot is copied into
    place. Attachments are restored afterwards. Returns the path the damaged
    file was moved to.

    Raises :class:`BackupError` when any step fails; in that case the
    original file layout is left as intact as possible.
    """
    tmp_db = _extract_db_to_temp(backup_path)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    aside = db_path.with_name(f"{db_path.stem}-defekt-{stamp}{db_path.suffix}")
    try:
        if db_path.exists():
            db_path.rename(aside)
        for suffix in ("-wal", "-shm"):
            sidecar = db_path.with_name(db_path.name + suffix)
            if sidecar.exists():
                sidecar.unlink()
        shutil.copyfile(tmp_db, db_path)
    except OSError as exc:
        raise BackupError(
            f"Wiederherstellung auf Dateiebene fehlgeschlagen: {exc}") from exc
    finally:
        shutil.rmtree(tmp_db.parent, ignore_errors=True)
    _restore_attachments(backup_path, attachments_root or attachments_dir())
    _log.info("Beschädigte Datenbank ersetzt (%s -> %s)", aside.name, backup_path.name)
    return aside
