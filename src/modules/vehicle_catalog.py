"""Fahrzeug-Katalog: Seed-Merge, Kaskaden-Abfragen, HSN/TSN-Auflösung.

Der Katalog erspart dem Nutzer das Abtippen des Fahrzeugprofils: Er wählt
Marke → Baureihe/Generation → Motorisierung (oder tippt HSN/TSN aus dem
Fahrzeugschein), und die Profilfelder werden VORBELEGT.

**Vertrauensmodell — der wichtigste Teil dieses Moduls:**

Katalogdaten sind Vorschläge, keine Wahrheit. Zwei Klassen, hart getrennt:

* *Vorbelegung* (Kraftstoff, Hubraum, PS …): darf aus dem Katalog kommen,
  ist sichtbar und editierbar; ein Fehler ist ärgerlich, aber korrigierbar.
* *Motorcode*: kommt NIE aus dem Katalog in die Fahrzeugdaten. Die Zuordnung
  Motorisierung→Code ist nachweislich mehrdeutig (Audi A4 B8 „1.8 TFSI
  160 PS" = CABB ODER CDHB — identische kW/ccm, nur übers Baujahr trennbar).
  Der Katalog SCHLÄGT VOR, der Nutzer BESTÄTIGT aus seinem Fahrzeugschein
  (Feld D.2) oder vom Motorblock. Nur ein bestätigter Code
  (``motorcode_herkunft = 'nutzer'``) löst motorcode-spezifische
  Empfehlungen aus — siehe modules.catalog.

Datenquellen (beide frei und im Repo dokumentiert, siehe
``src/database/KATALOG-QUELLEN.md``):

* ``kba_seed.csv.gz`` — HSN/TSN → Hersteller/Handelsname, aus der KBA-Statistik
  FZ 6 (Datenlizenz Deutschland – Namensnennung – Version 2.0).
* ``vehicle_seed.json`` — handkuratierte Generationen/Motorisierungen/
  Motorcodes; jede Zeile trägt Quellen-URL + wörtliches Zitat.

Merge-Regeln (wie beim Empfehlungs-Katalog): additiv über stabile Text-IDs.
Bekannte IDs werden aktualisiert (Katalogdaten sind read-only Referenz, keine
Nutzerdaten), verschwundene IDs werden NICHT gelöscht, sondern als
``deprecated`` markiert — sonst zerreißt ein Katalog-Update die Referenz eines
bestehenden Fahrzeugs.
"""

from __future__ import annotations

import csv
import gzip
import json
from dataclasses import dataclass
from pathlib import Path

from app_meta import resource_path
from modules.logging_setup import get_logger

_log = get_logger("katalog")

# Profilfelder, die eine Motorisierung vorbelegen kann. Reihenfolge = Reihenfolge
# im Fahrzeug-Dialog; Namen sind IDENTISCH zu den Vehicle-Feldern, damit die
# Vorbelegung ohne Übersetzungstabelle funktioniert (eine Quelle für Drift
# weniger).
PREFILL_FIELDS = (
    "kraftstoff", "motorbauform", "aufladung", "direkteinspritzung",
    "partikelfilter", "hubraum_ccm", "leistung_ps", "getriebe",
    "oel_viskositaet", "oel_freigabe",
)


def seed_path() -> Path:
    return resource_path("src", "database", "vehicle_seed.json")


def kba_seed_path() -> Path:
    return resource_path("src", "database", "kba_seed.csv.gz")


@dataclass(frozen=True)
class Motorisierung:
    """Eine wählbare Motorisierung inkl. ihrer Vorbelegungs-Werte."""
    id: str
    generation_id: str
    anzeigename: str
    bj_von: int | None
    bj_bis: int | None
    werte: dict          # nur PREFILL_FIELDS
    quelle_url: str
    quelle_zitat: str

    def zeitraum_text(self) -> str:
        if not self.bj_von:
            return ""
        return f"{self.bj_von}–{self.bj_bis}" if self.bj_bis else f"ab {self.bj_von}"


