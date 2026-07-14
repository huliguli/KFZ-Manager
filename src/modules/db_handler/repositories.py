"""Repositories: typed CRUD + aggregate queries over the database.

Each repository returns/accepts the dataclasses from ``modules.models`` so the
UI never touches SQL or raw rows. All queries are parameterised.
"""

from __future__ import annotations

from modules.db_handler.database import Database
from modules.models import (
    Appointment,
    Attachment,
    CareRule,
    CatalogItem,
    Cost,
    LogbookEntry,
    TankEntry,
    Vehicle,
)


class VehicleRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def list(self, only_active: bool = True) -> list[Vehicle]:
        sql = "SELECT * FROM vehicles"
        if only_active:
            sql += " WHERE active = 1"
        sql += " ORDER BY name COLLATE NOCASE"
        return [Vehicle.from_row(r) for r in self.db.query(sql)]

    def get(self, row_id: int) -> Vehicle | None:
        row = self.db.query_one("SELECT * FROM vehicles WHERE id = ?", (row_id,))
        return Vehicle.from_row(row) if row else None

    def add(self, item: Vehicle) -> int:
        return self.db.insert("vehicles", item.to_params())

    def update(self, item: Vehicle) -> None:
        if item.id is None:
            raise ValueError("Fahrzeug ohne id kann nicht aktualisiert werden.")
        self.db.update("vehicles", item.id, item.to_params())

    def delete(self, row_id: int) -> None:
        # ON DELETE CASCADE removes tank/cost/rule/logbook/attachment rows;
        # the attachment FILES are removed by the caller (attachments module).
        self.db.delete("vehicles", row_id)

    def count(self) -> int:
        row = self.db.query_one("SELECT COUNT(*) AS n FROM vehicles WHERE active = 1")
        return int(row["n"]) if row else 0


class TankRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def list(self, vehicle_id: int) -> list[TankEntry]:
        rows = self.db.query(
            "SELECT * FROM tank_entries WHERE vehicle_id = ? "
            "ORDER BY date DESC, odo_km DESC, id DESC", (vehicle_id,))
        return [TankEntry.from_row(r) for r in rows]

    def list_chronological(self, vehicle_id: int) -> list[TankEntry]:
        rows = self.db.query(
            "SELECT * FROM tank_entries WHERE vehicle_id = ? "
            "ORDER BY date ASC, odo_km ASC, id ASC", (vehicle_id,))
        return [TankEntry.from_row(r) for r in rows]

    def get(self, row_id: int) -> TankEntry | None:
        row = self.db.query_one("SELECT * FROM tank_entries WHERE id = ?", (row_id,))
        return TankEntry.from_row(row) if row else None

    def add(self, item: TankEntry) -> int:
        return self.db.insert("tank_entries", item.to_params())

    def update(self, item: TankEntry) -> None:
        if item.id is None:
            raise ValueError("Tankeintrag ohne id kann nicht aktualisiert werden.")
        self.db.update("tank_entries", item.id, item.to_params())

    def delete(self, row_id: int) -> None:
        self.db.delete("tank_entries", row_id)


class CostRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def list_for_month(self, vehicle_id: int, year: int, month: int) -> list[Cost]:
        prefix = f"{year:04d}-{month:02d}"
        rows = self.db.query(
            "SELECT * FROM costs WHERE vehicle_id = ? AND date LIKE ? "
            "ORDER BY date DESC, id DESC", (vehicle_id, prefix + "-%"))
        return [Cost.from_row(r) for r in rows]

    def list(self, vehicle_id: int) -> list[Cost]:
        rows = self.db.query(
            "SELECT * FROM costs WHERE vehicle_id = ? ORDER BY date DESC, id DESC",
            (vehicle_id,))
        return [Cost.from_row(r) for r in rows]

    def get(self, row_id: int) -> Cost | None:
        row = self.db.query_one("SELECT * FROM costs WHERE id = ?", (row_id,))
        return Cost.from_row(row) if row else None

    def add(self, item: Cost) -> int:
        return self.db.insert("costs", item.to_params())

    def update(self, item: Cost) -> None:
        if item.id is None:
            raise ValueError("Kosteneintrag ohne id kann nicht aktualisiert werden.")
        self.db.update("costs", item.id, item.to_params())

    def delete(self, row_id: int) -> None:
        self.db.delete("costs", row_id)

    def month_totals(self, vehicle_id: int, year: int, month: int) -> dict[str, int]:
        """Sum per category for one month (integer cents)."""
        prefix = f"{year:04d}-{month:02d}"
        rows = self.db.query(
            "SELECT kategorie, COALESCE(SUM(betrag_cent), 0) AS total FROM costs "
            "WHERE vehicle_id = ? AND date LIKE ? GROUP BY kategorie",
            (vehicle_id, prefix + "-%"))
        return {r["kategorie"]: int(r["total"]) for r in rows}

    def month_total_all(self, vehicle_id: int, year: int, month: int) -> int:
        prefix = f"{year:04d}-{month:02d}"
        row = self.db.query_one(
            "SELECT COALESCE(SUM(betrag_cent), 0) AS total FROM costs "
            "WHERE vehicle_id = ? AND date LIKE ?", (vehicle_id, prefix + "-%"))
        return int(row["total"]) if row else 0


class AppointmentRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def list(self, vehicle_id: int, include_done: bool = False) -> list[Appointment]:
        sql = "SELECT * FROM appointments WHERE vehicle_id = ?"
        if not include_done:
            sql += " AND erledigt = 0"
        # NULL due dates sort last so the next real deadline is on top.
        sql += " ORDER BY erledigt, COALESCE(faellig_datum, '9999-12-31'), id"
        return [Appointment.from_row(r) for r in self.db.query(sql, (vehicle_id,))]

    def list_open_all_vehicles(self) -> list[Appointment]:
        rows = self.db.query(
            "SELECT * FROM appointments WHERE erledigt = 0 "
            "ORDER BY COALESCE(faellig_datum, '9999-12-31')")
        return [Appointment.from_row(r) for r in rows]

    def get(self, row_id: int) -> Appointment | None:
        row = self.db.query_one("SELECT * FROM appointments WHERE id = ?", (row_id,))
        return Appointment.from_row(row) if row else None

    def add(self, item: Appointment) -> int:
        return self.db.insert("appointments", item.to_params())

    def update(self, item: Appointment) -> None:
        if item.id is None:
            raise ValueError("Termin ohne id kann nicht aktualisiert werden.")
        self.db.update("appointments", item.id, item.to_params())

    def delete(self, row_id: int) -> None:
        self.db.delete("appointments", row_id)


class CareRuleRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def list(self, vehicle_id: int, only_active: bool = True) -> list[CareRule]:
        sql = "SELECT * FROM care_rules WHERE vehicle_id = ?"
        if only_active:
            sql += " AND aktiv = 1"
        sql += " ORDER BY name COLLATE NOCASE"
        return [CareRule.from_row(r) for r in self.db.query(sql, (vehicle_id,))]

    def list_active_all_vehicles(self) -> list[CareRule]:
        rows = self.db.query("SELECT * FROM care_rules WHERE aktiv = 1")
        return [CareRule.from_row(r) for r in rows]

    def get(self, row_id: int) -> CareRule | None:
        row = self.db.query_one("SELECT * FROM care_rules WHERE id = ?", (row_id,))
        return CareRule.from_row(row) if row else None

    def add(self, item: CareRule) -> int:
        return self.db.insert("care_rules", item.to_params())

    def update(self, item: CareRule) -> None:
        if item.id is None:
            raise ValueError("Pflege-Regel ohne id kann nicht aktualisiert werden.")
        self.db.update("care_rules", item.id, item.to_params())

    def delete(self, row_id: int) -> None:
        self.db.delete("care_rules", row_id)

    def has_catalog_rule(self, vehicle_id: int, catalog_id: str) -> bool:
        """True when the vehicle already adopted this catalog suggestion."""
        row = self.db.query_one(
            "SELECT 1 FROM care_rules WHERE vehicle_id = ? AND catalog_id = ? LIMIT 1",
            (vehicle_id, catalog_id))
        return row is not None


class LogbookRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def list(self, vehicle_id: int) -> list[LogbookEntry]:
        rows = self.db.query(
            "SELECT * FROM logbook_entries WHERE vehicle_id = ? "
            "ORDER BY date DESC, id DESC", (vehicle_id,))
        return [LogbookEntry.from_row(r) for r in rows]

    def get(self, row_id: int) -> LogbookEntry | None:
        row = self.db.query_one("SELECT * FROM logbook_entries WHERE id = ?", (row_id,))
        return LogbookEntry.from_row(row) if row else None

    def add(self, item: LogbookEntry) -> int:
        return self.db.insert("logbook_entries", item.to_params())

    def update(self, item: LogbookEntry) -> None:
        if item.id is None:
            raise ValueError("Scheckheft-Eintrag ohne id kann nicht aktualisiert werden.")
        self.db.update("logbook_entries", item.id, item.to_params())

    def delete(self, row_id: int) -> None:
        self.db.delete("logbook_entries", row_id)


class AttachmentRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def list_for_entry(self, entry_kind: str, entry_id: int) -> list[Attachment]:
        rows = self.db.query(
            "SELECT * FROM attachments WHERE entry_kind = ? AND entry_id = ? "
            "ORDER BY id", (entry_kind, entry_id))
        return [Attachment.from_row(r) for r in rows]

    def list_all(self) -> list[Attachment]:
        return [Attachment.from_row(r) for r in self.db.query("SELECT * FROM attachments")]

    def add(self, item: Attachment) -> int:
        return self.db.insert("attachments", item.to_params())

    def delete(self, row_id: int) -> None:
        self.db.delete("attachments", row_id)


class CatalogRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def list(self) -> list[CatalogItem]:
        rows = self.db.query(
            "SELECT * FROM catalog_items ORDER BY kategorie, name COLLATE NOCASE")
        return [CatalogItem.from_row(r) for r in rows]

    def get(self, item_id: str) -> CatalogItem | None:
        row = self.db.query_one("SELECT * FROM catalog_items WHERE id = ?", (item_id,))
        return CatalogItem.from_row(row) if row else None

    def add(self, item: CatalogItem) -> None:
        self.db.insert("catalog_items", item.to_params())

    def update(self, item: CatalogItem) -> None:
        params = item.to_params()
        params.pop("id")
        cols = ", ".join(f"{c} = ?" for c in params)
        self.db.execute(
            f"UPDATE catalog_items SET {cols}, updated_at = datetime('now') WHERE id = ?",
            list(params.values()) + [item.id])

    def delete(self, item_id: str) -> None:
        self.db.execute("DELETE FROM catalog_items WHERE id = ?", (item_id,))

    def hidden_ids(self, vehicle_id: int) -> set[str]:
        rows = self.db.query(
            "SELECT catalog_id FROM catalog_hidden WHERE vehicle_id = ?", (vehicle_id,))
        return {r["catalog_id"] for r in rows}

    def hide(self, vehicle_id: int, catalog_id: str) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO catalog_hidden (vehicle_id, catalog_id) VALUES (?, ?)",
            (vehicle_id, catalog_id))

    def unhide(self, vehicle_id: int, catalog_id: str) -> None:
        self.db.execute(
            "DELETE FROM catalog_hidden WHERE vehicle_id = ? AND catalog_id = ?",
            (vehicle_id, catalog_id))


class SettingsRepository:
    """Key/value settings that belong INSIDE the database (travel with backups)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, key: str, default: str | None = None) -> str | None:
        row = self.db.query_one("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else default

    def set(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
