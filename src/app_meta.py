"""Central application metadata and filesystem locations.

Single source of truth for the app name, version, GitHub repo and all
on-disk paths. Keeping this in one tiny module avoids hard-coded paths
scattered through the code base (a classic "runs only on my machine" trap)
and makes the PyInstaller build behave identically to a dev run.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_NAME = "KFZManager"
APP_DISPLAY_NAME = "KFZ-Manager"
GITHUB_REPO = "huliguli/KFZ-Manager"

# Name of the shared app-family folder next to the per-app data folders. Both
# sister apps (KFZ-Manager, HaushaltsManager) announce themselves there — see
# modules.interop and INTEROP.md for the contract.
FAMILY_DIR_NAME = "AppFamilie"

# Fallback version; the real value is read from the bundled version.json below.
_FALLBACK_VERSION = "1.0.0"


def is_frozen() -> bool:
    """True when running from a PyInstaller-built executable."""
    return getattr(sys, "frozen", False)


def resource_dir() -> Path:
    """Directory that holds bundled read-only resources.

    Under PyInstaller builds the payload lives next to the executable in
    ``_internal`` exposed as ``sys._MEIPASS``. During development it is the
    project root (the parent of ``src``).
    """
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    # src/app_meta.py -> project root is two levels up
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    """Absolute path to a bundled resource (works in dev and frozen builds)."""
    return resource_dir().joinpath(*parts)


def _read_bundled_version() -> str:
    """Read the version string from the bundled version.json."""
    for candidate in (resource_path("version.json"), resource_path("src", "version.json")):
        try:
            with open(candidate, "r", encoding="utf-8") as fh:
                return str(json.load(fh).get("version", _FALLBACK_VERSION))
        except (OSError, ValueError):
            continue
    return _FALLBACK_VERSION


APP_VERSION = _read_bundled_version()


def _data_base() -> Path:
    """Per-user base directory that holds the app data folder AND the family
    folder, per OS convention. ``APPDATA`` is honoured on ANY OS when set, so
    tests can redirect everything to a temp folder regardless of platform."""
    base = os.environ.get("APPDATA")
    if base:
        return Path(base)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    if sys.platform.startswith("linux"):
        xdg = os.environ.get("XDG_DATA_HOME")
        return Path(xdg) if xdg else Path.home() / ".local" / "share"
    return Path.home()  # unusual setups


def data_dir() -> Path:
    """Per-user writable data directory (identical database/config on every OS).

    The packaged app usually lives in a read-only location (Program Files, or a
    read-only mounted .app), so the database, config, attachments and logs live
    in the user profile instead:
        * Windows: ``%APPDATA%\\KFZManager``
        * macOS:   ``~/Library/Application Support/KFZManager``
        * Linux:   ``$XDG_DATA_HOME/KFZManager`` (or ``~/.local/share/...``)
    """
    base = _data_base()
    if base == Path.home():
        path = base / f".{APP_NAME.lower()}"  # unusual setups: hidden dir in $HOME
    else:
        path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def family_dir(create: bool = True) -> Path:
    """Shared app-family folder (``<data base>/AppFamilie``).

    Every family app writes its announcement file here on startup
    (``kfzmanager.json`` / ``haushaltsmanager.json``) so the sisters can find
    each other without any registry or fixed install paths.
    """
    path = _data_base() / FAMILY_DIR_NAME
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def database_path() -> Path:
    return data_dir() / "kfz.db"


def config_path() -> Path:
    return data_dir() / "config.json"


def logs_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def attachments_dir() -> Path:
    """Root folder for copied attachment files (see modules.attachments)."""
    path = data_dir() / "attachments"
    path.mkdir(parents=True, exist_ok=True)
    return path


def schema_path() -> Path:
    """Location of the bundled SQL schema."""
    return resource_path("src", "database", "schema.sql")


def catalog_seed_path() -> Path:
    """Location of the bundled recommendation-catalog seed (JSON)."""
    return resource_path("src", "database", "catalog_seed.json")


def app_icon_path() -> Path:
    """Location of the bundled application icon (.ico)."""
    return resource_path("assets", "app.ico")
