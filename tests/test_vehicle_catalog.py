"""Fahrzeug-Katalog: Merge, Kaskade, HSN/TSN — und die Motorcode-Invarianten.

Die wichtigsten Tests hier sind die des Vertrauensmodells: ein Katalog-
Vorschlag darf NIEMALS eine motorcode-spezifische Empfehlung auslösen. Nur
ein vom Nutzer bestätigter Code (``motorcode_herkunft == 'nutzer'``) zählt.
Grund: „A4 B8 1.8 TFSI 160 PS" ist zweideutig (CABB oder CDHB) — ein
geratener Code würde falsche Wartungshinweise erzeugen.
"""

import gzip
import json

import pytest

from modules import catalog, vehicle_catalog as vc
from modules.db_handler.database import CURRENT_SCHEMA_VERSION, Database
from modules.db_handler.repositories import VehicleRepository
from modules.models import CatalogItem, Vehicle

SEED = {
    "katalog_version": 1,
    "marken": [{"id": "audi", "name": "Audi",
                "quelle_url": "https://de.wikipedia.org/wiki/Audi",
                "quelle_abruf": "2026-07-14"}],
    "baureihen": [{"id": "audi-a4", "marke_id": "audi", "name": "A4",
                   "quelle_url": "https://de.wikipedia.org/wiki/Audi_A4"}],
    "generationen": [{"id": "audi-a4-b8", "baureihe_id": "audi-a4", "name": "B8",
                      "bj_von": 2007, "bj_bis": 2015,
                      "quelle_url": "https://de.wikipedia.org/wiki/Audi_A4_B8"}],
    "motorisierungen": [{
        "id": "audi-a4-b8-1-8-tfsi-160", "generation_id": "audi-a4-b8",
        "anzeigename": "1.8 TFSI (160 PS)", "bj_von": 2008, "bj_bis": 2015,
        "kraftstoff": "benzin", "motorbauform": "r4", "aufladung": "turbo",
        "direkteinspritzung": 1, "partikelfilter": "keiner",
        "hubraum_ccm": 1798, "leistung_ps": 160, "getriebe": None,
        "oel_viskositaet": None, "oel_freigabe": None,
        "quelle_url": "https://de.wikipedia.org/wiki/Audi_A4_B8",
        "quelle_zitat": "1.8 TFSI 1798 cm3 118 kW (160 PS)",
        "quelle_abruf": "2026-07-14"}],
    # Genau der mehrdeutige Fall: eine Motorisierung, ZWEI mögliche Codes.
    "motorcodes": [
        {"id": "vag-cabb", "code": "CABB", "motorfamilie": "EA888-GEN1",
         "einbaulage": "laengs", "bj_von": 2008, "bj_bis": 2011,
         "quelle_url": "https://example.org/cabb", "quelle_zitat": "CABB 1.8 TFSI"},
        {"id": "vag-cdhb", "code": "CDHB", "motorfamilie": "EA888-GEN2",
         "einbaulage": "laengs", "bj_von": 2011, "bj_bis": 2015,
         "quelle_url": "https://example.org/cdhb", "quelle_zitat": "CDHB 1.8 TFSI"},
    ],
    "motorisierung_motorcode": [
        ["audi-a4-b8-1-8-tfsi-160", "vag-cabb"],
        ["audi-a4-b8-1-8-tfsi-160", "vag-cdhb"],
    ],
}


@pytest.fixture()
def db(tmp_path):
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps(SEED), encoding="utf-8")
    database = Database(tmp_path / "t.db")
    vc.merge_seed(database, seed)
    yield database
    database.close()


# --- Schema/Migration -----------------------------------------------------------
def test_schema_is_v2_with_catalog_tables(db):
    assert db.query_one("SELECT version FROM schema_version")["version"] \
        == CURRENT_SCHEMA_VERSION == 2
    for table in ("katalog_marke", "katalog_baureihe", "katalog_generation",
                  "katalog_motorisierung", "katalog_motorcode",
                  "katalog_motorisierung_motorcode", "katalog_kba"):
        db.query(f"SELECT * FROM {table} LIMIT 1")  # wirft, wenn es fehlt


def test_v1_database_is_lifted_to_v2(tmp_path):
    """Eine v1-DB bekommt die neuen Spalten, ohne Nutzerdaten anzufassen."""
    path = tmp_path / "old.db"
    db = Database(path)
    vid = VehicleRepository(db).add(Vehicle(name="Golf", km_stand=123_456))
    # v1 simulieren: neue Spalten weg, Version zurück.
    for col in ("katalog_motorisierung_id", "motorcode", "motorcode_herkunft",
                "profil_dirty"):
        db.conn.execute(f"ALTER TABLE vehicles DROP COLUMN {col}")
    db.conn.execute("UPDATE schema_version SET version = 1")
    db.conn.commit()
    db.close()

    db2 = Database(path)
    try:
        assert db2.query_one("SELECT version FROM schema_version")["version"] == 2
        v = VehicleRepository(db2).get(vid)
        assert v.name == "Golf" and v.km_stand == 123_456   # unangetastet
        assert v.motorcode == "" and v.motorcode_herkunft is None
    finally:
        db2.close()


