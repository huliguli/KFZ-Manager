"""Domain model dataclasses and shared vocabulary definitions.

These mirror the SQLite tables. Money fields are always integer cents; fuel
volumes are integer millilitres, charge energy integer watt-hours. Each model
knows how to build itself from a ``sqlite3.Row`` and back to a parameter
dict, keeping SQL out of the rest of the application.

The vocabulary keys (kraftstoff, motorbauform, ...) are stable machine values;
the *_LABELS dicts hold the German display names. The recommendation matcher
(modules.catalog) works on the machine values, so they must never be renamed
without a migration.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- Vehicle profile vocabularies -------------------------------------------
KRAFTSTOFFE = ["benzin", "diesel", "hev", "phev", "elektro", "lpg", "cng"]
KRAFTSTOFF_LABELS = {
    "benzin": "Benzin",
    "diesel": "Diesel",
    "hev": "Hybrid (HEV)",
    "phev": "Plug-in-Hybrid",
    "elektro": "Elektro",
    "lpg": "Autogas (LPG)",
    "cng": "Erdgas (CNG)",
}
# Convenience sets for the matcher and consumption logic.
VERBRENNER = {"benzin", "diesel", "hev", "phev", "lpg", "cng"}
ELEKTRISCH = {"elektro", "phev"}

MOTORBAUFORMEN = ["r3", "r4", "r5", "r6", "v6", "v8", "v10", "v12",
                  "boxer", "wankel", "emotor"]
MOTORBAUFORM_LABELS = {
    "r3": "R3 (Dreizylinder)", "r4": "R4 (Vierzylinder)", "r5": "R5 (Fünfzylinder)",
    "r6": "R6 (Reihensechser)", "v6": "V6", "v8": "V8", "v10": "V10", "v12": "V12",
    "boxer": "Boxer", "wankel": "Wankel", "emotor": "E-Motor",
}

AUFLADUNGEN = ["sauger", "turbo", "kompressor", "biturbo"]
AUFLADUNG_LABELS = {
    "sauger": "Sauger", "turbo": "Turbo",
    "kompressor": "Kompressor", "biturbo": "Biturbo",
}

PARTIKELFILTER = ["keiner", "dpf", "opf"]
PARTIKELFILTER_LABELS = {"keiner": "Keiner", "dpf": "DPF (Diesel)", "opf": "OPF (Benzin)"}

GETRIEBE = ["manuell", "wandler", "dsg", "cvt"]
GETRIEBE_LABELS = {
    "manuell": "Manuell", "wandler": "Automatik (Wandler)",
    "dsg": "DSG / Doppelkupplung", "cvt": "CVT",
}

ANTRIEBE = ["fwd", "rwd", "awd"]
ANTRIEB_LABELS = {"fwd": "Frontantrieb", "rwd": "Heckantrieb", "awd": "Allrad"}

FAHRPROFILE = ["kurzstrecke", "mix", "langstrecke"]
FAHRPROFIL_LABELS = {
    "kurzstrecke": "Überwiegend Kurzstrecke",
    "mix": "Gemischt",
    "langstrecke": "Überwiegend Langstrecke",
}

LADEORTE = ["heim", "ac", "dc"]
LADEORT_LABELS = {"heim": "Zuhause", "ac": "Öffentlich AC", "dc": "Schnelllader DC"}

# --- Cost / catalog / logbook vocabularies -----------------------------------
COST_CATEGORIES = ["Werkstatt", "Versicherung", "Steuer", "Pflege",
                   "Zubehör", "Kraftstoff/Strom", "Sonstiges"]

APPOINTMENT_TYPES = ["TÜV/HU", "Inspektion", "Versicherung", "Reifenwechsel", "Sonstiges"]

CATALOG_CATEGORIES = ["Additiv", "Öl", "Kühlsystem", "DPF", "Innenraum",
                      "Lack", "E-Auto", "Allgemein"]

LOGBOOK_KINDS = ["pflege", "wartung", "sonstiges"]
LOGBOOK_KIND_LABELS = {"pflege": "Pflege", "wartung": "Wartung", "sonstiges": "Sonstiges"}


def label_for(value: str | None, labels: dict[str, str], fallback: str = "—") -> str:
    """Display label for a vocabulary value (fallback for None/unknown)."""
    if not value:
        return fallback
    return labels.get(value, value)


# --- Models -------------------------------------------------------------------
@dataclass
class Vehicle:
    name: str
    hersteller: str = ""
    modell: str = ""
    erstzulassung: str | None = None    # ISO
    kennzeichen: str = ""
    km_stand: int | None = None
    km_stand_datum: str | None = None   # ISO
    kraftstoff: str | None = None
    motorbauform: str | None = None
    hubraum_ccm: int | None = None
    leistung_ps: int | None = None
    aufladung: str | None = None
    direkteinspritzung: bool | None = None
    partikelfilter: str | None = None
    getriebe: str | None = None
    antrieb: str | None = None
    oel_viskositaet: str = ""
    oel_freigabe: str = ""
    fahrprofil: str | None = None
    notiz: str = ""
    active: bool = True
    id: int | None = None

    @staticmethod
    def from_row(row) -> "Vehicle":
        de = row["direkteinspritzung"]
        return Vehicle(
            id=row["id"],
            name=row["name"],
            hersteller=row["hersteller"] or "",
            modell=row["modell"] or "",
            erstzulassung=row["erstzulassung"],
            kennzeichen=row["kennzeichen"] or "",
            km_stand=row["km_stand"],
            km_stand_datum=row["km_stand_datum"],
            kraftstoff=row["kraftstoff"],
            motorbauform=row["motorbauform"],
            hubraum_ccm=row["hubraum_ccm"],
            leistung_ps=row["leistung_ps"],
            aufladung=row["aufladung"],
            direkteinspritzung=None if de is None else bool(de),
            partikelfilter=row["partikelfilter"],
            getriebe=row["getriebe"],
            antrieb=row["antrieb"],
            oel_viskositaet=row["oel_viskositaet"] or "",
            oel_freigabe=row["oel_freigabe"] or "",
            fahrprofil=row["fahrprofil"],
            notiz=row["notiz"] or "",
            active=bool(row["active"]),
        )

    def to_params(self) -> dict:
        return {
            "name": self.name,
            "hersteller": self.hersteller or None,
            "modell": self.modell or None,
            "erstzulassung": self.erstzulassung,
            "kennzeichen": self.kennzeichen or None,
            "km_stand": self.km_stand,
            "km_stand_datum": self.km_stand_datum,
            "kraftstoff": self.kraftstoff,
            "motorbauform": self.motorbauform,
            "hubraum_ccm": self.hubraum_ccm,
            "leistung_ps": self.leistung_ps,
            "aufladung": self.aufladung,
            "direkteinspritzung": (None if self.direkteinspritzung is None
                                   else int(self.direkteinspritzung)),
            "partikelfilter": self.partikelfilter,
            "getriebe": self.getriebe,
            "antrieb": self.antrieb,
            "oel_viskositaet": self.oel_viskositaet or None,
            "oel_freigabe": self.oel_freigabe or None,
            "fahrprofil": self.fahrprofil,
            "notiz": self.notiz or None,
            "active": 1 if self.active else 0,
        }

    @property
    def display_name(self) -> str:
        """Name plus manufacturer/model when they add information."""
        extra = " ".join(p for p in (self.hersteller, self.modell) if p)
        if extra and extra.lower() not in self.name.lower():
            return f"{self.name} ({extra})"
        return self.name

    @property
    def ist_elektrisch(self) -> bool:
        return self.kraftstoff in ELEKTRISCH

    @property
    def ist_verbrenner(self) -> bool:
        return self.kraftstoff in VERBRENNER


@dataclass
class TankEntry:
    vehicle_id: int
    date: str                          # ISO
    odo_km: int
    art: str = "kraftstoff"            # kraftstoff | strom
    menge_ml: int | None = None        # Liter * 1000
    energie_wh: int | None = None      # kWh * 1000
    betrag_cent: int = 0
    voll: bool = True
    ladeort: str | None = None
    notiz: str = ""
    id: int | None = None

    @staticmethod
    def from_row(row) -> "TankEntry":
        return TankEntry(
            id=row["id"],
            vehicle_id=row["vehicle_id"],
            date=row["date"],
            odo_km=row["odo_km"],
            art=row["art"],
            menge_ml=row["menge_ml"],
            energie_wh=row["energie_wh"],
            betrag_cent=row["betrag_cent"],
            voll=bool(row["voll"]),
            ladeort=row["ladeort"],
            notiz=row["notiz"] or "",
        )

    def to_params(self) -> dict:
        return {
            "vehicle_id": self.vehicle_id,
            "date": self.date,
            "odo_km": int(self.odo_km),
            "art": self.art,
            "menge_ml": self.menge_ml,
            "energie_wh": self.energie_wh,
            "betrag_cent": int(self.betrag_cent),
            "voll": 1 if self.voll else 0,
            "ladeort": self.ladeort,
            "notiz": self.notiz or None,
        }


@dataclass
class Cost:
    vehicle_id: int
    date: str                          # ISO
    kategorie: str = "Sonstiges"
    betrag_cent: int = 0
    notiz: str = ""
    odo_km: int | None = None
    id: int | None = None

    @staticmethod
    def from_row(row) -> "Cost":
        return Cost(
            id=row["id"],
            vehicle_id=row["vehicle_id"],
            date=row["date"],
            kategorie=row["kategorie"],
            betrag_cent=row["betrag_cent"],
            notiz=row["notiz"] or "",
            odo_km=row["odo_km"],
        )

    def to_params(self) -> dict:
        return {
            "vehicle_id": self.vehicle_id,
            "date": self.date,
            "kategorie": self.kategorie,
            "betrag_cent": int(self.betrag_cent),
            "notiz": self.notiz or None,
            "odo_km": self.odo_km,
        }


@dataclass
class Appointment:
    vehicle_id: int
    typ: str = "Sonstiges"
    beschreibung: str = ""
    faellig_datum: str | None = None   # ISO
    faellig_km: int | None = None
    erledigt: bool = False
    erledigt_datum: str | None = None
    id: int | None = None

    @staticmethod
    def from_row(row) -> "Appointment":
        return Appointment(
            id=row["id"],
            vehicle_id=row["vehicle_id"],
            typ=row["typ"],
            beschreibung=row["beschreibung"] or "",
            faellig_datum=row["faellig_datum"],
            faellig_km=row["faellig_km"],
            erledigt=bool(row["erledigt"]),
            erledigt_datum=row["erledigt_datum"],
        )

    def to_params(self) -> dict:
        return {
            "vehicle_id": self.vehicle_id,
            "typ": self.typ,
            "beschreibung": self.beschreibung or None,
            "faellig_datum": self.faellig_datum,
            "faellig_km": self.faellig_km,
            "erledigt": 1 if self.erledigt else 0,
            "erledigt_datum": self.erledigt_datum,
        }


@dataclass
class CareRule:
    vehicle_id: int
    name: str
    kategorie: str = "Allgemein"
    catalog_id: str | None = None
    intervall_km: int | None = None
    intervall_monate: int | None = None
    letzte_datum: str | None = None    # ISO
    letzte_km: int | None = None
    notiz: str = ""
    aktiv: bool = True
    id: int | None = None

    @staticmethod
    def from_row(row) -> "CareRule":
        return CareRule(
            id=row["id"],
            vehicle_id=row["vehicle_id"],
            catalog_id=row["catalog_id"],
            name=row["name"],
            kategorie=row["kategorie"],
            intervall_km=row["intervall_km"],
            intervall_monate=row["intervall_monate"],
            letzte_datum=row["letzte_datum"],
            letzte_km=row["letzte_km"],
            notiz=row["notiz"] or "",
            aktiv=bool(row["aktiv"]),
        )

    def to_params(self) -> dict:
        return {
            "vehicle_id": self.vehicle_id,
            "catalog_id": self.catalog_id,
            "name": self.name,
            "kategorie": self.kategorie,
            "intervall_km": self.intervall_km,
            "intervall_monate": self.intervall_monate,
            "letzte_datum": self.letzte_datum,
            "letzte_km": self.letzte_km,
            "notiz": self.notiz or None,
            "aktiv": 1 if self.aktiv else 0,
        }

    def interval_text(self) -> str:
        """Human label like 'alle 15.000 km oder 12 Monate'."""
        parts = []
        if self.intervall_km:
            parts.append(f"alle {self.intervall_km:,} km".replace(",", "."))
        if self.intervall_monate:
            unit = "Monat" if self.intervall_monate == 1 else "Monate"
            parts.append(f"alle {self.intervall_monate} {unit}")
        return " oder ".join(parts) if parts else "kein Intervall"


@dataclass
class LogbookEntry:
    vehicle_id: int
    date: str                          # ISO
    titel: str
    art: str = "wartung"               # pflege | wartung | sonstiges
    odo_km: int | None = None
    beschreibung: str = ""
    kosten_cent: int | None = None
    cost_id: int | None = None
    rule_id: int | None = None
    id: int | None = None

    @staticmethod
    def from_row(row) -> "LogbookEntry":
        return LogbookEntry(
            id=row["id"],
            vehicle_id=row["vehicle_id"],
            date=row["date"],
            odo_km=row["odo_km"],
            art=row["art"],
            titel=row["titel"],
            beschreibung=row["beschreibung"] or "",
            kosten_cent=row["kosten_cent"],
            cost_id=row["cost_id"],
            rule_id=row["rule_id"],
        )

    def to_params(self) -> dict:
        return {
            "vehicle_id": self.vehicle_id,
            "date": self.date,
            "odo_km": self.odo_km,
            "art": self.art,
            "titel": self.titel,
            "beschreibung": self.beschreibung or None,
            "kosten_cent": self.kosten_cent,
            "cost_id": self.cost_id,
            "rule_id": self.rule_id,
        }


@dataclass
class Attachment:
    vehicle_id: int
    entry_kind: str                    # 'logbook' | 'cost'
    entry_id: int
    rel_path: str                      # relative to data_dir()
    original_name: str
    size_bytes: int = 0
    id: int | None = None

    @staticmethod
    def from_row(row) -> "Attachment":
        return Attachment(
            id=row["id"],
            vehicle_id=row["vehicle_id"],
            entry_kind=row["entry_kind"],
            entry_id=row["entry_id"],
            rel_path=row["rel_path"],
            original_name=row["original_name"],
            size_bytes=row["size_bytes"],
        )

    def to_params(self) -> dict:
        return {
            "vehicle_id": self.vehicle_id,
            "entry_kind": self.entry_kind,
            "entry_id": self.entry_id,
            "rel_path": self.rel_path,
            "original_name": self.original_name,
            "size_bytes": int(self.size_bytes),
        }


@dataclass
class CatalogItem:
    id: str                            # stable: seed-* / user-*
    name: str
    kategorie: str = "Allgemein"
    bedingungen: dict | None = None    # matcher conditions (parsed JSON)
    intervall_km: int | None = None
    intervall_monate: int | None = None
    warum: str = ""
    produkt_beispiel: str = ""
    quelle: str = "seed"               # 'seed' | 'user'

    @staticmethod
    def from_row(row) -> "CatalogItem":
        import json
        try:
            conditions = json.loads(row["bedingungen_json"] or "{}")
        except ValueError:
            conditions = {}
        return CatalogItem(
            id=row["id"],
            name=row["name"],
            kategorie=row["kategorie"],
            bedingungen=conditions if isinstance(conditions, dict) else {},
            intervall_km=row["intervall_km"],
            intervall_monate=row["intervall_monate"],
            warum=row["warum"] or "",
            produkt_beispiel=row["produkt_beispiel"] or "",
            quelle=row["quelle"],
        )

    def to_params(self) -> dict:
        import json
        return {
            "id": self.id,
            "name": self.name,
            "kategorie": self.kategorie,
            "bedingungen_json": json.dumps(self.bedingungen or {}, ensure_ascii=False),
            "intervall_km": self.intervall_km,
            "intervall_monate": self.intervall_monate,
            "warum": self.warum or None,
            "produkt_beispiel": self.produkt_beispiel or None,
            "quelle": self.quelle,
        }

    def interval_text(self) -> str:
        parts = []
        if self.intervall_km:
            parts.append(f"alle {self.intervall_km:,} km".replace(",", "."))
        if self.intervall_monate:
            unit = "Monat" if self.intervall_monate == 1 else "Monate"
            parts.append(f"alle {self.intervall_monate} {unit}")
        return " oder ".join(parts) if parts else "nach Bedarf"
