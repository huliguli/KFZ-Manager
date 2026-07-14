"""Pytest setup: make ``src`` importable and isolate all on-disk state.

Every test runs with APPDATA redirected to its own temp folder, so the data
dir, the attachment store, the family folder and the config can never touch
the real user profile (app_meta honours APPDATA on every OS exactly for this).
"""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(autouse=True)
def _isolated_appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    yield
