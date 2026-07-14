"""Database initialisation, migrations, guards and repositories."""

import sqlite3

import pytest

from modules.db_handler.database import (
    CURRENT_SCHEMA_VERSION,
    INTEROP_VERSION,
    Database,
    DatabaseCorruptError,
    SchemaTooNewError,
)
from modules.db_handler.repositories import (
    AppointmentRepository,
    CareRuleRepository,
    CostRepository,
    TankRepository,
    VehicleRepository,
)
from modules.models import Appointment, CareRule, Cost, TankEntry, Vehicle


def test_fresh_database_gets_current_versions(tmp_path):
    db = Database(tmp_path / "t.db")
    try:
        row = db.query_one("SELECT version FROM schema_version")
        assert row["version"] == CURRENT_SCHEMA_VERSION
        irow = db.query_one("SELECT interop_version FROM interop_meta")
        assert irow["interop_version"] == INTEROP_VERSION
        # Interop views exist and are queryable on an empty DB.
        for view in ("interop_fahrzeuge", "interop_kosten_monat", "interop_termine"):
            assert db.query(f"SELECT * FROM {view}") == []
    finally:
        db.close()


def test_newer_schema_is_refused(tmp_path):
    path = tmp_path / "t.db"
    db = Database(path)
    db.execute("UPDATE schema_version SET version = ?", (CURRENT_SCHEMA_VERSION + 1,))
    db.close()
    with pytest.raises(SchemaTooNewError):
        Database(path)


def test_corrupt_file_is_refused_and_not_locked(tmp_path):
    path = tmp_path / "t.db"
    path.write_bytes(b"das ist keine sqlite-datei" * 100)
    with pytest.raises(DatabaseCorruptError):
        Database(path)
    # The handle must be released so recovery can rename the file (Windows!).
    path.rename(tmp_path / "aside.db")


def test_reopen_existing_database_is_idempotent(tmp_path):
    path = tmp_path / "t.db"
    db = Database(path)
    VehicleRepository(db).add(Vehicle(name="Golf"))
    db.close()
    db2 = Database(path)  # second start: executescript + merge again
    try:
        assert VehicleRepository(db2).count() == 1
    finally:
        db2.close()


def test_wipe_all_data_clears_user_rows_keeps_seed(tmp_path):
    db = Database(tmp_path / "t.db")
    try:
        vehicles = VehicleRepository(db)
        vid = vehicles.add(Vehicle(name="Golf"))
        TankRepository(db).add(TankEntry(vehicle_id=vid, date="2026-01-01",
                                         odo_km=1000, menge_ml=40_000))
        CostRepository(db).add(Cost(vehicle_id=vid, date="2026-01-01", betrag_cent=100))
        db.execute("INSERT INTO catalog_items (id, name, quelle) VALUES ('user-1', 'x', 'user')")
        db.wipe_all_data()
        assert vehicles.count() == 0
        assert db.query("SELECT * FROM tank_entries") == []
        assert db.query("SELECT * FROM costs") == []
        assert db.query_one("SELECT 1 FROM catalog_items WHERE quelle = 'user'") is None
        # The bundled seed survives (it ships with the app anyway).
        assert db.query_one("SELECT 1 FROM catalog_items WHERE quelle = 'seed'") is not None
    finally:
        db.close()


def test_vehicle_cascade_delete(tmp_path):
    db = Database(tmp_path / "t.db")
    try:
        vid = VehicleRepository(db).add(Vehicle(name="Golf"))
        TankRepository(db).add(TankEntry(vehicle_id=vid, date="2026-01-01",
                                         odo_km=1000, menge_ml=40_000))
        AppointmentRepository(db).add(Appointment(vehicle_id=vid, typ="TÜV/HU",
                                                  faellig_datum="2026-09-01"))
        CareRuleRepository(db).add(CareRule(vehicle_id=vid, name="Öl",
                                            intervall_monate=12))
        VehicleRepository(db).delete(vid)
        assert db.query("SELECT * FROM tank_entries") == []
        assert db.query("SELECT * FROM appointments") == []
        assert db.query("SELECT * FROM care_rules") == []
    finally:
        db.close()


def test_interop_views_content(tmp_path):
    db = Database(tmp_path / "t.db")
    try:
        vid = VehicleRepository(db).add(Vehicle(name="Golf", kraftstoff="diesel"))
        costs = CostRepository(db)
        costs.add(Cost(vehicle_id=vid, date="2026-07-01", kategorie="Werkstatt",
                       betrag_cent=5000))
        costs.add(Cost(vehicle_id=vid, date="2026-07-20", kategorie="Werkstatt",
                       betrag_cent=2500))
        costs.add(Cost(vehicle_id=vid, date="2026-06-15", kategorie="Pflege",
                       betrag_cent=999))
        AppointmentRepository(db).add(Appointment(vehicle_id=vid, typ="TÜV/HU",
                                                  faellig_datum="2026-09-01"))

        rows = db.query("SELECT * FROM interop_fahrzeuge")
        assert len(rows) == 1 and rows[0]["antrieb"] == "diesel"

        month = {(r["jahr"], r["monat"], r["kategorie"]): r["betrag_cent"]
                 for r in db.query("SELECT * FROM interop_kosten_monat")}
        assert month[(2026, 7, "Werkstatt")] == 7500
        assert month[(2026, 6, "Pflege")] == 999

        termine = db.query("SELECT * FROM interop_termine")
        assert len(termine) == 1 and termine[0]["typ"] == "TÜV/HU"
    finally:
        db.close()


def test_month_totals(tmp_path):
    db = Database(tmp_path / "t.db")
    try:
        vid = VehicleRepository(db).add(Vehicle(name="Golf"))
        costs = CostRepository(db)
        costs.add(Cost(vehicle_id=vid, date="2026-07-01", kategorie="Steuer",
                       betrag_cent=1500))
        costs.add(Cost(vehicle_id=vid, date="2026-07-31", kategorie="Steuer",
                       betrag_cent=500))
        costs.add(Cost(vehicle_id=vid, date="2026-08-01", kategorie="Steuer",
                       betrag_cent=99999))
        assert costs.month_totals(vid, 2026, 7) == {"Steuer": 2000}
        assert costs.month_total_all(vid, 2026, 7) == 2000
    finally:
        db.close()


def test_updated_at_bumped_on_update(tmp_path):
    db = Database(tmp_path / "t.db")
    try:
        repo = VehicleRepository(db)
        vid = repo.add(Vehicle(name="Golf"))
        db.conn.execute("UPDATE vehicles SET updated_at = '2000-01-01 00:00:00'")
        db.conn.commit()
        vehicle = repo.get(vid)
        vehicle.name = "Golf II"
        repo.update(vehicle)
        row = db.query_one("SELECT updated_at FROM vehicles WHERE id = ?", (vid,))
        assert row["updated_at"] != "2000-01-01 00:00:00"
    finally:
        db.close()
