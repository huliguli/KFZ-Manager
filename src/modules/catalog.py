"""Empfehlungs-Katalog: seed merge and the rule-based profile matcher.

The catalog ships with the app as ``src/database/catalog_seed.json`` and is
merged into the ``catalog_items`` table on every start — STRICTLY ADDITIVELY
by stable id: an id that already exists in the database is never touched, so
user edits, user-created entries (``user-*`` ids) and per-vehicle hides
survive every app update. Removing an entry from the seed never deletes it
from an existing database either (the user may have adopted it).

Matching is rule-based and fully offline (NO LLM anywhere): every condition
in an item's ``bedingungen`` dict must hold against the vehicle profile
(logical AND); list-valued conditions mean "one of" (logical OR inside the
field). A condition on a profile field the user left empty does NOT match —
better to show too few suggestions than wrong ones. Supported conditions:

    kraftstoff           list[str]  — one of KRAFTSTOFFE
    aufladung            list[str]
    partikelfilter       list[str]
    getriebe             list[str]
    fahrprofil           list[str]
    motorbauform         list[str]
    direkteinspritzung   bool
    min_laufleistung_km  int        — current odometer at least this
    max_laufleistung_km  int
    min_alter_jahre      int        — years since first registration
    motorcode            list[str]  — Motorkennbuchstaben, z. B. ["CDHB"]
    motorfamilie         list[str]  — z. B. ["EA888-GEN1", "EA888-GEN2"]

Die beiden letzten Bedingungen sind bewusst STRENGER als alle anderen: Sie
matchen nur, wenn der Nutzer den Motorcode selbst bestätigt hat
(``vehicle.motorcode_herkunft == 'nutzer'``). Grund: Die Zuordnung
Motorisierung→Motorcode ist mehrdeutig (Audi A4 B8 „1.8 TFSI 160 PS" = CABB
ODER CDHB, identische kW/ccm), ein geratener Code würde also falsche
Wartungshinweise auslösen, die der Nutzer nicht als falsch erkennen kann.
Ein Katalog-Vorschlag allein löst deshalb NIE eine Empfehlung aus — der
Katalog fragt, der Nutzer antwortet, erst dann greift die Regel.

Every product named in the seed is a real, established product (Liqui Moly,
Sonax, Bosch, MANN-FILTER, Flashlube …) referenced WITHOUT invented article
numbers or prices — inventing product data is a classic generation trap the
project explicitly guards against. Recommendations never override the
manufacturer's service schedule; the UI shows that disclaimer prominently.
"""

from __future__ import annotations

import json
from datetime import date

from app_meta import catalog_seed_path
from modules import dates
from modules.logging_setup import get_logger
from modules.models import CatalogItem, Vehicle

_log = get_logger("catalog")

# Conditions the matcher understands; unknown keys make an item NOT match
# (fail closed — a future seed with new conditions must not mis-match on old
# app versions that do not understand them).
_LIST_CONDITIONS = ("kraftstoff", "aufladung", "partikelfilter", "getriebe",
                    "fahrprofil", "motorbauform")
# Motorcode-Bedingungen laufen NICHT über _LIST_CONDITIONS: sie prüfen nicht
# ein Profilfeld, sondern eine bestätigte Nutzerangabe (siehe Modul-Docstring).
_MOTOR_CONDITIONS = ("motorcode", "motorfamilie")
_KNOWN_CONDITIONS = set(_LIST_CONDITIONS) | set(_MOTOR_CONDITIONS) | {
    "direkteinspritzung", "min_laufleistung_km", "max_laufleistung_km",
    "min_alter_jahre"}


def load_seed(path=None) -> list[dict]:
    """Parse the bundled seed file. Returns [] when missing/broken (the app
    must start even with a damaged seed — the catalog is a bonus feature)."""
    path = path or catalog_seed_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        items = data.get("items", [])
        return items if isinstance(items, list) else []
    except (OSError, ValueError) as exc:
        _log.warning("Katalog-Seed konnte nicht geladen werden: %s", exc)
        return []