# --- Merge ------------------------------------------------------------------------
def test_merge_is_idempotent_and_fills_cascade(db):
    assert vc.marken(db) == [("audi", "Audi")]
    assert vc.baureihen(db, "audi") == [("audi-a4", "A4")]
    gens = vc.generationen(db, "audi-a4")
    assert gens[0][0] == "audi-a4-b8" and "2007" in gens[0][1]
    mots = vc.motorisierungen(db, "audi-a4-b8")
    assert len(mots) == 1
    assert mots[0].werte["hubraum_ccm"] == 1798
    assert mots[0].werte["kraftstoff"] == "benzin"


def test_merge_tombstones_removed_entries(tmp_path, db):
    """Entfallene IDs werden markiert, nicht gelöscht — sonst zerreißt ein
    Update die Referenz eines Bestandsfahrzeugs."""
    reduced = json.loads(json.dumps(SEED))
    reduced["motorisierungen"] = []
    seed2 = tmp_path / "seed2.json"
    seed2.write_text(json.dumps(reduced), encoding="utf-8")
    vc.merge_seed(db, seed2)
    assert vc.motorisierungen(db, "audi-a4-b8") == []      # nicht mehr wählbar
    row = db.query_one("SELECT deprecated FROM katalog_motorisierung WHERE id = ?",
                       ("audi-a4-b8-1-8-tfsi-160",))
    assert row is not None and row["deprecated"] == 1       # aber noch da


def test_broken_seed_never_crashes(tmp_path, db):
    bad = tmp_path / "bad.json"
    bad.write_text("{kaputt", encoding="utf-8")
    assert vc.load_seed(bad) == {}
    assert vc.merge_seed(db, bad) == {"marken": 0, "baureihen": 0, "generationen": 0,
                                      "motorisierungen": 0, "motorcodes": 0,
                                      "verknuepfungen": 0}
    # Kaputter Seed darf den bestehenden Katalog NICHT entwerten.
    assert vc.motorisierungen(db, "audi-a4-b8")


def test_partial_seed_does_not_tombstone_untouched_tables(tmp_path, db):
    """Fehlender Schlüssel = keine Aussage (nicht „alles weg").

    Sonst würde ein verstümmelter Seed (z. B. nur „marken") den halben
    Katalog abräumen und die Auswahl bestehender Fahrzeuge zerreißen.
    """
    partial = tmp_path / "partial.json"
    partial.write_text(json.dumps({"katalog_version": 1, "marken": SEED["marken"]}),
                       encoding="utf-8")
    vc.merge_seed(db, partial)
    assert vc.motorisierungen(db, "audi-a4-b8")      # unangetastet
    assert vc.marken(db) == [("audi", "Audi")]


# --- HSN/TSN ----------------------------------------------------------------------
def test_kba_lookup(tmp_path):
    db = Database(tmp_path / "k.db")
    try:
        seed = tmp_path / "kba.csv.gz"
        with gzip.open(seed, "wt", encoding="utf-8", newline="") as fh:
            fh.write("# quelle,KBA FZ 6\nhsn,tsn,hersteller,handelsname\n"
                     "0588,300,AUDI,AUDI 80\n0603,469,VOLKSWAGEN-VW,GOLF\n")
        assert vc.merge_kba_seed(db, seed) == 2
        treffer = vc.kba_lookup(db, "0603", "469")
        assert treffer.hersteller == "VOLKSWAGEN-VW" and treffer.handelsname == "GOLF"
        assert vc.kba_lookup(db, "0603", "469".lower()) is not None  # case-insensitiv
        # Fehleingaben liefern None statt zu werfen.
        assert vc.kba_lookup(db, "60", "469") is None
        assert vc.kba_lookup(db, "9999", "999") is None
        assert vc.kba_lookup(db, "", "") is None
        # Zweiter Merge mit gleicher Datei: nichts zu tun.
        assert vc.merge_kba_seed(db, seed) == 0
    finally:
        db.close()


def test_kba_seed_shipped_is_real():
    """Der mitgelieferte KBA-Seed muss echt und plausibel sein."""
    path = vc.kba_seed_path()
    assert path.is_file(), "kba_seed.csv.gz fehlt — tools/build_kba_seed.py laufen lassen"
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    assert lines[0].startswith("# quelle"), "Quellenvermerk fehlt (Lizenzpflicht!)"
    assert "Datenlizenz Deutschland" in lines[0]
    assert len(lines) > 50_000, "Datei wirkt unvollständig"


