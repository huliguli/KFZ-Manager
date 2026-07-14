"""Pfad-Logik von app_meta (APPDATA-Umleitung, Familienordner)."""

import app_meta


def test_data_dirs_under_redirected_appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert app_meta.data_dir() == tmp_path / "KFZManager"
    assert app_meta.database_path().name == "kfz.db"
    assert app_meta.family_dir() == tmp_path / "AppFamilie"
    assert app_meta.attachments_dir().is_dir()


def test_version_is_semver():
    parts = app_meta.APP_VERSION.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts)


def test_bundled_resources_exist():
    assert app_meta.schema_path().is_file()
    assert app_meta.catalog_seed_path().is_file()