@dataclass(frozen=True)
class MotorcodeVorschlag:
    """Ein Motorcode, den der Nutzer bestätigen (oder ablehnen) kann."""
    code: str
    motorfamilie: str
    einbaulage: str
    bj_von: int | None
    bj_bis: int | None
    quelle_url: str


@dataclass(frozen=True)
class KbaTreffer:
    hsn: str
    tsn: str
    hersteller: str
    handelsname: str


# --- Seed laden / mergen ------------------------------------------------------
def load_seed(path: Path | None = None) -> dict:
    """Bundled JSON-Seed lesen. Kaputt/fehlend ⇒ {} (Katalog ist optional)."""
    path = path or seed_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as exc:
        _log.warning("Fahrzeug-Seed konnte nicht geladen werden: %s", exc)
        return {}


def _merge_table(db, table: str, rows: list[dict] | None,
                 columns: tuple[str, ...]) -> int:
    """Additiver Upsert einer Katalog-Tabelle über die stabile Text-ID.

    Nur Katalogdaten (read-only Referenz) — Nutzerzeilen liegen in anderen
    Tabellen und werden hier nie berührt. Rückgabe: Anzahl geschriebener Zeilen.

    Semantik von ``rows``, bewusst unterschieden:

    * ``None`` (Schlüssel fehlt im Seed) — keine Aussage, Tabelle bleibt
      unangetastet. Schützt vor einem verstümmelten Seed, der sonst den
      halben Katalog tombstonen würde.
    * ``[]`` (Schlüssel da, leer) — der Seed sagt „es gibt hier nichts mehr",
      alle bestehenden Zeilen werden getombstonet.
    """
    if rows is None:
        return 0
    written = 0
    seen_ids: list[str] = []
    for row in rows:
        row_id = str(row.get("id") or "").strip()
        if not row_id:
            continue
        values = [row.get(c) for c in columns]
        placeholders = ", ".join("?" for _ in columns)
        updates = ", ".join(f"{c} = excluded.{c}" for c in columns if c != "id")
        db.conn.execute(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}, deprecated = 0",
            values)
        seen_ids.append(row_id)
        written += 1
    # Tombstones: IDs, die der Seed nicht mehr kennt, bleiben erhalten (ein
    # Bestandsfahrzeug referenziert sie evtl.), verschwinden aber aus der
    # Auswahl. Auch bei rows == [] — dann sind ALLE bestehenden Zeilen entfallen.
    if seen_ids:
        marks = ", ".join("?" for _ in seen_ids)
        db.conn.execute(
            f"UPDATE {table} SET deprecated = 1 WHERE id NOT IN ({marks})", seen_ids)
    else:
        db.conn.execute(f"UPDATE {table} SET deprecated = 1")
    return written


