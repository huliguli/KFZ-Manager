# Quellen und Lizenzen der mitgelieferten Katalogdaten

Der KFZ-Manager liefert zwei Referenz-Datensätze mit. Beide sind frei
lizenziert; dieses Dokument hält Herkunft, Lizenz und Stand fest — und ist
zugleich der geforderte Quellenvermerk.

> **Angaben ohne Gewähr.** Katalogdaten sind Vorschläge zur Vorbelegung.
> Maßgeblich sind immer Fahrzeugschein, Serviceheft und die Angaben des
> Herstellers.

## 1. HSN/TSN-Schlüsselnummern (`kba_seed.csv.gz`)

- **Quelle:** Kraftfahrt-Bundesamt (KBA), Statistik **FZ 6** — „Bestand an
  Kraftfahrzeugen und Kraftfahrzeuganhängern nach Herstellern und Typen",
  Stand 1. Januar 2025, veröffentlicht am 11. April 2025.
- **Bezug:** <https://www.kba.de/DE/Statistik/Produktkatalog/produkte/Fahrzeuge/fz6>
- **Lizenz:** **Datenlizenz Deutschland – Namensnennung – Version 2.0**
  (<https://www.govdata.de/dl-de/by-2-0>) — erlaubt Weiterverbreitung und
  Veränderung, auch kommerziell, solange der Quellenvermerk erhalten bleibt.
  Die Lizenzangabe steht wörtlich im Impressum der Original-Datei.
- **Quellenvermerk:** © Kraftfahrt-Bundesamt, Flensburg — FZ 6, Stand
  01.01.2025; Datenlizenz Deutschland – Namensnennung – Version 2.0.
- **Veränderung gegenüber dem Original:** Aus der XLSX wurden die Spalten
  HSN, Herstellerklartext, TSN und Handelsname übernommen und als
  gzip-komprimierte CSV gespeichert; die Bestandszahlen (Spalte „Anzahl")
  wurden nicht übernommen. Erzeugt mit `tools/build_kba_seed.py`.
- **Aktualisierung:** FZ 6 erscheint jährlich; beim Neuziehen den Stand hier
  mitführen.

## 2. Fahrzeug-Katalog (`vehicle_seed.json`)

- **Inhalt:** Marken, Baureihen, Generationen, Motorisierungen und — nur als
  Vorschlag — Motorkennbuchstaben (Motorcodes).
- **Herkunft:** handkuratiert. **Jede Zeile trägt die URL ihrer Quelle und ein
  wörtliches Zitat** (`quelle_url`, `quelle_zitat`, `quelle_abruf`); der
  CI-Check `tools/check_vehicle_seed.py` weist Zeilen ohne Beleg zurück.
  Überwiegend genutzt: die deutschsprachige Wikipedia (Fahrzeug- und
  Motorartikel, Lizenz CC BY-SA 4.0) — übernommen werden ausschließlich
  **einzelne technische Fakten** (Hubraum, Leistung, Bauzeitraum), die als
  solche keinen Urheberrechtsschutz genießen; Texte werden nicht kopiert.
- **Markennamen** („Audi", „BMW", …) werden ausschließlich als beschreibende
  Wortangabe verwendet, um Fahrzeuge benennen zu können (§ 23 Abs. 1 Nr. 3
  MarkenG). Es werden **keine Logos oder Wort-/Bildmarken** mitgeliefert. Alle
  genannten Marken sind Eigentum der jeweiligen Rechteinhaber; es besteht
  keine Verbindung zu ihnen.

### Warum Motorcodes nur Vorschläge sind

Die Zuordnung „Modell + Motorisierung → Motorcode" ist **nicht eindeutig**:
Ein Audi A4 B8 „1.8 TFSI mit 160 PS" kann den Motorcode **CABB** (EA888 Gen1)
oder **CDHB** (Gen2) tragen — identischer Hubraum, identische Leistung,
identisches Fahrzeug, unterscheidbar nur über das Baujahr. Ein geratener Code
würde falsche Wartungsempfehlungen auslösen, die sich für den Nutzer nicht als
falsch erkennen lassen. Deshalb gilt in dieser App ausnahmslos:

1. Der Katalog **fragt** („Vermutlich CDHB — steht das in Ihrem Schein?").
2. Der Nutzer **bestätigt** (Zulassungsbescheinigung Feld D.2, CoC-Papier,
   Serviceheft oder Prägung am Motorblock).
3. Erst ein bestätigter Code (`motorcode_herkunft = 'nutzer'`) schaltet
   motorcode-spezifische Empfehlungen frei.

Sind mehrere Codes möglich, zeigt die App **alle** zur Auswahl und wählt
keinen vor. „Weiß ich nicht" ist ein vollwertiger Ausgang — es entfallen
lediglich die motorcode-abhängigen Empfehlungen.
