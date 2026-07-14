# Changelog

Alle nennenswerten Änderungen dieses Projekts. Das Format folgt
[Keep a Changelog](https://keepachangelog.com/de/), die Versionierung
[SemVer](https://semver.org/lang/de/).

## [1.0.0] – 2026-07-14

Erstes Release.

### Hinzugefügt
- Fahrzeugverwaltung mit ausführlichem Profil (Kraftstoffart, Motorbauform,
  Aufladung, Direkteinspritzung, Partikelfilter, Getriebe, Antrieb,
  Öl-Viskosität/-Freigabe, Fahrprofil) und globalem Fahrzeug-Umschalter.
- Erster-Start-Assistent zum Anlegen eines oder mehrerer Fahrzeuge.
- Tank- & Ladebuch: Verbrauch l/100 km (Voll-zu-voll inkl. Teilbetankungen),
  kWh/100 km für Elektro/Plug-in, Kosten/km, €-je-Einheit-Vorschau,
  monotone km-Stand-Validierung mit Korrekturmöglichkeit.
- Kostenmodul mit Kategorien und Monatsübersicht je Fahrzeug.
- Termine (TÜV/HU, Inspektion, Versicherung, Reifenwechsel, eigene Typen)
  fällig per Datum und/oder km-Stand; Erinnerung beim Start mit
  einstellbarem Vorlauf (Tage und Kilometer).
- Pflegeplaner: Intervall-Regeln „alle X km und/oder alle Y Monate — was
  zuerst eintritt“ mit kalendarischer Prognose aus der Ø-Fahrleistung der
  letzten ~90 Tage; Erledigen-Dialog mit Intervall-Reset, optionalem
  Kosteneintrag und Scheckheft-Übernahme.
- Empfehlungs-Katalog (regelbasiert, offline): 42 kuratierte Einträge
  inklusive dedizierter E-Auto- und Hybrid-Pflege, gefiltert nach
  Fahrzeugprofil; Übernahme in den Pflegeplan, Ausblenden je Fahrzeug,
  eigene Einträge; Seed-Updates mergen additiv und überschreiben nie
  Nutzerdaten.
- Digitales Scheckheft: gemeinsame Zeitleiste aus Pflege, Wartung und
  manuellen Einträgen; Anhänge (JPG/PNG/WebP/HEIC/PDF, max. 25 MB) mit
  Bildvorschau, gehärtetem Dateispeicher und Aufräumlauf beim Start.
- Datensicherung: tägliches Auto-Backup sowie manuelles Backup/Restore —
  jeweils Datenbank und Anhänge in einem Archiv; Wiederherstellung bei
  beschädigter Datenbank.
- Auto-Update über GitHub-Releases mit Prüfsummen-Verifikation und
  signatur-gepinntem Installer (optional vollautomatisch).
- Interop-Schicht der App-Familie: Familienordner-Ankündigung,
  `interop_*`-Views für den HaushaltsManager, vorbereitete
  Haushalts-Budget-Kachel (aktiviert sich mit HaushaltsManager v3.6);
  Spezifikation in INTEROP.md.
- Helles und dunkles Design, Tastatur-Navigation (Strg+1…9, Strg+N,
  Strg+Tab), Windows- und macOS-Build aus derselben Codebasis.
