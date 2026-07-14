"""Bundled catalog seed: content sanity + strictly additive merge."""

import json

from app_meta import catalog_seed_path
from modules import catalog
from modules.db_handler.database import Database
from modules.models import CatalogItem, Vehicle


def test_seed_file_is_valid_and_substantial():
    items = catalog.load_seed()
    assert len(items) >= 30, "Katalog muss mindestens ~30 Einträge liefern"
    ids = [i["id"] for i in items]
    assert len(ids) == len(set(ids)), "Katalog-IDs müssen eindeutig sein"
    for item in items:
        assert item["id"].startswith("seed-")
        assert item["name"]
        # Every entry needs at least one interval OR is purely advisory — the
        # spec wants adoptable rules, so require an interval.
        assert item.get("intervall_km") or item.get("intervall_monate"), item["id"]
        # No invented pricing/order data (classic hallucination trap).
        text = json.dumps(item, ensure_ascii=False)
        assert "€" not in (item.get("produkt_beispiel") or "")
        assert "Art.-Nr" not in text and "Artikelnummer" not in text


def test_seed_covers_ev_and_hybrid():
    items = catalog.load_seed()
    ev = [i for i in items if "elektro" in (i.get("bedingungen") or {}).get("kraftstoff", [])]
    hybrid = [i for i in items
              if "hev" in (i.get("bedingungen") or {}).get("kraftstoff", [])
              or "phev" in (i.get("bedingungen") or {}).get("kraftstoff", [])]
    assert len(ev) >= 4, "dedizierte E-Auto-Pflege gefordert"
    assert len(hybrid) >= 2, "Hybrid-Einträge gefordert"


def test_seed_conditions_only_use_known_keys():
    # Every bundled condition must be understood by THIS app version —
    # otherwise the matcher suppresses the item (fail closed) and the seed
    # entry would be dead on arrival.
    known = catalog._KNOWN_CONDITIONS
    for item in catalog.load_seed():
        for key in (item.get("bedingungen") or {}):
            assert key in known, f"{item['id']}: unbekannte Bedingung {key}"


def test_seed_items_reachable_by_some_profile():
    """Each seed item must match at least one plausible vehicle profile."""
    profiles = [
        Vehicle(name="Benziner DI", kraftstoff="benzin", direkteinspritzung=True,
                partikelfilter="opf", aufladung="turbo", getriebe="dsg",
                fahrprofil="kurzstrecke", km_stand=150_000,
                erstzulassung="2010-01-01", motorbauform="r4"),
        Vehicle(name="Benziner Sauger", kraftstoff="benzin", direkteinspritzung=False,
                partikelfilter="keiner", aufladung="sauger", getriebe="wandler",
                fahrprofil="mix", km_stand=150_000, erstzulassung="2008-01-01",
                motorbauform="v6"),
        Vehicle(name="Diesel", kraftstoff="diesel", direkteinspritzung=True,
                partikelfilter="dpf", aufladung="turbo", getriebe="manuell",
                fahrprofil="kurzstrecke", km_stand=150_000,
                erstzulassung="2012-01-01", motorbauform="r4"),
        Vehicle(name="EV", kraftstoff="elektro", motorbauform="emotor",
                getriebe="cvt", fahrprofil="mix", km_stand=60_000,
                erstzulassung="2021-01-01"),
        Vehicle(name="PHEV", kraftstoff="phev", direkteinspritzung=True,
                partikelfilter="opf", aufladung="turbo", getriebe="dsg",
                fahrprofil="kurzstrecke", km_stand=120_000,
                erstzulassung="2015-01-01", motorbauform="r4"),
        Vehicle(name="HEV", kraftstoff="hev", direkteinspritzung=True,
                partikelfilter="opf", aufladung="sauger", getriebe="cvt",
                fahrprofil="kurzstrecke", km_stand=120_000,
                erstzulassung="2015-01-01", motorbauform="r4"),
        Vehicle(name="LPG", kraftstoff="lpg", direkteinspritzung=False,
                partikelfilter="keiner", aufladung="sauger", getriebe="manuell",
                fahrprofil="mix", km_stand=180_000, erstzulassung="2009-01-01",
                motorbauform="r4"),
        Vehicle(name="Wankel", kraftstoff="benzin", direkteinspritzung=False,
                partikelfilter="keiner", aufladung="sauger", getriebe="manuell",
                fahrprofil="mix", km_stand=90_000, erstzulassung="2005-01-01",
                motorbauform="wankel"),
    ]
    for raw in catalog.load_seed():
        item = CatalogItem(id=raw["id"], name=raw["name"],
                           bedingungen=raw.get("bedingungen") or {})
        assert any(catalog.matches(item, p, km_now=p.km_stand) for p in profiles), \
            f"{item.id} passt auf kein Testprofil"


# --- merge behaviour ------------------------------------------------------------
def test_merge_is_additive_and_never_overwrites(tmp_path):
    db = Database(tmp_path / "t.db")  # initial merge ran here
    try:
        # User edits a seed entry...
        db.execute("UPDATE catalog_items SET name = 'MEINS' WHERE id = 'seed-wischerblaetter'")
        # ...creates an own entry and hides one per vehicle.
        db.execute("INSERT INTO catalog_items (id, name, quelle) VALUES ('user-1', 'Eigenes', 'user')")
        db.execute("INSERT INTO vehicles (name) VALUES ('Auto')")
        db.execute("INSERT INTO catalog_hidden (vehicle_id, catalog_id) VALUES (1, 'seed-felgen')")

        # A seed update re-runs the merge (as every app start does).
        inserted = __import__("modules.catalog", fromlist=["merge_seed"]).merge_seed(db)
        assert inserted == 0  # nothing new -> nothing touched

        row = db.query_one("SELECT name FROM catalog_items WHERE id = 'seed-wischerblaetter'")
        assert row["name"] == "MEINS", "Seed-Merge darf Nutzeränderungen nie überschreiben"
        assert db.query_one("SELECT 1 FROM catalog_items WHERE id = 'user-1'") is not None
        assert db.query_one(
            "SELECT 1 FROM catalog_hidden WHERE vehicle_id = 1 AND catalog_id = 'seed-felgen'"
        ) is not None
    finally:
        db.close()


def test_merge_inserts_new_seed_ids(tmp_path):
    db = Database(tmp_path / "t.db")
    try:
        seed = {"items": [{"id": "seed-neu-999", "name": "Neu", "kategorie": "Allgemein",
                           "intervall_monate": 6}]}
        extra = tmp_path / "extra_seed.json"
        extra.write_text(json.dumps(seed), encoding="utf-8")
        from modules.catalog import merge_seed
        assert merge_seed(db, extra) == 1
        assert merge_seed(db, extra) == 0  # idempotent
        row = db.query_one("SELECT quelle FROM catalog_items WHERE id = 'seed-neu-999'")
        assert row["quelle"] == "seed"
    finally:
        db.close()


def test_broken_seed_never_crashes(tmp_path):
    from modules.catalog import load_seed, merge_seed
    broken = tmp_path / "broken.json"
    broken.write_text("{kaputt", encoding="utf-8")
    assert load_seed(broken) == []
    db = Database(tmp_path / "t.db")
    try:
        assert merge_seed(db, broken) == 0
    finally:
        db.close()
