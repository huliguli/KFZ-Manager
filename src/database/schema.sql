-- ==========================================================================
--  KFZ-Manager — SQLite schema
--  RULE: every monetary value is stored as INTEGER cents (never REAL/float).
--  Quantities follow the same discipline: fuel in millilitres, energy in
--  watt-hours — INTEGER everywhere, floats only at the display boundary.
--  Dates are ISO-8601 strings (YYYY-MM-DD).
-- ==========================================================================

PRAGMA foreign_keys = ON;

-- Schema version for forward-compatible migrations.
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

-- --- Vehicles ---------------------------------------------------------------
-- The profile fields drive the recommendation matcher (modules.catalog);
-- everything except name is optional so a quick start never blocks on data
-- the user does not know offhand.
CREATE TABLE IF NOT EXISTS vehicles (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    name               TEXT    NOT NULL,               -- Spitzname/Anzeige
    hersteller         TEXT,
    modell             TEXT,
    erstzulassung      TEXT,                           -- ISO, optional
    kennzeichen        TEXT,
    km_stand           INTEGER,                        -- zuletzt bekannter km-Stand
    km_stand_datum     TEXT,                           -- ISO; wann erfasst
    kraftstoff         TEXT,   -- benzin|diesel|hev|phev|elektro|lpg|cng
    motorbauform       TEXT,   -- r3|r4|r5|r6|v6|v8|v10|v12|boxer|wankel|emotor
    hubraum_ccm        INTEGER,
    leistung_ps        INTEGER,
    aufladung          TEXT,   -- sauger|turbo|kompressor|biturbo
    direkteinspritzung INTEGER,                        -- 1/0, NULL = unbekannt
    partikelfilter     TEXT,   -- keiner|dpf|opf, NULL = unbekannt
    getriebe           TEXT,   -- manuell|wandler|dsg|cvt
    antrieb            TEXT,   -- fwd|rwd|awd
    oel_viskositaet    TEXT,   -- z. B. 5W-30
    oel_freigabe       TEXT,   -- z. B. VW 507 00
    fahrprofil         TEXT,   -- kurzstrecke|mix|langstrecke
    notiz              TEXT,
    -- v2, Fahrzeug-Katalog: Herkunft der Profildaten (alle optional, NULL =
    -- vollständig manuell angelegt).
    katalog_motorisierung_id TEXT,          -- gewählte Katalog-Motorisierung
    motorcode          TEXT,                -- z. B. 'CDHB'
    motorcode_herkunft TEXT,                -- 'nutzer' | NULL — NIE 'katalog'!
    profil_dirty       TEXT,                -- JSON-Array manuell geänderter Felder
    active             INTEGER NOT NULL DEFAULT 1,
    created_at         TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- --- Tank-/Ladebuch -----------------------------------------------------------
-- One table for both drivetrains: art='kraftstoff' rows carry menge_ml,
-- art='strom' rows carry energie_wh. The odometer column doubles as the
-- app-wide km history (validated monotonically per vehicle in the UI) that
-- feeds the due-date forecaster (modules.fuel / modules.intervals).
CREATE TABLE IF NOT EXISTS tank_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id  INTEGER NOT NULL,
    date        TEXT    NOT NULL,                      -- ISO YYYY-MM-DD
    odo_km      INTEGER NOT NULL,
    art         TEXT    NOT NULL DEFAULT 'kraftstoff', -- kraftstoff|strom
    menge_ml    INTEGER,                               -- Liter * 1000 (kraftstoff)
    energie_wh  INTEGER,                               -- kWh * 1000 (strom)
    betrag_cent INTEGER NOT NULL DEFAULT 0,
    voll        INTEGER NOT NULL DEFAULT 1,            -- Vollbetankung (kraftstoff)
    ladeort     TEXT,                                  -- heim|ac|dc (strom)
    notiz       TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE CASCADE
);

-- --- Kosten -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS costs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id  INTEGER NOT NULL,
    date        TEXT    NOT NULL,                      -- ISO YYYY-MM-DD
    kategorie   TEXT    NOT NULL DEFAULT 'Sonstiges',
    betrag_cent INTEGER NOT NULL DEFAULT 0,
    notiz       TEXT,
    odo_km      INTEGER,                               -- optional
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE CASCADE
);

