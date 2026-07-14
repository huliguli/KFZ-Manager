"""Anhang-Härtung: Whitelist, Größenlimit, Traversal-Schutz, Orphan-Sweep."""

import pytest

from app_meta import attachments_dir, data_dir
from modules import attachments
from modules.db_handler.database import Database
from modules.db_handler.repositories import AttachmentRepository, VehicleRepository
from modules.models import Vehicle


def _src(tmp_path, name: str, size: int = 128) -> str:
    f = tmp_path / name
    f.write_bytes(b"x" * size)
    return str(f)


def test_extension_whitelist(tmp_path):
    for bad in ("virus.exe", "script.js", "archiv.zip", "doppel.pdf.exe", "ohne_endung"):
        with pytest.raises(attachments.AttachmentError):
            attachments.validate_source(tmp_path / _src(tmp_path, bad))
    # Allowed types pass.
    for good in ("foto.JPG", "scan.pdf", "bild.webp", "handy.heic", "shot.png"):
        attachments.validate_source(tmp_path / _src(tmp_path, good))


def test_size_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(attachments, "MAX_FILE_BYTES", 1024)
    with pytest.raises(attachments.AttachmentError):
        attachments.validate_source(tmp_path / _src(tmp_path, "gross.jpg", 2048))
    with pytest.raises(attachments.AttachmentError):
        attachments.validate_source(tmp_path / _src(tmp_path, "leer.jpg", 0))


def test_store_generates_safe_names(tmp_path):
    # Hostile original name: no path component may reach the filesystem.
    evil = tmp_path / "..%2F..%2Fboese.pdf"
    evil.write_bytes(b"pdf")
    att = attachments.store_file(evil, vehicle_id=7, entry_kind="logbook", entry_id=1)
    assert att.rel_path.startswith("attachments/7/")
    stored = attachments.resolve_path(att.rel_path)
    assert stored is not None and stored.is_file()
    assert stored.parent == attachments_dir() / "7"
    # The generated filename is uuid-hex + whitelisted extension only.
    assert stored.suffix == ".pdf" and len(stored.stem) == 32


def test_resolve_path_refuses_escape(tmp_path):
    secret = data_dir() / "geheim.txt"
    secret.write_text("x", encoding="utf-8")
    assert attachments.resolve_path("../geheim.txt") is None
    assert attachments.resolve_path("attachments/../geheim.txt") is None
    assert attachments.resolve_path("attachments/../../windows/win.ini") is None


def test_orphan_sweep_and_entry_delete(tmp_path):
    db = Database(tmp_path / "t.db")
    try:
        vid = VehicleRepository(db).add(Vehicle(name="Golf"))
        repo = AttachmentRepository(db)
        att = attachments.store_file(_src(tmp_path, "beleg.jpg"), vid, "logbook", 1)
        repo.add(att)

        # An orphaned file (no DB row) is removed by the sweep...
        orphan = attachments_dir() / str(vid) / "verwaist.jpg"
        orphan.write_bytes(b"x")
        removed = attachments.orphan_sweep(repo)
        assert removed == 1
        assert not orphan.exists()
        # ...while the tracked file survives.
        assert attachments.resolve_path(att.rel_path) is not None

        # Deleting the entry removes file AND row.
        attachments.delete_for_entry(repo, "logbook", 1)
        assert attachments.resolve_path(att.rel_path) is None
        assert repo.list_for_entry("logbook", 1) == []
    finally:
        db.close()
