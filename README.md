# KFZ-Manager

Lokaler, offline-first Autoliebhaber-Hub für Windows und macOS: Tankbuch,
Kosten, Termine, Pflegeplaner mit Intervall-Prognose, regelbasierte
Pflege-Empfehlungen und ein digitales Scheckheft mit Foto-/PDF-Anhängen —
alle Daten bleiben auf dem eigenen Gerät.

## Funktionen

- **Fahrzeuge** — beliebig viele Fahrzeuge mit ausführlichem Profil
  (Kraftstoffart, Motorbauform, Aufladung, Direkteinspritzung, Partikelfilter,
  Getriebe, Öl-Freigabe, Fahrprofil …); globaler Umschalter in der Toolbar.
- **Tank- & Ladebuch** — Verbrenner (l/100 km nach Voll-zu-voll-Methode,
  Teilbetankungen werden korrekt verrechnet) und Elektro/Plug-in
  (kWh/100 km, Ladeort). Kosten/km automatisch; die km-Stände werden monoton
  validiert und speisen die Fälligkeits-Prognosen.
- **Kosten** — Einträge je Fahrzeug mit Kategorie und Monatsübersicht.
- **Termine & Erinnerungen** — TÜV/HU, Inspektion, Versicherung,
  Reifenwechsel und eigene Typen; fällig per Datum und/oder km-Stand,
  Erinnerung beim Programmstart mit einstellbarem Vorlauf.
- **Pflegeplaner** — Regeln wie „alle 15.000 km oder 12 Monate — was zuerst
  eintritt“. Der kalendarische Rechner leitet aus der Fahrleistung der
  letzten ~90 Tage ein konkretes Datum ab: „fällig in ca. 1.800 km ≈
  voraussichtlich 03.09.2026“. Erledigen setzt das Intervall zurück, bucht
  optional die Kosten und schreibt ins Scheckheft.
- **Empfehlungen** — kuratierter, komplett offline arbeitender Katalog
  (40+ Einträge inkl. E-Auto- und Hybrid-Pflege), regelbasiert gegen das
  Fahrzeugprofil gefiltert; per Klick in den Pflegeplan übernehmbar,
  ausblendbar, um eigene Einträge erweiterbar. Empfehlungen ersetzen keine
  Herstellervorgaben.
- **Digitales Scheckheft** — chronologische Historie je Fahrzeug; Anhänge
  (JPG/PNG/WebP/HEIC/PDF, bis 25 MB) werden in den Datenordner kopiert,
  Bilder mit Vorschau.
- **Datensicherung** — automatisches tägliches Backup (Datenbank **und**
  Anhänge in einem Archiv), manuelle Sicherung und Wiederherstellung,
  Wiederherstellungs-Angebot bei beschädigter Datenbank.
- **Auto-Update** — prüft GitHub-Releases, verifiziert Prüfsumme und
  Signatur und installiert auf Wunsch vollautomatisch.
- **App-Familie** — erkennt den [HaushaltsManager](https://github.com/huliguli/HaushaltsManager)
  und verzahnt sich über eine schreibgeschützte Interop-Schicht
  (Details in [INTEROP.md](INTEROP.md)).

## Installation

**Windows:** `KFZManager-Setup.exe` aus dem neuesten
[Release](../../releases/latest) herunterladen und ausführen (Installation
per Benutzer, keine Adminrechte nötig).

**macOS:** `KFZManager-macOS.dmg` laden, öffnen und die App nach
`Programme` ziehen. Beim ersten Start ggf. Rechtsklick → „Öffnen“.

Die Daten liegen unter `%APPDATA%\KFZManager` (Windows) bzw.
`~/Library/Application Support/KFZManager` (macOS).

## Aus dem Quellcode starten

```powershell
# Windows
.\run.ps1
```

```bash
# macOS/Linux
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python src/main.py
```

Tests: `python -m pytest`

## Build

- Windows: `.\build.ps1` (PyInstaller onedir + Inno-Setup-Installer),
  optional `-Sign` mit eigenem Zertifikat (`tools\make-cert.ps1`,
  Details in [SIGNING.md](SIGNING.md)).
- macOS: `./build-mac.sh` (ad-hoc-signierte .app in einem .dmg).

## Technik

Python · PyQt6 · SQLite (alle Geldbeträge als Integer-Cent, Mengen als
Milliliter/Wattstunden). Keine Cloud, keine Telemetrie, kein Konto.

## Lizenz

Privat genutztes Werkzeug; Oberfläche mit PyQt6 (GPL v3). Der Quellcode
dieses Repositories steht unter der [GPL v3](https://www.gnu.org/licenses/gpl-3.0.html).
