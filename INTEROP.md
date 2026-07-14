# Interop-Schicht der App-Familie

KFZ-Manager und HaushaltsManager sind vollständig eigenständige Desktop-Apps,
die sich gegenseitig erkennen und über eine schmale, versionierte
Interop-Schicht verzahnen. Dieses Dokument ist der **Vertrag** zwischen den
Apps — beide Seiten implementieren ausschließlich, was hier steht.

## Grundprinzipien

1. **Vertrag statt Tabellen-Zugriff.** Eine App liest von ihrer Schwester
   ausschließlich die Tabelle `interop_meta` und die `interop_*`-SQL-Views.
   Private Tabellen sind tabu — sie dürfen sich jederzeit ändern.
2. **Strikt read-only.** Fremde Datenbanken werden nur mit
   `file:…?mode=ro` (URI) und gesetztem `busy_timeout` geöffnet. Es wird nie
   in die Schwester-DB geschrieben.
3. **Fail silent.** Jeder Fehlerpfad (Ordner fehlt, JSON kaputt, DB gesperrt
   oder fehlend, WAL-Read-only-Sonderfall) deaktiviert die Integration still
   für die laufende Sitzung. Eine App darf wegen der Integration niemals
   abstürzen oder den Start verweigern.
4. **Versionierter Handshake.** Integration nur bei gleicher
   interop_version-Major (die Version ist eine ganze Zahl → die Zahl ist die
   Major). Bei Abweichung zeigt die App den Hinweis „Bitte <App>
   aktualisieren“ und lässt die Integration aus.

## Erkennung: Familienordner

Neben den Datenordnern der Apps liegt der gemeinsame Familienordner
(gleiche Plattformlogik wie die Datenordner):

| Plattform | Pfad |
| --- | --- |
| Windows | `%APPDATA%\AppFamilie\` |
| macOS | `~/Library/Application Support/AppFamilie/` |
| Linux | `$XDG_DATA_HOME/AppFamilie/` (Fallback `~/.local/share/AppFamilie/`) |

Jede App schreibt dort **bei jedem Start** ihre Ankündigungsdatei
(`kfzmanager.json` bzw. `haushaltsmanager.json`):

```json
{
  "app_name": "KFZManager",
  "app_version": "1.0.0",
  "interop_version": 1,
  "db_path": "C:\\Users\\...\\AppData\\Roaming\\KFZManager\\kfz.db",
  "updated_at": "2026-07-14T12:00:00+00:00"
}
```

## interop_version 1 — was der KFZ-Manager bereitstellt

In der eigenen DB (`kfz.db`) pflegt der KFZ-Manager:

```sql
CREATE TABLE interop_meta (interop_version INTEGER NOT NULL);  -- genau 1 Zeile, Wert 1
```

und diese stabilen Views:

### `interop_fahrzeuge`

| Spalte | Typ | Bedeutung |
| --- | --- | --- |
| `id` | INTEGER | Fahrzeug-ID (stabil) |
| `name` | TEXT | Anzeigename |
| `antrieb` | TEXT | `benzin/diesel/hev/phev/elektro/lpg/cng/unbekannt` |

### `interop_kosten_monat`

| Spalte | Typ | Bedeutung |
| --- | --- | --- |
| `fahrzeug_id` | INTEGER | Bezug auf `interop_fahrzeuge.id` |
| `jahr` | INTEGER | z. B. 2026 |
| `monat` | INTEGER | 1–12 |
| `kategorie` | TEXT | Werkstatt/Versicherung/Steuer/Pflege/Zubehör/Kraftstoff/Strom/Sonstiges |
| `betrag_cent` | INTEGER | Monatssumme der Kategorie in **Cent** |

### `interop_termine`

| Spalte | Typ | Bedeutung |
| --- | --- | --- |
| `fahrzeug_id` | INTEGER | Bezug auf `interop_fahrzeuge.id` |
| `typ` | TEXT | TÜV/HU, Inspektion, Versicherung, Reifenwechsel, … |
| `faellig_datum` | TEXT | ISO `YYYY-MM-DD` oder NULL |
| `faellig_km` | INTEGER | km-Fälligkeit oder NULL |
| `beschreibung` | TEXT | Anzeigetext |

Nur offene (nicht erledigte) Termine erscheinen in der View.

## interop_version 1 — Gegenstück des HaushaltsManagers (ab v3.6)

Der HaushaltsManager v3.5 hat noch **keine** Interop-Schicht. Der KFZ-Manager
erkennt diesen Zustand (Datenordner `HaushaltsManager` mit `haushalt.db`
vorhanden, aber keine `haushaltsmanager.json`) und zeigt dezent:
„Integration verfügbar ab HaushaltsManager v3.6“.

Für v3.6 stellt der HaushaltsManager mindestens bereit:

```sql
CREATE TABLE interop_meta (interop_version INTEGER NOT NULL);  -- genau 1 Zeile, Wert 1
```

### `interop_ausgaben_monat` (Pflicht)

| Spalte | Typ | Bedeutung |
| --- | --- | --- |
| `jahr` | INTEGER | z. B. 2026 |
| `monat` | INTEGER | 1–12 |
| `summe_cent` | INTEGER | Gesamtausgaben des Monats in **Cent** (Fixkosten + variable Ausgaben) |

Zusätzlich schreibt er bei jedem Start `haushaltsmanager.json` in den
Familienordner (Schema wie oben, `app_name: "HaushaltsManager"`).

**Verwendung im KFZ-Manager (bereits fertig verdrahtet):** Die
Budget-Kontext-Kachel auf dem Dashboard rechnet
„Fahrzeugkosten = X % deiner Monatsausgaben“ aus `interop_kosten_monat`
(eigene DB) und `interop_ausgaben_monat` (Schwester). Sie erscheint
automatisch, sobald der HaushaltsManager seine Views liefert — im
KFZ-Manager ist dafür kein Update nötig.

**Verwendung im HaushaltsManager (geplant):** Budget-Kachel bzw.
Kategorie-Drilldown „Auto“ kann `interop_kosten_monat` und
`interop_termine` des KFZ-Managers anzeigen (z. B. „nächster TÜV am …“).

## Regeln für zukünftige Versionen

* **Additiv erweitern:** Neue Spalten/Views innerhalb derselben
  interop_version sind erlaubt; bestehende Spalten dürfen weder umbenannt
  noch entfernt oder umgedeutet werden.
* **Breaking Change ⇒ Version hochzählen** (2, 3, …). Beide Apps zeigen bei
  einem Major-Mismatch nur den Aktualisieren-Hinweis.
* Geldbeträge sind **immer INTEGER Cent**, Daten immer ISO-Strings —
  identisch zur internen Konvention beider Apps.