def merge_seed(db, path: Path | None = None) -> dict[str, int]:
    """Kompletten Fahrzeug-Katalog in die DB mergen (idempotent, never raises)."""
    counts = {"marken": 0, "baureihen": 0, "generationen": 0,
              "motorisierungen": 0, "motorcodes": 0, "verknuepfungen": 0}
    data = load_seed(path)
    if not data:
        return counts
    try:
        # .get(key) OHNE Default: fehlender Schlüssel ⇒ None ⇒ Tabelle bleibt
        # unangetastet (siehe _merge_table).
        counts["marken"] = _merge_table(
            db, "katalog_marke", data.get("marken"),
            ("id", "name", "quelle_url", "quelle_abruf"))
        counts["baureihen"] = _merge_table(
            db, "katalog_baureihe", data.get("baureihen"),
            ("id", "marke_id", "name", "quelle_url"))
        counts["generationen"] = _merge_table(
            db, "katalog_generation", data.get("generationen"),
            ("id", "baureihe_id", "name", "bj_von", "bj_bis", "quelle_url"))
        counts["motorisierungen"] = _merge_table(
            db, "katalog_motorisierung", data.get("motorisierungen"),
            ("id", "generation_id", "anzeigename", "bj_von", "bj_bis",
             "kraftstoff", "motorbauform", "aufladung", "direkteinspritzung",
             "partikelfilter", "hubraum_ccm", "leistung_ps", "getriebe",
             "oel_viskositaet", "oel_freigabe",
             "quelle_url", "quelle_zitat", "quelle_abruf"))
        counts["motorcodes"] = _merge_table(
            db, "katalog_motorcode", data.get("motorcodes"),
            ("id", "code", "motorfamilie", "einbaulage", "bj_von", "bj_bis",
             "quelle_url", "quelle_zitat"))
        # n:m-Verknüpfung: komplett neu setzen (reine Ableitung aus dem Seed).
        db.conn.execute("DELETE FROM katalog_motorisierung_motorcode")
        for pair in data.get("motorisierung_motorcode") or []:
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                db.conn.execute(
                    "INSERT OR IGNORE INTO katalog_motorisierung_motorcode "
                    "(motorisierung_id, motorcode_id) VALUES (?, ?)", tuple(pair))
                counts["verknuepfungen"] += 1
        db.conn.commit()
    except Exception as exc:  # noqa: BLE001 - Katalog ist ein Komfort-Feature
        _log.warning("Fahrzeug-Katalog-Merge fehlgeschlagen: %s", exc)
        return counts
    if any(counts.values()):
        _log.info("Fahrzeug-Katalog gemergt: %s", counts)
    return counts


def merge_kba_seed(db, path: Path | None = None) -> int:
    """HSN/TSN-Liste einlesen (nur wenn nötig — 62k Zeilen).

    Übersprungen, sobald die Tabelle bereits gefüllt ist; ein Katalog-Update
    liefert eine neue Datei und wird über die Zeilenzahl erkannt. Never raises.
    """
    path = path or kba_seed_path()
    try:
        row = db.query_one("SELECT COUNT(*) AS n FROM katalog_kba")
        have = int(row["n"]) if row else 0
        if not path.is_file():
            return 0
        with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
            rows = [r for r in csv.reader(fh)
                    if r and not r[0].startswith("#") and r[0] != "hsn"]
        if have == len(rows):
            return 0  # unverändert → nichts zu tun
        db.conn.execute("DELETE FROM katalog_kba")
        db.conn.executemany(
            "INSERT OR REPLACE INTO katalog_kba (hsn, tsn, hersteller, handelsname) "
            "VALUES (?, ?, ?, ?)", [r[:4] for r in rows if len(r) >= 4])
        db.conn.commit()
        _log.info("KBA-Schlüsselnummern geladen: %d Zeilen", len(rows))
        return len(rows)
    except Exception as exc:  # noqa: BLE001
        _log.warning("KBA-Seed konnte nicht geladen werden: %s", exc)
        return 0


# --- Abfragen für die Kaskade ---------------------------------------------------
def marken(db) -> list[tuple[str, str]]:
    rows = db.query("SELECT id, name FROM katalog_marke WHERE deprecated = 0 "
                    "ORDER BY name COLLATE NOCASE")
    return [(r["id"], r["name"]) for r in rows]


def baureihen(db, marke_id: str) -> list[tuple[str, str]]:
    rows = db.query("SELECT id, name FROM katalog_baureihe "
                    "WHERE marke_id = ? AND deprecated = 0 "
                    "ORDER BY name COLLATE NOCASE", (marke_id,))
    return [(r["id"], r["name"]) for r in rows]


def generationen(db, baureihe_id: str) -> list[tuple[str, str]]:
    """(id, Anzeigetext) je Generation — neueste zuerst."""
    rows = db.query(
        "SELECT id, name, bj_von, bj_bis FROM katalog_generation "
        "WHERE baureihe_id = ? AND deprecated = 0 "
        "ORDER BY COALESCE(bj_von, 0) DESC", (baureihe_id,))
    out = []
    for r in rows:
        span = ""
        if r["bj_von"]:
            span = f" ({r['bj_von']}–{r['bj_bis']})" if r["bj_bis"] else f" (ab {r['bj_von']})"
        out.append((r["id"], f"{r['name']}{span}"))
    return out


