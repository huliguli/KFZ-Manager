"""Hardened attachment storage for the digital Scheckheft.

Files (photos/PDFs) are COPIED into ``<data_dir>/attachments/<vehicle_id>/``;
the database stores paths relative to the data dir. Hardening against the
classic file-handling traps:

    * Generated filenames (``<uuid>.<ext>``) — the original name is kept only
      as display metadata, so no user-controlled path component ever touches
      the filesystem (no traversal, no reserved names, no Unicode tricks).
    * Extension whitelist (jpg/jpeg/png/webp/heic/pdf), checked case-insensitively
      against the ORIGINAL file before anything is copied.
    * Size limit (~25 MB per file), checked before the copy.
    * ``resolve_path`` refuses any stored path that escapes the attachments
      root — a tampered database row cannot read or delete foreign files.
    * Deleting an entry deletes its files; an orphan sweep at startup removes
      files without a database row (e.g. after a crash mid-delete).
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from app_meta import attachments_dir, data_dir
from modules.logging_setup import get_logger
from modules.models import Attachment

_log = get_logger("attachments")

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "heic", "pdf"}
IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}  # thumbnail-capable (Qt built-ins)
MAX_FILE_BYTES = 25 * 1024 * 1024  # ~25 MB per file

FILE_FILTER = "Fotos & PDFs (*.jpg *.jpeg *.png *.webp *.heic *.pdf)"


class AttachmentError(ValueError):
    """Rejected attachment; message is user-presentable German."""


def _extension(name: str) -> str:
    return Path(name).suffix.lstrip(".").lower()


def validate_source(path: Path) -> None:
    """Whitelist + size check on the source file. Raises AttachmentError."""
    if not path.is_file():
        raise AttachmentError("Die Datei existiert nicht oder ist kein normaler Dateityp.")
    ext = _extension(path.name)
    if ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise AttachmentError(
            f"Dateityp „.{ext}“ wird nicht unterstützt. Erlaubt sind: {allowed}.")
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise AttachmentError(
            f"Die Datei ist zu groß ({size / 1_000_000:.1f} MB). "
            f"Maximal erlaubt sind {MAX_FILE_BYTES // (1024 * 1024)} MB.")
    if size == 0:
        raise AttachmentError("Die Datei ist leer.")


def store_file(source: Path | str, vehicle_id: int, entry_kind: str,
               entry_id: int) -> Attachment:
    """Copy a file into the attachment store and return its (unsaved) model.

    The caller persists the returned Attachment via the repository; on a
    later DB failure the copied file is picked up by the orphan sweep.
    """
    source = Path(source)
    validate_source(source)
    ext = _extension(source.name)
    # Generated name: no user-controlled bytes reach the filesystem.
    fname = f"{uuid.uuid4().hex}.{ext}"
    target_dir = attachments_dir() / str(int(vehicle_id))
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / fname
    shutil.copyfile(source, target)
    rel_path = str(target.relative_to(data_dir())).replace("\\", "/")
    _log.info("Anhang gespeichert: %s (%s)", rel_path, source.name)
    return Attachment(
        vehicle_id=vehicle_id, entry_kind=entry_kind, entry_id=entry_id,
        rel_path=rel_path, original_name=source.name,
        size_bytes=target.stat().st_size)


def resolve_path(rel_path: str) -> Path | None:
    """Absolute path for a stored relative path — confined to the store.

    Returns None when the stored value escapes the attachments root (defense
    against a manipulated database) or the file is gone.
    """
    root = attachments_dir().resolve()
    try:
        candidate = (data_dir() / rel_path).resolve()
    except OSError:
        return None
    if not candidate.is_relative_to(root):
        _log.warning("Anhang-Pfad außerhalb des Speicherordners verweigert: %s", rel_path)
        return None
    return candidate if candidate.is_file() else None


def delete_file(rel_path: str) -> None:
    """Best-effort removal of a stored attachment file."""
    path = resolve_path(rel_path)
    if path is None:
        return
    try:
        path.unlink()
    except OSError as exc:
        _log.warning("Anhang-Datei konnte nicht gelöscht werden (%s): %s", rel_path, exc)


def delete_for_entry(repo, entry_kind: str, entry_id: int) -> None:
    """Delete all attachments (files + rows) of one logbook/cost entry."""
    for att in repo.list_for_entry(entry_kind, entry_id):
        delete_file(att.rel_path)
        if att.id is not None:
            repo.delete(att.id)


def orphan_sweep(repo) -> int:
    """Remove files in the attachment store that have no database row.

    Runs at startup (never raises): after a crash between file copy and DB
    insert — or DB delete and file delete — the store and the table can
    drift; the sweep restores the invariant "every file has a row".
    """
    removed = 0
    try:
        known = {att.rel_path for att in repo.list_all()}
        root = attachments_dir()
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            rel = str(path.relative_to(data_dir())).replace("\\", "/")
            if rel not in known:
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass
        # Prune now-empty vehicle folders (cosmetic).
        for folder in sorted(root.glob("*")):
            if folder.is_dir():
                try:
                    folder.rmdir()  # only succeeds when empty
                except OSError:
                    pass
    except Exception as exc:  # noqa: BLE001 - a sweep failure must never block startup
        _log.warning("Anhang-Aufräumlauf fehlgeschlagen: %s", exc)
    if removed:
        _log.info("Anhang-Aufräumlauf: %d verwaiste Datei(en) entfernt.", removed)
    return removed
