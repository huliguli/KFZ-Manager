"""Updater: Versionsvergleich, Host-Allowlist, Asset-Auswahl, Prüfsummen."""

import hashlib

from modules.updater import updater


def test_parse_version_and_is_newer():
    assert updater.parse_version("v1.2.3") == (1, 2, 3)
    assert updater.parse_version("1.10") > updater.parse_version("1.9")
    assert updater.is_newer("v1.0.1", "1.0.0")
    assert not updater.is_newer("1.0.0", "1.0.0")
    assert not updater.is_newer("0.9.9", "1.0.0")
    assert updater.parse_version("unsinn") == (0,)


def test_https_github_allowlist():
    assert updater._https_github("https://github.com/x/y/releases/download/v1/a.exe")
    assert updater._https_github("https://objects.githubusercontent.com/x")
    assert not updater._https_github("http://github.com/x")          # kein TLS
    assert not updater._https_github("https://evilgithub.com/x")     # fremder Host
    assert not updater._https_github("https://github.com.evil.de/x")  # Suffix-Trick


def test_select_asset_matches_checksum_by_name():
    assets = [
        {"name": "KFZManager-macOS.dmg", "browser_download_url": "https://github.com/dmg"},
        {"name": "KFZManager-macOS.dmg.sha256", "browser_download_url": "https://github.com/dmg.sha"},
        {"name": "KFZManager-Setup.exe", "browser_download_url": "https://github.com/exe"},
        {"name": "KFZManager-Setup.exe.sha256", "browser_download_url": "https://github.com/exe.sha"},
    ]
    url, sha = updater._select_asset_and_checksum(assets, ".exe")
    assert url.endswith("/exe") and sha.endswith("/exe.sha")
    url, sha = updater._select_asset_and_checksum(assets, ".dmg")
    assert url.endswith("/dmg") and sha.endswith("/dmg.sha")


def test_verify_download(tmp_path):
    f = tmp_path / "setup.exe"
    f.write_bytes(b"INSTALLER")
    good = hashlib.sha256(b"INSTALLER").hexdigest()
    assert updater.verify_download(str(f), good)
    assert updater.verify_download(str(f), good.upper())
    assert not updater.verify_download(str(f), "0" * 64)
    # No checksum available -> accepted here (Authenticode pin is the anchor).
    assert updater.verify_download(str(f), None)


def test_parse_sha256_extracts_digest():
    digest = "a" * 64
    assert updater._parse_sha256(f"{digest}  KFZManager-Setup.exe") == digest
    assert updater._parse_sha256("kein hash") is None


def test_trusted_thumbprints_pinned():
    # The release workflow verifies the built installer against this pin;
    # an empty tuple would silently break every future auto-update.
    assert updater._TRUSTED_CERT_THUMBPRINTS
    for tp in updater._TRUSTED_CERT_THUMBPRINTS:
        assert len(tp) == 40 and tp == tp.upper()