def motorisierungen(db, generation_id: str) -> list[Motorisierung]:
    rows = db.query(
        "SELECT * FROM katalog_motorisierung WHERE generation_id = ? "
        "AND deprecated = 0 ORDER BY kraftstoff, leistung_ps", (generation_id,))
    return [Motorisierung(
        id=r["id"], generation_id=r["generation_id"], anzeigename=r["anzeigename"],
        bj_von=r["bj_von"], bj_bis=r["bj_bis"],
        werte={f: r[f] for f in PREFILL_FIELDS},
        quelle_url=r["quelle_url"], quelle_zitat=r["quelle_zitat"]) for r in rows]


def get_motorisierung(db, motorisierung_id: str) -> Motorisierung | None:
    rows = db.query("SELECT * FROM katalog_motorisierung WHERE id = ?",
                    (motorisierung_id,))
    if not rows:
        return None
    r = rows[0]
    return Motorisierung(
        id=r["id"], generation_id=r["generation_id"], anzeigename=r["anzeigename"],
        bj_von=r["bj_von"], bj_bis=r["bj_bis"],
        werte={f: r[f] for f in PREFILL_FIELDS},
        quelle_url=r["quelle_url"], quelle_zitat=r["quelle_zitat"])


def motorcode_vorschlaege(db, motorisierung_id: str) -> list[MotorcodeVorschlag]:
    """Mögliche Motorcodes einer Motorisierung — zum BESTÄTIGEN, nie zum Setzen.

    Mehrere Treffer sind der Normalfall und werden bewusst alle geliefert:
    die App darf nicht auswählen, nur fragen.
    """
    rows = db.query(
        "SELECT c.* FROM katalog_motorcode c "
        "JOIN katalog_motorisierung_motorcode v ON v.motorcode_id = c.id "
        "WHERE v.motorisierung_id = ? AND c.deprecated = 0 ORDER BY c.code",
        (motorisierung_id,))
    return [MotorcodeVorschlag(
        code=r["code"], motorfamilie=r["motorfamilie"] or "",
        einbaulage=r["einbaulage"] or "", bj_von=r["bj_von"], bj_bis=r["bj_bis"],
        quelle_url=r["quelle_url"]) for r in rows]


def motorfamilie_fuer_code(db, code: str) -> str | None:
    """Motorfamilie eines Codes — nur bei EINDEUTIGER Auflösung.

    Mehrdeutig (derselbe Code in mehreren Familien) ⇒ None: der
    Empfehlungs-Matcher darf dann nicht auf die Familie schließen.
    """
    if not code:
        return None
    rows = db.query(
        "SELECT DISTINCT motorfamilie FROM katalog_motorcode "
        "WHERE UPPER(code) = UPPER(?) AND motorfamilie IS NOT NULL "
        "AND motorfamilie <> ''", (code.strip(),))
    return rows[0]["motorfamilie"] if len(rows) == 1 else None


# --- HSN/TSN ---------------------------------------------------------------------
def kba_lookup(db, hsn: str, tsn: str) -> KbaTreffer | None:
    """Fahrzeugschein Feld 2.1 (HSN) + 2.2 (TSN) → Hersteller/Handelsname."""
    hsn = (hsn or "").strip()
    tsn = (tsn or "").strip().upper()
    if not (len(hsn) == 4 and hsn.isdigit()) or len(tsn) != 3:
        return None
    row = db.query_one(
        "SELECT hsn, tsn, hersteller, handelsname FROM katalog_kba "
        "WHERE hsn = ? AND UPPER(tsn) = ?", (hsn, tsn))
    return KbaTreffer(row["hsn"], row["tsn"], row["hersteller"],
                      row["handelsname"]) if row else None


def kba_available(db) -> bool:
    row = db.query_one("SELECT 1 FROM katalog_kba LIMIT 1")
    return row is not None