-- --- Termine & Erinnerungen -----------------------------------------------------
-- Due by date and/or by odometer (whichever applies first). erledigt keeps the
-- row for the history; completing may create a Scheckheft entry.
CREATE TABLE IF NOT EXISTS appointments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id      INTEGER NOT NULL,
    typ             TEXT    NOT NULL DEFAULT 'Sonstiges', -- TÜV/HU, Inspektion, ...
    beschreibung    TEXT,
    faellig_datum   TEXT,                              -- ISO, optional
    faellig_km      INTEGER,                           -- optional
    erledigt        INTEGER NOT NULL DEFAULT 0,
    erledigt_datum  TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE CASCADE
);

-- --- Pflegeplan: Intervall-Regeln --------------------------------------------------
-- Rule: due every X km AND/OR every Y months — whatever comes first, measured
-- from the last completion (letzte_datum/letzte_km). catalog_id links a rule
-- adopted from the recommendation catalog to its stable seed id.
CREATE TABLE IF NOT EXISTS care_rules (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id        INTEGER NOT NULL,
    catalog_id        TEXT,                            -- optional Katalog-Herkunft
    name              TEXT    NOT NULL,
    kategorie         TEXT    NOT NULL DEFAULT 'Allgemein',
    intervall_km      INTEGER,                         -- NULL = keine km-Regel
    intervall_monate  INTEGER,                         -- NULL = keine Zeitregel
    letzte_datum      TEXT,                            -- ISO; letzte Durchführung
    letzte_km         INTEGER,
    notiz             TEXT,
    aktiv             INTEGER NOT NULL DEFAULT 1,
    created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE CASCADE
);

-- --- Digitales Scheckheft ------------------------------------------------------------
-- Chronological per-vehicle history: care completions, maintenance and manual
-- entries share one timeline. cost_id links the cost row a completion created.
CREATE TABLE IF NOT EXISTS logbook_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id  INTEGER NOT NULL,
    date        TEXT    NOT NULL,                      -- ISO YYYY-MM-DD
    odo_km      INTEGER,
    art         TEXT    NOT NULL DEFAULT 'wartung',    -- pflege|wartung|sonstiges
    titel       TEXT    NOT NULL,
    beschreibung TEXT,
    kosten_cent INTEGER,                               -- optional (Anzeige)
    cost_id     INTEGER,                               -- verknüpfter Kosteneintrag
    rule_id     INTEGER,                               -- erzeugende Pflege-Regel
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE CASCADE,
    FOREIGN KEY (cost_id) REFERENCES costs(id) ON DELETE SET NULL,
    FOREIGN KEY (rule_id) REFERENCES care_rules(id) ON DELETE SET NULL
);

-- --- Anhänge (Fotos/PDFs) ---------------------------------------------------------
-- Files are COPIED into <data_dir>/attachments/<vehicle_id>/ with a generated
-- safe filename; the DB stores the path relative to the data dir. Hardening
-- (extension whitelist, size limit, traversal-safe names) lives in
-- modules.attachments; an orphan sweep runs at startup.
CREATE TABLE IF NOT EXISTS attachments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id    INTEGER NOT NULL,
    entry_kind    TEXT    NOT NULL,                    -- 'logbook' | 'cost'
    entry_id      INTEGER NOT NULL,
    rel_path      TEXT    NOT NULL,                    -- relativ zum Datenordner
    original_name TEXT    NOT NULL,
    size_bytes    INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE CASCADE,
    UNIQUE (rel_path)
);

