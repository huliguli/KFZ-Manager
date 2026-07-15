"""CI-Gate für den Fahrzeug-Katalog: Belegpflicht, Vokabular, Plausibilität.

Läuft in der CI (und lokal vor jedem Commit am Seed). Fail closed: ein Fehler
lässt den Build scheitern, statt fragwürdige Daten auszuliefern.

**Was dieses Gate kann — und was nicht.** Es prüft Syntax, Vollständigkeit der
Belege, rechnerische Plausibilität und (bei Motorcodes) ob der Beleg überhaupt
ein Beleg IST:

* **Selbstbeleg-Test:** Der Code muss im eigenen ``quelle_zitat`` vorkommen.
  Real gefangener Fehler: Code ``A14NEL`` mit dem Zitat
  „Motorkennzeichnung | A14XEL | A14XER | …" — der belegte Code steht dort
  gar nicht.
* **Sammelzeilen-Test:** Nennt ein Zitat mehrere Codes, ist es eine
  Tabellen-/Sammelzeile. Genau daraus entstehen die Falschzuordnungen
  (mehrere Motoren teilen sich eine Zeile) — solche Belege werden abgelehnt.

Was es NICHT kann: prüfen, ob eine korrekt zitierte Zuordnung inhaltlich
stimmt. Ein erfundener Code mit plausiblen Zahlen und einer echten URL, der im
Zitat auftaucht, besteht diesen Check. Diese Ebene trägt allein die
adversarische Gegenprüfung der Kuratierung (im Zweifel: Zeile weglassen).

Aufruf:  python tools/check_vehicle_seed.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "src" / "database" / "vehicle_seed.json"

# Vokabular — MUSS mit modules.models übereinstimmen (Wert außerhalb = Zeile
# wäre in der App unbrauchbar bzw. würde den Matcher fehlleiten).
KRAFTSTOFFE = {"benzin", "diesel", "hev", "phev", "elektro", "lpg", "cng"}
MOTORBAUFORMEN = {"r3", "r4", "r5", "r6", "v6", "v8", "v10", "v12",
                  "boxer", "wankel", "emotor"}
AUFLADUNGEN = {"sauger", "turbo", "kompressor", "biturbo"}
PARTIKELFILTER = {"keiner", "dpf", "opf"}
GETRIEBE = {"manuell", "wandler", "dsg", "cvt"}

ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
URL_RE = re.compile(r"^https://")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CODE_RE = re.compile(r"^[A-Z0-9]{3,10}$")
# Wikitext-Reste verraten ein aus einer Tabellenzeile kopiertes „Zitat".
# Solche Zeilen gehören mehreren Motoren gemeinsam — daraus entstehen die
# Falschzuordnungen. Ein sauberes Zitat ist ein lesbarer Satz.
WIKITEXT_RE = re.compile(r"align\s*=|style\s*=|'''|\|\s*colspan|bgcolor|background:")

MIN_ZITAT = 8          # kürzer ist kein Beleg, sondern ein Feigenblatt
JAHR_MIN, JAHR_MAX = 1950, 2030


class Fehler(list):
    def add(self, wo: str, was: str) -> None:
        self.append(f"{wo}: {was}")


def _check_beleg(err: Fehler, wo: str, row: dict, *, zitat: bool) -> None:
    """Belegpflicht — der Kern des Gates."""
    url = str(row.get("quelle_url") or "")
    if not URL_RE.match(url):
        err.add(wo, "quelle_url fehlt oder ist kein https-Link")
    if zitat:
        text = str(row.get("quelle_zitat") or "").strip()
        if len(text) < MIN_ZITAT:
            err.add(wo, f"quelle_zitat fehlt oder ist zu kurz (<{MIN_ZITAT} Zeichen)")
    abruf = row.get("quelle_abruf")
    if abruf is not None and not ISO_RE.match(str(abruf)):
        err.add(wo, "quelle_abruf ist kein ISO-Datum (JJJJ-MM-TT)")


def _check_jahr(err: Fehler, wo: str, row: dict) -> None:
    von, bis = row.get("bj_von"), row.get("bj_bis")
    for name, value in (("bj_von", von), ("bj_bis", bis)):
        if value is None:
            continue
        if not isinstance(value, int) or not (JAHR_MIN <= value <= JAHR_MAX):
            err.add(wo, f"{name}={value!r} ist kein plausibles Baujahr")
    if isinstance(von, int) and isinstance(bis, int) and bis < von:
        err.add(wo, f"bj_bis ({bis}) liegt vor bj_von ({von})")


def main() -> int:
    err = Fehler()
    try:
        data = json.loads(SEED.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"FEHLER: {SEED} unlesbar: {exc}")
        return 1

    marken = {m.get("id"): m for m in data.get("marken", [])}
    baureihen = {b.get("id"): b for b in data.get("baureihen", [])}
    generationen = {g.get("id"): g for g in data.get("generationen", [])}
    motorisierungen = {m.get("id"): m for m in data.get("motorisierungen", [])}
    motorcodes = {c.get("id"): c for c in data.get("motorcodes", [])}

    for name, table in (("marken", data.get("marken", [])),
                        ("baureihen", data.get("baureihen", [])),
                        ("generationen", data.get("generationen", [])),
                        ("motorisierungen", data.get("motorisierungen", [])),
                        ("motorcodes", data.get("motorcodes", []))):
        ids = [r.get("id") for r in table]
        if len(ids) != len(set(ids)):
            dupes = {i for i in ids if ids.count(i) > 1}
            err.add(name, f"doppelte IDs: {sorted(dupes)}")
        for row in table:
            row_id = str(row.get("id") or "")
            if not ID_RE.match(row_id):
                err.add(name, f"ID {row_id!r} verletzt das Schema (a-z0-9-)")

    # --- Marken ---------------------------------------------------------------
    for m in data.get("marken", []):
        wo = f"marke {m.get('id')}"
        if not str(m.get("name") or "").strip():
            err.add(wo, "name fehlt")
        _check_beleg(err, wo, m, zitat=False)

    # --- Baureihen ------------------------------------------------------------
    for b in data.get("baureihen", []):
        wo = f"baureihe {b.get('id')}"
        if b.get("marke_id") not in marken:
            err.add(wo, f"marke_id {b.get('marke_id')!r} existiert nicht")
        _check_beleg(err, wo, b, zitat=False)

    # --- Generationen ---------------------------------------------------------
    for g in data.get("generationen", []):
        wo = f"generation {g.get('id')}"
        if g.get("baureihe_id") not in baureihen:
            err.add(wo, f"baureihe_id {g.get('baureihe_id')!r} existiert nicht")
        _check_beleg(err, wo, g, zitat=False)
        _check_jahr(err, wo, g)

    # --- Motorisierungen ------------------------------------------------------
    for m in data.get("motorisierungen", []):
        wo = f"motorisierung {m.get('id')}"
        gen_id = m.get("generation_id")
        if gen_id not in generationen:
            err.add(wo, f"generation_id {gen_id!r} existiert nicht")
        _check_beleg(err, wo, m, zitat=True)
        _check_jahr(err, wo, m)
        if not str(m.get("anzeigename") or "").strip():
            err.add(wo, "anzeigename fehlt")

        if m.get("kraftstoff") not in KRAFTSTOFFE:
            err.add(wo, f"kraftstoff {m.get('kraftstoff')!r} nicht im Vokabular")
        for feld, erlaubt in (("motorbauform", MOTORBAUFORMEN),
                              ("aufladung", AUFLADUNGEN),
                              ("partikelfilter", PARTIKELFILTER),
                              ("getriebe", GETRIEBE)):
            value = m.get(feld)
            if value is not None and value not in erlaubt:
                err.add(wo, f"{feld}={value!r} nicht im Vokabular")
        di = m.get("direkteinspritzung")
        if di not in (0, 1, None):
            err.add(wo, f"direkteinspritzung={di!r} muss 1, 0 oder null sein")

        ccm, ps = m.get("hubraum_ccm"), m.get("leistung_ps")
        if ccm is not None and not (400 <= ccm <= 8500):
            err.add(wo, f"hubraum_ccm={ccm} unplausibel")
        if ps is not None and not (20 <= ps <= 800):
            err.add(wo, f"leistung_ps={ps} unplausibel")
        # E-Motoren haben keinen Hubraum; Verbrenner brauchen einen.
        if m.get("kraftstoff") == "elektro" and ccm:
            err.add(wo, "elektro mit hubraum_ccm — vermutlich verwechselt")
        # Motorisierungs-Bauzeit muss in der Generation liegen (fängt die
        # „Fitment-Übergeneralisierung" — der einzige maschinell fangbare Fehler).
        gen = generationen.get(gen_id) or {}
        gv, gb = gen.get("bj_von"), gen.get("bj_bis")
        mv, mb = m.get("bj_von"), m.get("bj_bis")
        if isinstance(gv, int) and isinstance(mv, int) and mv < gv - 1:
            err.add(wo, f"bj_von {mv} liegt vor dem Generationsstart {gv}")
        if isinstance(gb, int) and isinstance(mb, int) and mb > gb + 1:
            err.add(wo, f"bj_bis {mb} liegt nach dem Generationsende {gb}")

    # --- Motorcodes -----------------------------------------------------------
    # Alle bekannten Codes: Nennt ein Zitat mehrere davon, stammt es aus einer
    # Sammelzeile. Gegen die echte Code-Liste zu prüfen ist treffsicherer als
    # jede Muster-Heuristik (Motorcodes sehen aus wie normale Abkürzungen).
    alle_codes = {str(c.get("code") or "").upper()
                  for c in data.get("motorcodes", []) if c.get("code")}
    for c in data.get("motorcodes", []):
        wo = f"motorcode {c.get('id')}"
        code = str(c.get("code") or "")
        if not CODE_RE.match(code):
            err.add(wo, f"code {code!r} sieht nicht wie ein Motorcode aus")
        _check_beleg(err, wo, c, zitat=True)
        _check_jahr(err, wo, c)
        lage = c.get("einbaulage")
        if lage is not None and lage not in ("laengs", "quer"):
            err.add(wo, f"einbaulage={lage!r} muss 'laengs' oder 'quer' sein")

        # Selbstbeleg: Steht der Code überhaupt in seinem eigenen Zitat?
        # (Real gefangen: A14NEL mit Zitat „…| A14XEL | A14XER |…")
        zitat = str(c.get("quelle_zitat") or "")
        if code and zitat and code.upper() not in zitat.upper():
            err.add(wo, f"code {code!r} kommt im eigenen quelle_zitat nicht vor "
                        f"— das ist kein Beleg")
        # Sammelzeile: nennt das Zitat weitere bekannte Codes?
        fremde = sorted(k for k in alle_codes
                        if k != code.upper() and k in zitat.upper())
        if len(fremde) >= 2:
            err.add(wo, f"quelle_zitat nennt außerdem {', '.join(fremde[:4])} "
                        f"— Sammelzeile, kein per-Code-Beleg")
        # Wikitext-Reste = aus einer Tabellenzeile kopiert, nicht zitiert.
        if WIKITEXT_RE.search(zitat):
            err.add(wo, "quelle_zitat enthält Wikitext-Tabellensyntax — "
                        "bitte den lesbaren Satz zur Zeile zitieren")

    # --- Verknüpfungen --------------------------------------------------------
    for pair in data.get("motorisierung_motorcode", []):
        if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
            err.add("motorisierung_motorcode", f"ungültiges Paar: {pair!r}")
            continue
        mot_id, code_id = pair
        if mot_id not in motorisierungen:
            err.add("motorisierung_motorcode", f"unbekannte Motorisierung {mot_id!r}")
        if code_id not in motorcodes:
            err.add("motorisierung_motorcode", f"unbekannter Motorcode {code_id!r}")

    # --- Empfehlungs-Katalog gegen Motorfamilien prüfen ------------------------
    # Eine Regel, die auf eine nirgends definierte Motorfamilie zeigt, wäre
    # stumm — das ist ein Fehler, kein Feature.
    rec_seed = ROOT / "src" / "database" / "catalog_seed.json"
    try:
        rec = json.loads(rec_seed.read_text(encoding="utf-8"))
        familien = {str(c.get("motorfamilie")) for c in data.get("motorcodes", [])
                    if c.get("motorfamilie")}
        codes = {str(c.get("code", "")).upper() for c in data.get("motorcodes", [])}
        for item in rec.get("items", []):
            cond = item.get("bedingungen") or {}
            for fam in cond.get("motorfamilie", []) or []:
                if fam not in familien:
                    err.add(f"empfehlung {item.get('id')}",
                            f"motorfamilie {fam!r} existiert im Fahrzeug-Katalog nicht")
            for code in cond.get("motorcode", []) or []:
                if str(code).upper() not in codes:
                    err.add(f"empfehlung {item.get('id')}",
                            f"motorcode {code!r} existiert im Fahrzeug-Katalog nicht")
    except (OSError, ValueError):
        pass  # der Empfehlungs-Seed hat sein eigenes Gate

    counts = (f"{len(marken)} Marken, {len(baureihen)} Baureihen, "
              f"{len(generationen)} Generationen, {len(motorisierungen)} Motorisierungen, "
              f"{len(motorcodes)} Motorcodes")
    if err:
        print(f"Fahrzeug-Katalog FEHLERHAFT ({counts}) — {len(err)} Beanstandung(en):")
        for line in err[:60]:
            print("  -", line)
        if len(err) > 60:
            print(f"  … und {len(err) - 60} weitere")
        return 1
    print(f"Fahrzeug-Katalog ok: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
