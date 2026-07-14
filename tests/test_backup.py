"""Backup/Restore: ZIP mit Datenbank UND Anhängen, Rotation, Fehlerpfade."""

import zipfile
from datetime import datetime

import pytest

from app_meta import attachments_dir
from modules import attachments, backup
from modules.db_handler.database import Database
from modules.db_handler.repositories import AttachmentRepository, VehicleRepository
from modules.models import Vehicle


def _db_with_attachment(tmp_path):
    db = Database(tmp_path / "t.db")
    vid = VehicleRepository(db).add(Vehicle(name="Golf"))
    src = tmp_path / "beleg.jpg"
    src.write_bytes(b"JPEGDATA")
    att = attachments.store_file(src, vid, "logbook", 1)
    AttachmentRepository(db).add(att)
    return db, vid, att


def test_backup_contains_db_and_attachments(tmp_path):
    db, _vid, att = _db_with_attachment(tmp_path)
    try:
        target = backup.create_backup(db.conn, directory=tmp_path / "backups")
        with zipfile.ZipFile(target) as zf:
            names = zf.namelist()
        assert backup.DB_MEMBER in names
        member = backup.ATTACH_PREFIX + att.rel_path.split("attachments/", 1)[1]
        assert member in names
    finally:
        db.close()


def test_restore_roundtrip_including_attachments(tmp_path):
    db, vid, att = _db_with_attachment(tmp_path)
    try:
        snapshot = backup.create_backup(db.conn, directory=tmp_path / "backups")

        # Destroy state: drop the vehicle AND the attachment file.
        VehicleRepository(db).delete(vid)
        attachments.delete_file(att.rel_path)
        assert VehicleRepository(db).count() == 0
        assert attachments.resolve_path(att.rel_path) is None

        backup.restore_into_connection(db.conn, snapshot)
        db.reinitialise_after_restore()
        assert VehicleRepository(db).count() == 1
        restored = attachments.resolve_path(att.rel_path)
        assert restored is not None and restored.read_bytes() == b"JPEGDATA"
    finally:
        db.close()


def test_restore_replaces_foreign_attachment_files(tmp_path):
    db, _vid, _att = _db_with_attachment(tmp_path)
    try:
        snapshot = backup.create_backup(db.conn, directory=tmp_path / "backups")
        stray = attachments_dir() / "999" / "fremd.jpg"
        stray.parent.mkdir(parents=True, exist_ok=True)
        stray.write_bytes(b"x")
        backup.restore_into_connection(db.conn, snapshot)
        db.reinitialise_after_restore()
        assert not stray.exists(), "Restore muss den Anhang-Bestand ersetzen"
    finally:
        db.close()


def test_rotation_keeps_newest(tmp_path):
    db = Database(tmp_path / "t.db")
    try:
        directory = tmp_path / "backups"
        for i in range(backup.MAX_BACKUPS + 3):
            backup.create_backup(db.conn, directory=directory,
                                 now=datetime(2026, 1, 1, 12, 0, i))
        backups = backup.list_backups(directory)
        assert len(backups) == backup.MAX_BACKUPS
    finally:
        db.close()


def test_startup_backup_once_per_day(tmp_path):
    db = Database(tmp_path / "t.db")
    try:
        directory = tmp_path / "backups"
        first = backup.startup_backup(db.conn, directory)
        second = backup.startup_backup(db.conn, directory)
        assert first is not None and second is None
    finally:
        db.close()


def test_backup_schema_version_readable(tmp_path):
    db = Database(tmp_path / "t.db")
    try:
        target = backup.create_backup(db.conn, directory=tmp_path / "backups")
        from modules.db_handler.database import CURRENT_SCHEMA_VERSION
        assert backup.backup_schema_version(target) == CURRENT_SCHEMA_VERSION
    finally:
        db.close()


def test_corrupt_archive_raises_backuperror(tmp_path):
    db = Database(tmp_path / "t.db")
    try:
        bad = tmp_path / "kfz-20260101-120000-manuell.zip"
        bad.write_bytes(b"keine zip-datei")
        with pytest.raises(backup.BackupError):
            backup.restore_into_connection(db.conn, bad)
        with pytest.raises(backup.BackupError):
            backup.restore_into_connection(db.conn, tmp_path / "fehlt.zip")
    finally:
        db.close()


def test_zip_traversal_member_is_rejected(tmp_path):
    db = Database(tmp_path / "t.db")
    try:
        evil = tmp_path / "kfz-20260101-120000-manuell.zip"
        with zipfile.ZipFile(evil, "w") as zf:
            zf.writestr(backup.DB_MEMBER, b"x")  # invalid db, but traversal first
            zf.writestr("attachments/../../boese.txt", b"x")
        with pytest.raises(backup.BackupError):
            backup.restore_into_connection(db.conn, evil)
        assert not (tmp_path / "boese.txt").exists()
    finally:
        db.close()


def test_replace_database_file_recovers_corruption(tmp_path):
    path = tmp_path / "t.db"
    db = Database(path)
    VehicleRepository(db).add(Vehicle(name="Golf"))
    snapshot = backup.create_backup(db.conn, directory=tmp_path / "backups")
    db.close()

    path.write_bytes(b"kaputt" * 1000)  # simulate corruption
    aside = backup.replace_database_file(path, snapshot)
    assert aside.exists(), "beschädigte Datei wird beiseitegelegt, nie gelöscht"
    db2 = Database(path)
    try:
        assert VehicleRepository(db2).count() == 1
    finally:
        db2.close()
