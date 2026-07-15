"""Führt die je Baureihe kuratierten Teil-Dateien zum vehicle_seed.json zusammen.

Die Kuratierung läuft pro Baureihe und liefert Generationen, Motorisierungen und
(nur wo belegbar) Motorcodes. Dieses Skript setzt die Teile zusammen, leitet
Marken/Baureihen aus den IDs ab und schreibt den Seed — deterministisch
sortiert, damit Diffs lesbar bleiben.

Aufruf:  python tools/merge_catalog_parts.py <verzeichnis-mit-teil-jsons>
Danach IMMER: python tools/check_vehicle_seed.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "database" / "vehicle_seed.json"

# Wikitext-Reste verraten ein aus einer Tabellenzeile kopiertes „Zitat".
WIKITEXT_RE = re.compile(r"align\s*=|style\s*=|'''|\|\s*colspan|bgcolor|background:")

# Anzeigenamen der Marken (die IDs kommen aus den kuratierten Datensätzen).
MARKEN_NAMEN = {
    "vw": "Volkswagen", "audi": "Audi", "skoda": "Škoda", "seat": "SEAT",
    "bmw": "BMW", "mercedes": "Mercedes-Benz", "opel": "Opel", "ford": "Ford",
    "renault": "Renault", "toyota": "Toyota",
}

# Baureihen, deren Schreibweise sich nicht aus der ID ableiten lässt
# (Markenschreibweise schlägt jede Automatik).
BAUREIHEN_NAMEN = {
    "vw-up": "up!", "vw-t-roc": "T-Roc", "vw-t-cross": "T-Cross",
    "mercedes-c-klasse": "C-Klasse", "mercedes-a-klasse": "A-Klasse",
    "mercedes-e-klasse": "E-Klasse", "mercedes-b-klasse": "B-Klasse",
    "opel-corsa": "Corsa", "opel-astra": "Astra",
}


def _baureihe_name(baureihe_id: str, marke_id: str) -> str:
    """Anzeigename einer Baureihe aus ihrer ID (mit Ausnahmen-Tabelle).

    Bindestriche bleiben erhalten („t-roc" → „T-Roc", nicht „T Roc"); kurze
    Teile bleiben groß („a4" → „A4").
    """
    if baureihe_id in BAUREIHEN_NAMEN:
        return BAUREIHEN_NAMEN[baureihe_id]
    rest = baureihe_id[len(marke_id) + 1:]
    return "-".join(w.upper() if len(w) <= 2 else w.capitalize()
                    for w in rest.split("-"))


def _first_url(rows: list[dict]) -> str:
    for row in rows:
        url = str(row.get("quelle_url") or "")
        if url.startswith("https://"):
            return url
    return ""


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    parts_dir = Path(sys.argv[1])
    if not parts_dir.is_dir():
        raise SystemExit(f"Kein Verzeichnis: {parts_dir}")

    generationen: dict[str, dict] = {}
    motorisierungen: dict[str, dict] = {}
    motorcodes: dict[str, dict] = {}
    links: set[tuple[str, str]] = set()

    for file in sorted(parts_dir.glob("*.json")):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except ValueError as exc:
            print(f"  übersprungen (kaputt): {file.name} — {exc}")
            continue
        for g in data.get("generationen") or []:
            if g.get("id"):
                generationen[g["id"]] = g
        for m in data.get("motorisierungen") or []:
            if m.get("id"):
                motorisierungen[m["id"]] = m
        for c in data.get("motorcodes") or []:
            if c.get("id"):
                motorcodes[c["id"]] = c
        for pair in data.get("motorisierung_motorcode") or []:
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                links.add((str(pair[0]), str(pair[1])))

    # Marken/Baureihen aus den Generations-IDs ableiten: 'audi-a4-b8' ->
    # baureihe 'audi-a4' -> marke 'audi'. Die Quelle der Generation gilt auch
    # für ihre Baureihe (dieselbe Fahrzeugseite).
    baureihen: dict[str, dict] = {}
    marken: dict[str, dict] = {}
    for g in generationen.values():
        b_id = str(g.get("baureihe_id") or "")
        if not b_id:
            continue
        marke_id = b_id.split("-")[0]
        if b_id not in baureihen:
            baureihen[b_id] = {
                "id": b_id, "marke_id": marke_id,
                "name": _baureihe_name(b_id, marke_id),
                "quelle_url": g.get("quelle_url", ""),
            }
        if marke_id not in marken:
            marken[marke_id] = {
                "id": marke_id,
                "name": MARKEN_NAMEN.get(marke_id, marke_id.capitalize()),
                "quelle_url": g.get("quelle_url", ""),
                "quelle_abruf": "2026-07-14",
            }

    # --- Belegschwache Motorcodes verwerfen (fail closed) --------------------
    # Ein Motorcode darf nur bleiben, wenn sein Zitat ihn selbst nennt und
    # NICHT aus einer Sammelzeile stammt (mehrere Codes / Wikitext-Tabelle).
    # Genau dort entstehen die Falschzuordnungen: Real gefangen wurde „A14NEL"
    # mit dem Zitat „…| A14XEL | A14XER |…" — der belegte Code kam darin gar
    # nicht vor. Lieber gar kein Code als ein falscher: ein falscher Code löst
    # eine falsche Wartungsempfehlung aus, die der Nutzer nicht als falsch
    # erkennen kann.
    alle_codes = {str(c.get("code") or "").upper() for c in motorcodes.values()}
    verworfen: list[str] = []
    for code_id, c in list(motorcodes.items()):
        code = str(c.get("code") or "").upper()
        zitat = str(c.get("quelle_zitat") or "")
        gruende = []
        if code and code not in zitat.upper():
            gruende.append("Code steht nicht im eigenen Zitat")
        fremde = [k for k in alle_codes if k != code and k in zitat.upper()]
        if len(fremde) >= 2:
            gruende.append(f"Sammelzeile (nennt auch {', '.join(sorted(fremde)[:3])})")
        if WIKITEXT_RE.search(zitat):
            gruende.append("Wikitext-Tabellenzeile statt Zitat")
        if gruende:
            del motorcodes[code_id]
            verworfen.append(f"{code}: {'; '.join(gruende)}")

    # Verwaiste Verknüpfungen entfernen (Codes oben verworfen, oder eine
    # Prüfung hat eine Motorisierung entfernt).
    links = {(m, c) for (m, c) in links
             if m in motorisierungen and c in motorcodes}

    if verworfen:
        print(f"\n{len(verworfen)} Motorcode(s) ohne tragfähigen Beleg verworfen:")
        for line in verworfen[:12]:
            print(f"  - {line}")
        if len(verworfen) > 12:
            print(f"  … und {len(verworfen) - 12} weitere")
        print()

    seed = {
        "comment": ("Fahrzeug-Katalog: Marke -> Baureihe -> Generation -> Motorisierung, "
                    "zur VORBELEGUNG des Fahrzeugprofils. Jede Zeile traegt Quelle + "
                    "woertliches Zitat (CI-Gate tools/check_vehicle_seed.py). Motorcodes "
                    "sind ausschliesslich VORSCHLAEGE zum Bestaetigen - die Zuordnung "
                    "Motorisierung->Code ist mehrdeutig, deshalb setzt die App nie selbst "
                    "einen Code. Lizenz/Quellen: siehe src/database/KATALOG-QUELLEN.md"),
        "katalog_version": 1,
        "marken": sorted(marken.values(), key=lambda r: r["id"]),
        "baureihen": sorted(baureihen.values(), key=lambda r: r["id"]),
        "generationen": sorted(generationen.values(), key=lambda r: r["id"]),
        "motorisierungen": sorted(motorisierungen.values(), key=lambda r: r["id"]),
        "motorcodes": sorted(motorcodes.values(), key=lambda r: r["id"]),
        "motorisierung_motorcode": sorted(list(pair) for pair in links),
    }
    OUT.write_text(json.dumps(seed, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    print(f"{len(marken)} Marken, {len(baureihen)} Baureihen, "
          f"{len(generationen)} Generationen, {len(motorisierungen)} Motorisierungen, "
          f"{len(motorcodes)} Motorcodes, {len(links)} Verknuepfungen -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