def merge_seed(db, path=None) -> int:
    """Insert seed items whose id is not in the database yet (additive merge).

    Existing rows are NEVER updated or deleted — user modifications, adopted
    entries and hides stay exactly as they are. Returns the number of newly
    inserted items.
    """
    inserted = 0
    for raw in load_seed(path):
        item_id = str(raw.get("id") or "").strip()
        name = str(raw.get("name") or "").strip()
        if not item_id or not name:
            continue  # malformed seed row: skip, never crash
        cur = db.conn.execute(
            "INSERT OR IGNORE INTO catalog_items "
            "(id, name, kategorie, bedingungen_json, intervall_km, "
            " intervall_monate, warum, produkt_beispiel, quelle) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'seed')",
            (item_id, name,
             raw.get("kategorie") or "Allgemein",
             json.dumps(raw.get("bedingungen") or {}, ensure_ascii=False),
             raw.get("intervall_km"),
             raw.get("intervall_monate"),
             raw.get("warum"),
             raw.get("produkt_beispiel")))
        inserted += cur.rowcount if cur.rowcount > 0 else 0
    db.conn.commit()
    if inserted:
        _log.info("Katalog-Seed: %d neue Einträge übernommen.", inserted)
    return inserted


def _vehicle_age_years(vehicle: Vehicle, today: date | None = None) -> float | None:
    reg = dates.parse_date(vehicle.erstzulassung)
    if reg is None:
        return None
    today = today or dates.today()
    return (today - reg).days / 365.25


def matches(item: CatalogItem, vehicle: Vehicle, km_now: int | None = None,
            today: date | None = None, motorfamilie: str | None = None) -> bool:
    """True when every condition of the item holds for the vehicle profile.

    ``km_now`` is the best-known current odometer (falls back to the profile
    reading). ``motorfamilie`` is the family the vehicle's CONFIRMED motor code
    resolves to unambiguously (see modules.vehicle_catalog.motorfamilie_fuer_code);
    the caller passes it because the resolution needs a database lookup.

    Unknown profile values fail the respective condition (see module
    docstring) — and unknown condition KEYS fail the whole item (fail closed).
    """
    conditions = item.bedingungen or {}
    if any(key not in _KNOWN_CONDITIONS for key in conditions):
        return False
    km = km_now if km_now is not None else vehicle.km_stand

    # --- Motorcode-Bedingungen: nur mit BESTÄTIGTEM Code ---------------------
    # Fail closed in beide Richtungen: kein Code / nicht bestätigt ⇒ kein Match
    # (nicht etwa "matcht alles"). Ein Katalog-Vorschlag ist keine Bestätigung.
    if any(key in conditions for key in _MOTOR_CONDITIONS):
        if vehicle.motorcode_herkunft != "nutzer" or not vehicle.motorcode:
            return False
        code = (vehicle.motorcode or "").strip().upper()
        if "motorcode" in conditions:
            allowed = conditions["motorcode"]
            if not isinstance(allowed, list):
                allowed = [allowed]
            if code not in {str(a).strip().upper() for a in allowed}:
                return False
        if "motorfamilie" in conditions:
            allowed = conditions["motorfamilie"]
            if not isinstance(allowed, list):
                allowed = [allowed]
            # Nicht auflösbar oder mehrdeutig ⇒ kein Match.
            if not motorfamilie:
                return False
            if motorfamilie.strip().upper() not in {
                    str(a).strip().upper() for a in allowed}:
                return False

    for key in _LIST_CONDITIONS:
        if key in conditions:
            allowed = conditions[key]
            if not isinstance(allowed, list):
                allowed = [allowed]
            value = getattr(vehicle, key)
            if value is None or value not in allowed:
                return False

    if "direkteinspritzung" in conditions:
        if vehicle.direkteinspritzung is None:
            return False
        if bool(conditions["direkteinspritzung"]) != vehicle.direkteinspritzung:
            return False

    if "min_laufleistung_km" in conditions:
        if km is None or km < int(conditions["min_laufleistung_km"]):
            return False
    if "max_laufleistung_km" in conditions:
        if km is None or km > int(conditions["max_laufleistung_km"]):
            return False

    if "min_alter_jahre" in conditions:
        age = _vehicle_age_years(vehicle, today)
        if age is None or age < float(conditions["min_alter_jahre"]):
            return False

    return True


def suggestions_for(items: list[CatalogItem], vehicle: Vehicle,
                    hidden_ids: set[str], adopted_ids: set[str],
                    km_now: int | None = None,
                    today: date | None = None,
                    motorfamilie: str | None = None) -> list[CatalogItem]:
    """Matching, not-hidden, not-yet-adopted catalog items for one vehicle."""
    return [item for item in items
            if item.id not in hidden_ids
            and item.id not in adopted_ids
            and matches(item, vehicle, km_now, today, motorfamilie)]


def next_user_id(existing_ids: set[str]) -> str:
    """Stable id for a user-created catalog entry (user-1, user-2, …)."""
    n = 1
    while f"user-{n}" in existing_ids:
        n += 1
    return f"user-{n}"
