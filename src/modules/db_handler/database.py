"""SQLite connection management and schema initialisation.

A single connection is shared across the UI. All value binding is
parameterised; the only identifiers ever interpolated into SQL are table and
column names that originate from our own model code (never user input), so
there is no SQL-injection surface.

Mirrors the proven sister-app pattern (HaushaltsManager): idempotent
``schema.sql`` (CREATE ... IF NOT EXISTS) plus a guarded, additive
``_migrate`` and a ``schema_version`` row for the downgrade guard.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable, Sequence

from app_meta import database_path, schema_path
from modules.logging_setup import get_logger

_log = get_logger("db")

CURRENT_SCHEMA_VERSION = 1

# Version of the interop contract this app writes (see INTEROP.md). Stored in
# interop_meta so the sister app can handshake before reading any view.
INTEROP_VERSION = 1


class DatabaseCorruptError(RuntimeError):
    """The database file failed its integrity check on open."""


class SchemaTooNewError(RuntimeError):
    """The database was written by a NEWER app version.

    Running old code against a newer schema is undefined behaviour (missing
    columns, half-understood data), so the open is refused instead — the data
    stays untouched and the message tells the user what to do.
    """


# Every table that holds user-entered vehicle data. The single source of truth
# for the "delete all data" reset — a new table must be added here so the reset
# can never leave orphaned rows behind (schema_version, interop_meta, settings
# and the seed part of the catalog are intentionally excluded; user catalog
# entries and hides ARE data and get cleared).
WIPE_TABLES = (
    "attachments",
    "logbook_entries",
    "care_rules",
    "appointments",
    "costs",
    "tank_entries",
    "catalog_hidden",
    "vehicles",
)


class Database:
    """Thin wrapper around a sqlite3 connection with helper CRUD methods."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else database_path()
        # check_same_thread=False: short-lived worker threads (update check)
        # may touch the DB; we serialise access from the UI in practice.
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        try:
            try:
                self.conn.execute("PRAGMA foreign_keys = ON")
                # journal_mode reads the file header, so a non-database file
                # already fails here — surface it as the same corruption error.
                self.conn.execute("PRAGMA journal_mode = WAL")
            except sqlite3.DatabaseError as exc:
                raise DatabaseCorruptError(
                    "Die Datenbank ist beschädigt und kann nicht geöffnet "
                    f"werden.\nDatei: {self.path}") from exc
            self._guard_before_schema_work()
            self._column_cache: dict[str, set[str]] = {}
            self._initialise()
        except BaseException:
            # A failed open must not keep the file locked — the recovery path
            # (rename aside + restore a backup) needs the handle released,
            # especially on Windows where open files cannot be renamed.
            self.conn.close()
            raise

    # -- schema -------------------------------------------------------------
    def _guard_before_schema_work(self) -> None:
        """Integrity check, downgrade guard and pre-migration backup.

        Runs BEFORE ``executescript``/``_migrate`` ever touch the file: a
        corrupt database or one written by a newer app version must be
        refused while its bytes are still exactly as found on disk.
        """
        from modules import backup

        if not backup.integrity_ok(self.conn):
            raise DatabaseCorruptError(
                "Die Datenbank ist beschädigt und kann nicht geöffnet werden.\n"
                f"Datei: {self.path}")
        stored = self._stored_schema_version()
        if stored is not None and stored > CURRENT_SCHEMA_VERSION:
            raise SchemaTooNewError(
                "Die Daten wurden mit einer neueren Programmversion "
                f"gespeichert (Datenstand v{stored}, dieses Programm kennt "
                f"v{CURRENT_SCHEMA_VERSION}).\nBitte installiere die aktuelle "
                "Version des KFZ-Managers — deine Daten bleiben unverändert.")
        if stored is not None and stored < CURRENT_SCHEMA_VERSION:
            # Snapshot before the (additive) migration runs. A failing backup
            # is logged but does not block the start: migrations are additive
            # by contract, and refusing to start over an unwritable backups
            # folder would lock the user out of their own data.
            try:
                backup.create_backup(
                    self.conn, label="vor-migration",
                    directory=backup.backups_dir(self.path))
            except Exception as exc:  # noqa: BLE001
                _log.warning("Backup vor Migration fehlgeschlagen: %s", exc)

    def _stored_schema_version(self) -> int | None:
        """Schema version recorded in the file (None on a fresh database)."""
        try:
            row = self.conn.execute(
                "SELECT version FROM schema_version LIMIT 1").fetchone()
        except sqlite3.OperationalError:
            return None  # table missing = fresh database
        return int(row["version"]) if row else None

    def reinitialise_after_restore(self) -> None:
        """Re-run schema setup after a backup was restored into the connection.

        A restored snapshot may predate the current schema, so the same
        idempotent path as a normal open runs again (CREATE IF NOT EXISTS +
        guarded migrations). The cached column info is stale after the
        content swap and must be rebuilt.
        """
        self._column_cache.clear()
        self._initialise()

    def _initialise(self) -> None:
        with open(schema_path(), "r", encoding="utf-8") as fh:
            self.conn.executescript(fh.read())
        self._migrate()
        row = self.conn.execute(
            "SELECT version FROM schema_version LIMIT 1"
        ).fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (CURRENT_SCHEMA_VERSION,),
            )
        # Interop handshake data: exactly one row carrying the contract version.
        irow = self.conn.execute(
            "SELECT interop_version FROM interop_meta LIMIT 1").fetchone()
        if irow is None:
            self.conn.execute(
                "INSERT INTO interop_meta (interop_version) VALUES (?)",
                (INTEROP_VERSION,))
        elif int(irow["interop_version"]) != INTEROP_VERSION:
            self.conn.execute(
                "UPDATE interop_meta SET interop_version = ?", (INTEROP_VERSION,))
        self.conn.commit()
        # Seed/merge the recommendation catalog (additive by stable id; user
        # rows and hides are never touched — see modules.catalog).
        from modules import catalog
        catalog.merge_seed(self)
        _log.info("Database ready at %s (schema v%s)", self.path, CURRENT_SCHEMA_VERSION)

    def _migrate(self) -> None:
        """Apply forward-compatible schema tweaks to an existing database.

        ``executescript`` only creates *missing* tables; a column added to an
        existing table needs an explicit guarded ``ALTER`` here. v1 has no
        migrations yet — the hook exists so v2+ follows the proven pattern:
        guarded ALTERs first, then a ``_migrate_vN`` that bumps the stored
        version exactly once (see the sister app for worked examples).
        Views are dropped/recreated by schema.sql design: when a view's SELECT
        changes in a future version, add a ``DROP VIEW IF EXISTS`` step here
        BEFORE executescript recreates it (CREATE VIEW IF NOT EXISTS alone
        would keep the stale definition).
        """

    def wipe_all_data(self) -> None:
        """Delete all rows from every user-data table in one transaction.

        Single source of truth for the "delete all data" reset (WIPE_TABLES):
        clearing them together avoids the class of bug where a newly added
        table is forgotten and leaves orphaned rows behind. User catalog
        entries are removed too; the seed part is left intact (it ships with
        the app and reappears on every start anyway).
        """
        for table in WIPE_TABLES:
            self.conn.execute(f"DELETE FROM {table}")
        self.conn.execute("DELETE FROM catalog_items WHERE quelle = 'user'")
        self.conn.commit()

    # -- low-level helpers --------------------------------------------------
    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur

    def insert(self, table: str, params: dict[str, Any]) -> int:
        """Parameterised INSERT. Column names come from model.to_params()."""
        cols = list(params.keys())
        placeholders = ", ".join("?" for _ in cols)
        col_sql = ", ".join(cols)
        sql = f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders})"
        cur = self.conn.execute(sql, [params[c] for c in cols])
        self.conn.commit()
        return int(cur.lastrowid)

    def update(self, table: str, row_id: int, params: dict[str, Any]) -> None:
        cols = list(params.keys())
        assignments = ", ".join(f"{c} = ?" for c in cols)
        values = [params[c] for c in cols]
        # Bump updated_at where the column exists.
        touch = ", updated_at = datetime('now')" if self._has_column(table, "updated_at") else ""
        sql = f"UPDATE {table} SET {assignments}{touch} WHERE id = ?"
        self.conn.execute(sql, values + [row_id])
        self.conn.commit()

    def delete(self, table: str, row_id: int) -> None:
        self.conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
        self.conn.commit()

    def _has_column(self, table: str, column: str) -> bool:
        cols = self._column_cache.get(table)
        if cols is None:
            rows = self.conn.execute(f"PRAGMA table_info({table})").fetchall()
            cols = {r["name"] for r in rows}
            self._column_cache[table] = cols
        return column in cols

    def executemany(self, sql: str, seq: Iterable[Sequence[Any]]) -> None:
        self.conn.executemany(sql, seq)
        self.conn.commit()

    def close(self) -> None:
        try:
            self.conn.close()
        except sqlite3.Error:
            pass