# --- Motorcode: Vorschlag ≠ Bestätigung (Kern des Vertrauensmodells) ----------
def test_ambiguous_motor_offers_all_codes(db):
    """Mehrdeutigkeit wird abgebildet, nicht aufgelöst."""
    codes = vc.motorcode_vorschlaege(db, "audi-a4-b8-1-8-tfsi-160")
    assert [c.code for c in codes] == ["CABB", "CDHB"]
    assert {c.motorfamilie for c in codes} == {"EA888-GEN1", "EA888-GEN2"}


def test_motorfamilie_only_when_unambiguous(db):
    assert vc.motorfamilie_fuer_code(db, "CDHB") == "EA888-GEN2"
    assert vc.motorfamilie_fuer_code(db, "cdhb") == "EA888-GEN2"   # case-insensitiv
    assert vc.motorfamilie_fuer_code(db, "GIBTESNICHT") is None
    assert vc.motorfamilie_fuer_code(db, "") is None
    # Derselbe Code in zwei Familien ⇒ nicht auflösbar ⇒ None (fail closed).
    db.execute("INSERT INTO katalog_motorcode (id, code, motorfamilie, quelle_url, "
               "quelle_zitat) VALUES ('x-cdhb', 'CDHB', 'ANDERE-FAMILIE', "
               "'https://example.org', 'zitat')")
    assert vc.motorfamilie_fuer_code(db, "CDHB") is None


def _vehicle(**kwargs) -> Vehicle:
    base = dict(name="A4", kraftstoff="benzin", km_stand=150_000)
    base.update(kwargs)
    return Vehicle(**base)


def _rule() -> CatalogItem:
    return CatalogItem(id="steuerkette", name="Steuerkette prüfen",
                       bedingungen={"motorfamilie": ["EA888-GEN1", "EA888-GEN2"]})


def _code_rule() -> CatalogItem:
    return CatalogItem(id="nur-cdhb", name="Nur CDHB",
                       bedingungen={"motorcode": ["CDHB"]})


def test_confirmed_code_triggers_recommendation():
    v = _vehicle(motorcode="CDHB", motorcode_herkunft="nutzer")
    assert catalog.matches(_code_rule(), v)
    assert catalog.matches(_rule(), v, motorfamilie="EA888-GEN2")


def test_unconfirmed_code_never_triggers():
    """DIE zentrale Invariante: ohne Bestätigung feuert nichts."""
    # Code da, aber nicht vom Nutzer bestätigt (z. B. altes Datenfeld).
    v = _vehicle(motorcode="CDHB", motorcode_herkunft=None)
    assert not catalog.matches(_code_rule(), v)
    assert not catalog.matches(_rule(), v, motorfamilie="EA888-GEN2")
    # Kein Code ⇒ kein Match (nicht etwa „matcht alles").
    v2 = _vehicle(motorcode="", motorcode_herkunft="nutzer")
    assert not catalog.matches(_code_rule(), v2)
    assert not catalog.matches(_rule(), v2, motorfamilie="EA888-GEN2")


def test_wrong_code_does_not_trigger():
    v = _vehicle(motorcode="CABB", motorcode_herkunft="nutzer")
    assert not catalog.matches(_code_rule(), v)               # Regel will CDHB
    assert catalog.matches(_rule(), v, motorfamilie="EA888-GEN1")  # Familie passt


def test_family_rule_needs_resolvable_family():
    """Mehrdeutiger Code ⇒ Aufrufer übergibt None ⇒ kein Match."""
    v = _vehicle(motorcode="CDHB", motorcode_herkunft="nutzer")
    assert not catalog.matches(_rule(), v, motorfamilie=None)


def test_model_never_persists_katalog_as_confirmation():
    """Auch ein manipuliertes Feld kann keine Bestätigung vortäuschen."""
    v = _vehicle(motorcode="CDHB", motorcode_herkunft="katalog")
    assert v.to_params()["motorcode_herkunft"] is None
    assert not catalog.matches(_code_rule(), v)


def test_motorcode_roundtrip_is_normalised(tmp_path):
    db = Database(tmp_path / "r.db")
    try:
        repo = VehicleRepository(db)
        vid = repo.add(_vehicle(motorcode=" cdhb ", motorcode_herkunft="nutzer",
                                profil_dirty=["hubraum_ccm"]))
        v = repo.get(vid)
        assert v.motorcode == "CDHB"                  # getrimmt + Großbuchstaben
        assert v.motorcode_herkunft == "nutzer"
        assert v.profil_dirty == ["hubraum_ccm"]
    finally:
        db.close()