-- --- Empfehlungs-Katalog -------------------------------------------------------------
-- Seeded from the bundled catalog_seed.json (additive merge by stable id, see
-- modules.catalog: user rows and hides are NEVER overwritten by seed updates).
CREATE TABLE IF NOT EXISTS catalog_items (
    id                TEXT PRIMARY KEY,                -- stabile ID (seed-* / user-*)
    name              TEXT    NOT NULL,
    kategorie         TEXT    NOT NULL DEFAULT 'Allgemein',
    bedingungen_json  TEXT    NOT NULL DEFAULT '{}',   -- Matcher-Bedingungen
    intervall_km      INTEGER,
    intervall_monate  INTEGER,
    warum             TEXT,                            -- Erklärtext
    produkt_beispiel  TEXT,                            -- nur reale Produkte
    quelle            TEXT    NOT NULL DEFAULT 'seed', -- 'seed' | 'user'
    created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Per-vehicle hidden suggestions (survive seed updates by design).
CREATE TABLE IF NOT EXISTS catalog_hidden (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id INTEGER NOT NULL,
    catalog_id TEXT    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE CASCADE,
    UNIQUE (vehicle_id, catalog_id)
);

-- --- Fahrzeug-Katalog (schema v2) --------------------------------------------------
-- Zweck: Beim Anlegen eines Fahrzeugs sollen Marke/Baureihe/Motorisierung
-- auswählbar sein und die Profilfelder VORBELEGEN, statt sie abzutippen.
--
-- Vertrauensmodell (Kern des ganzen Katalogs!):
--   * Katalogdaten sind VORSCHLÄGE — sichtbar, editierbar, ohne Gewähr.
--   * Der MOTORCODE wird NIE aus dem Katalog abgeleitet: die Zuordnung
--     Motorisierung→Code ist nachweislich mehrdeutig (z. B. Audi A4 B8
--     „1.8 TFSI 160 PS" = CABB ODER CDHB, identisch in kW und ccm, nur übers
--     Baujahr unterscheidbar). Ein geratener Code würde falsche
--     Wartungsempfehlungen auslösen, die der Nutzer nicht als falsch erkennt.
--     Deshalb: Katalog SCHLÄGT VOR, der Nutzer BESTÄTIGT (vehicles.motorcode_
--     herkunft = 'nutzer'), und nur dann greifen motorcode-Empfehlungen.
--   * Jede kuratierte Zeile trägt Quelle + wörtliches Zitat (CI-Gate).
--
-- Alle Tabellen sind read-only Katalogdaten: additiver Merge per stabiler
-- Text-ID (Slug), entfallene Einträge werden getombstoned statt gelöscht
-- (siehe modules/vehicle_catalog.py).
CREATE TABLE IF NOT EXISTS katalog_marke (
    id           TEXT PRIMARY KEY,             -- 'audi' (stabil, nie ändern)
    name         TEXT NOT NULL,                -- 'Audi' (Wortmarke, NIE Logo)
    quelle_url   TEXT NOT NULL,
    quelle_abruf TEXT NOT NULL,                -- ISO
    deprecated   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS katalog_baureihe (
    id         TEXT PRIMARY KEY,               -- 'audi-a4'
    marke_id   TEXT NOT NULL,
    name       TEXT NOT NULL,                  -- 'A4'
    quelle_url TEXT NOT NULL,
    deprecated INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (marke_id) REFERENCES katalog_marke(id)
);

CREATE TABLE IF NOT EXISTS katalog_generation (
    id          TEXT PRIMARY KEY,              -- 'audi-a4-b8'
    baureihe_id TEXT NOT NULL,
    name        TEXT NOT NULL,                 -- 'B8'
    bj_von      INTEGER,
    bj_bis      INTEGER,                       -- NULL = noch aktuell
    quelle_url  TEXT NOT NULL,
    deprecated  INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (baureihe_id) REFERENCES katalog_baureihe(id)
);

-- Was der Nutzer als „Motor" sieht: der HANDELSNAME, nicht der Code.
-- Die Felder spiegeln 1:1 das Fahrzeugprofil → verlustfreie Vorbelegung.
CREATE TABLE IF NOT EXISTS katalog_motorisierung (
    id                 TEXT PRIMARY KEY,       -- 'audi-a4-b8-1-8-tfsi-160'
    generation_id      TEXT NOT NULL,
    anzeigename        TEXT NOT NULL,          -- '1.8 TFSI (160 PS)'
    bj_von             INTEGER,
    bj_bis             INTEGER,
    kraftstoff         TEXT NOT NULL,          -- Vokabular aus modules.models
    motorbauform       TEXT,
    aufladung          TEXT,
    direkteinspritzung INTEGER,                -- 1/0/NULL
    partikelfilter     TEXT,                   -- keiner|dpf|opf
    hubraum_ccm        INTEGER,
    leistung_ps        INTEGER,
    getriebe           TEXT,                   -- oft variantenabhängig → NULL ok
    oel_viskositaet    TEXT,
    oel_freigabe       TEXT,
    -- Quellenpflicht (CI-Gate lehnt Zeilen ohne diese Felder ab)
    quelle_url         TEXT NOT NULL,
    quelle_zitat       TEXT NOT NULL,          -- Rohsatz der Quelle, wörtlich
    quelle_abruf       TEXT NOT NULL,
    deprecated         INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (generation_id) REFERENCES katalog_generation(id)
);

-- Motorcodes: NUR als Vorschlagsliste zum Bestätigen (siehe Vertrauensmodell).
CREATE TABLE IF NOT EXISTS katalog_motorcode (
    id           TEXT PRIMARY KEY,             -- 'vag-cdhb'
    code         TEXT NOT NULL,                -- 'CDHB'
    motorfamilie TEXT,                         -- 'EA888-GEN2' ← Empfehlungs-Anker
    einbaulage   TEXT,                         -- laengs|quer ← hier passieren die Fehler
    bj_von       INTEGER,
    bj_bis       INTEGER,
    quelle_url   TEXT NOT NULL,
    quelle_zitat TEXT NOT NULL,
    deprecated   INTEGER NOT NULL DEFAULT 0
);

-- BEWUSST n:m — eine Motorisierung kann mehrere Codes haben. Die App löst das
-- NIE selbst auf, sondern legt die Auswahl dem Nutzer vor.
CREATE TABLE IF NOT EXISTS katalog_motorisierung_motorcode (
    motorisierung_id TEXT NOT NULL,
    motorcode_id     TEXT NOT NULL,
    PRIMARY KEY (motorisierung_id, motorcode_id),
    FOREIGN KEY (motorisierung_id) REFERENCES katalog_motorisierung(id),
    FOREIGN KEY (motorcode_id) REFERENCES katalog_motorcode(id)
);

-- HSN/TSN → Hersteller + Handelsname, komplett aus dem KBA-Bestand FZ 6.
-- Quelle: Kraftfahrt-Bundesamt, FZ 6; Datenlizenz Deutschland Namensnennung 2.0
-- (steht wörtlich im Impressum der Original-XLSX). Erlaubt zwei Zahlen aus dem
-- Fahrzeugschein (Feld 2.1/2.2) statt einer Dropdown-Kaskade.
CREATE TABLE IF NOT EXISTS katalog_kba (
    hsn         TEXT NOT NULL,
    tsn         TEXT NOT NULL,
    hersteller  TEXT NOT NULL,
    handelsname TEXT NOT NULL,
    PRIMARY KEY (hsn, tsn)
);

-- --- Key/value settings inside the DB ---------------------------------------------
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- --- Interop (App-Familie) ------------------------------------------------------------
-- Contract instead of table access: the sister app (HaushaltsManager) reads
-- ONLY interop_meta and the interop_* views below. See INTEROP.md.
CREATE TABLE IF NOT EXISTS interop_meta (
    interop_version INTEGER NOT NULL
);

CREATE VIEW IF NOT EXISTS interop_fahrzeuge AS
    SELECT id, name, COALESCE(kraftstoff, 'unbekannt') AS antrieb
    FROM vehicles WHERE active = 1;

CREATE VIEW IF NOT EXISTS interop_kosten_monat AS
    SELECT vehicle_id                                   AS fahrzeug_id,
           CAST(strftime('%Y', date) AS INTEGER)        AS jahr,
           CAST(strftime('%m', date) AS INTEGER)        AS monat,
           kategorie                                    AS kategorie,
           SUM(betrag_cent)                             AS betrag_cent
    FROM costs
    GROUP BY vehicle_id, jahr, monat, kategorie;

CREATE VIEW IF NOT EXISTS interop_termine AS
    SELECT vehicle_id   AS fahrzeug_id,
           typ          AS typ,
           faellig_datum AS faellig_datum,
           faellig_km   AS faellig_km,
           COALESCE(beschreibung, typ) AS beschreibung
    FROM appointments WHERE erledigt = 0;

-- --- Indexes ------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_tank_vehicle_date ON tank_entries(vehicle_id, date);
CREATE INDEX IF NOT EXISTS idx_costs_vehicle_date ON costs(vehicle_id, date);
CREATE INDEX IF NOT EXISTS idx_costs_kategorie ON costs(kategorie);
CREATE INDEX IF NOT EXISTS idx_appt_vehicle ON appointments(vehicle_id, erledigt);
CREATE INDEX IF NOT EXISTS idx_rules_vehicle ON care_rules(vehicle_id, aktiv);
CREATE INDEX IF NOT EXISTS idx_logbook_vehicle_date ON logbook_entries(vehicle_id, date);
CREATE INDEX IF NOT EXISTS idx_attach_entry ON attachments(entry_kind, entry_id);
-- Katalog: Kaskade (Marke→Baureihe→Generation→Motorisierung) + HSN/TSN-Suche.
CREATE INDEX IF NOT EXISTS idx_kat_baureihe_marke ON katalog_baureihe(marke_id);
CREATE INDEX IF NOT EXISTS idx_kat_gen_baureihe ON katalog_generation(baureihe_id);
CREATE INDEX IF NOT EXISTS idx_kat_mot_gen ON katalog_motorisierung(generation_id);
CREATE INDEX IF NOT EXISTS idx_kat_kba_name ON katalog_kba(handelsname);
