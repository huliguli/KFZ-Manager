"""Modal add/edit dialogs for vehicles, tank entries, costs, appointments,
care rules and catalog entries.

Each dialog builds and validates a model dataclass. Validation errors are shown
inline (never as a raw exception), money/date fields use the German-aware
parsers, and odometer inputs are validated against the vehicle's km history
(monotonically increasing, corrections allowed by editing the entry itself).
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from modules import dates, fuel
from modules.models import (
    ANTRIEB_LABELS,
    ANTRIEBE,
    APPOINTMENT_TYPES,
    AUFLADUNG_LABELS,
    AUFLADUNGEN,
    CATALOG_CATEGORIES,
    COST_CATEGORIES,
    FAHRPROFIL_LABELS,
    FAHRPROFILE,
    GETRIEBE,
    GETRIEBE_LABELS,
    KRAFTSTOFF_LABELS,
    KRAFTSTOFFE,
    LADEORT_LABELS,
    LADEORTE,
    LOGBOOK_KIND_LABELS,
    LOGBOOK_KINDS,
    MOTORBAUFORM_LABELS,
    MOTORBAUFORMEN,
    PARTIKELFILTER,
    PARTIKELFILTER_LABELS,
    Appointment,
    CareRule,
    CatalogItem,
    Cost,
    LogbookEntry,
    TankEntry,
    Vehicle,
)
from ui.widgets.inputs import MoneyLineEdit, labelled


def _opt_date(text: str) -> str | None:
    """Parse an optional date field. Empty -> None; invalid -> ValueError."""
    text = (text or "").strip()
    if not text:
        return None
    d = dates.parse_date(text)
    if d is None:
        raise ValueError(f"„{text}“ ist kein gültiges Datum (TT.MM.JJJJ).")
    return dates.to_iso(d)


def _opt_int(text: str, label: str) -> int | None:
    text = (text or "").strip().replace(".", "").replace(" ", "")
    if not text:
        return None
    try:
        value = int(text)
    except ValueError as exc:
        raise ValueError(f"{label}: bitte eine ganze Zahl eingeben.") from exc
    if value < 0:
        raise ValueError(f"{label} darf nicht negativ sein.")
    return value


def _kba_titel(text: str) -> str:
    """Behörden-Schreibweise in lesbare Form bringen.

    Die KBA-Liste führt „VOLKSWAGEN-VW" und „GOLF" durchgängig in
    Großbuchstaben; im Fahrzeugprofil steht das sonst als Geschrei. Aus
    Kürzeln (VW, BMW, GTI …) wird bewusst nichts gemacht — sie bleiben groß.
    """
    def wort(w: str) -> str:
        return w if (len(w) <= 3 or not w.isalpha()) else w.capitalize()

    parts = [wort(p) for p in (text or "").split()]
    return " ".join(parts)


def _vocab_combo(values: list[str], labels: dict[str, str],
                 current: str | None, optional: bool = True) -> QComboBox:
    """Combo box over a machine-value vocabulary with German labels."""
    combo = QComboBox()
    if optional:
        combo.addItem("— unbekannt —", None)
    for key in values:
        combo.addItem(labels.get(key, key), key)
    if current is not None:
        idx = combo.findData(current)
        if idx >= 0:
            combo.setCurrentIndex(idx)
    return combo


class _BaseDialog(QDialog):
    """Shared scaffold: titled form grid, inline error label, OK/Cancel."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(560)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(16)

        header = QLabel(title)
        header.setObjectName("H2")
        root.addWidget(header)

        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(12)
        root.addLayout(self.grid)

        self._error = QLabel("")
        self._error.setObjectName("ErrorText")
        self._error.setWordWrap(True)
        self._error.hide()
        root.addWidget(self._error)

        root.addStretch(1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Abbrechen")
        cancel.setObjectName("Ghost")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Speichern")
        save.setObjectName("Primary")
        save.clicked.connect(self._on_save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

        self._row = 0

    def add_row(self, left: QWidget, right: QWidget | None = None) -> None:
        if right is None:
            self.grid.addWidget(left, self._row, 0, 1, 2)
        else:
            self.grid.addWidget(left, self._row, 0)
            self.grid.addWidget(right, self._row, 1)
        self._row += 1

    def show_error(self, message: str) -> None:
        self._error.setText(message)
        self._error.show()

    def _on_save(self) -> None:
        try:
            self.build()  # subclass validates + stores self.result_model
        except ValueError as exc:
            self.show_error(str(exc))
            return
        self.accept()

    def build(self) -> None:  # noqa: D401 - overridden
        raise NotImplementedError


# --- Vehicle -----------------------------------------------------------------
class VehicleDialog(_BaseDialog):
    """Add/edit a vehicle with the full recommendation-relevant profile.

    Der Katalog-Knopf oben belegt die Profilfelder vor (Marke/Baureihe/Motor
    oder HSN/TSN aus dem Fahrzeugschein) — alles bleibt danach frei
    editierbar. Von Hand geänderte Felder werden in ``profil_dirty``
    vermerkt, damit spätere Katalog-Updates sie nie überschreiben.

    ``db`` wird nur für den Katalog gebraucht; ohne DB (z. B. im Wizard vor
    dem ersten Start) erscheint der Knopf schlicht nicht.
    """

    def __init__(self, item: Vehicle | None = None, parent=None, db=None) -> None:
        super().__init__("Fahrzeug bearbeiten" if item else "Fahrzeug anlegen", parent)
        self._id = item.id if item else None
        self._db = db
        self._katalog_motorisierung_id = item.katalog_motorisierung_id if item else None
        self._motorcode = item.motorcode if item else ""
        self._motorcode_herkunft = item.motorcode_herkunft if item else None
        self._dirty: set[str] = set(item.profil_dirty) if item else set()

        self.name = QLineEdit(item.name if item else "")
        self.name.setPlaceholderText("z. B. Roter Flitzer")
        self.hersteller = QLineEdit(item.hersteller if item else "")
        self.hersteller.setPlaceholderText("z. B. Mazda")
        self.modell = QLineEdit(item.modell if item else "")
        self.modell.setPlaceholderText("z. B. MX-5")
        self.erstzulassung = QLineEdit(
            dates.format_date(item.erstzulassung) if item and item.erstzulassung else "")
        self.erstzulassung.setPlaceholderText("optional · TT.MM.JJJJ")
        self.kennzeichen = QLineEdit(item.kennzeichen if item else "")
        self.kennzeichen.setPlaceholderText("optional")
        self.km_stand = QLineEdit(
            str(item.km_stand) if item and item.km_stand is not None else "")
        self.km_stand.setPlaceholderText("aktueller km-Stand")

        self.kraftstoff = _vocab_combo(KRAFTSTOFFE, KRAFTSTOFF_LABELS,
                                       item.kraftstoff if item else None)
        self.motorbauform = _vocab_combo(MOTORBAUFORMEN, MOTORBAUFORM_LABELS,
                                         item.motorbauform if item else None)
        self.hubraum = QLineEdit(
            str(item.hubraum_ccm) if item and item.hubraum_ccm else "")
        self.hubraum.setPlaceholderText("cm³ · optional")
        self.leistung = QLineEdit(
            str(item.leistung_ps) if item and item.leistung_ps else "")
        self.leistung.setPlaceholderText("PS · optional")
        self.aufladung = _vocab_combo(AUFLADUNGEN, AUFLADUNG_LABELS,
                                      item.aufladung if item else None)

        self.direkteinspritzung = QComboBox()
        for label, value in (("— unbekannt —", None), ("Ja", True), ("Nein", False)):
            self.direkteinspritzung.addItem(label, value)
        if item and item.direkteinspritzung is not None:
            self.direkteinspritzung.setCurrentIndex(1 if item.direkteinspritzung else 2)

        self.partikelfilter = _vocab_combo(PARTIKELFILTER, PARTIKELFILTER_LABELS,
                                           item.partikelfilter if item else None)
        self.getriebe = _vocab_combo(GETRIEBE, GETRIEBE_LABELS,
                                     item.getriebe if item else None)
        self.antrieb = _vocab_combo(ANTRIEBE, ANTRIEB_LABELS,
                                    item.antrieb if item else None)
        self.oel_viskositaet = QLineEdit(item.oel_viskositaet if item else "")
        self.oel_viskositaet.setPlaceholderText("z. B. 5W-30 · optional")
        self.oel_freigabe = QLineEdit(item.oel_freigabe if item else "")
        self.oel_freigabe.setPlaceholderText("z. B. VW 507 00 · optional")
        self.fahrprofil = _vocab_combo(FAHRPROFILE, FAHRPROFIL_LABELS,
                                       item.fahrprofil if item else None)
        self.notiz = QLineEdit(item.notiz if item else "")

        # Katalog-Einstieg ganz oben: der schnellste Weg zu einem gefüllten
        # Profil — aber freiwillig, alles darunter bleibt von Hand bedienbar.
        if db is not None:
            katalog_row = QHBoxLayout()
            katalog_btn = QPushButton("Aus Katalog übernehmen …")
            katalog_btn.setObjectName("Ghost")
            katalog_btn.clicked.connect(self._pick_from_catalog)
            self._katalog_info = QLabel("")
            self._katalog_info.setObjectName("Faint")
            self._katalog_info.setWordWrap(True)
            katalog_row.addWidget(katalog_btn)
            katalog_row.addWidget(self._katalog_info, 1)
            wrap = QWidget()
            wrap.setLayout(katalog_row)
            self.add_row(labelled(
                "Fahrzeugschein oder Katalog", wrap,
                hint="Spart das Abtippen: HSN/TSN aus dem Schein oder "
                     "Marke → Baureihe → Motor. Alle Werte bleiben änderbar."))

        self.add_row(labelled("Name/Spitzname *", self.name),
                     labelled("Kennzeichen", self.kennzeichen))
        self.add_row(labelled("Hersteller", self.hersteller),
                     labelled("Modell", self.modell))
        self.add_row(labelled("Erstzulassung", self.erstzulassung),
                     labelled("Aktueller km-Stand", self.km_stand))
        self.add_row(labelled("Kraftstoffart", self.kraftstoff),
                     labelled("Motorbauform", self.motorbauform))
        self.add_row(labelled("Hubraum", self.hubraum),
                     labelled("Leistung", self.leistung))
        self.add_row(labelled("Aufladung", self.aufladung),
                     labelled("Direkteinspritzung", self.direkteinspritzung))
        self.add_row(labelled("Partikelfilter", self.partikelfilter),
                     labelled("Getriebe", self.getriebe))
        self.add_row(labelled("Antrieb", self.antrieb),
                     labelled("Fahrprofil", self.fahrprofil))
        self.add_row(labelled("Öl-Viskosität", self.oel_viskositaet),
                     labelled("Öl-Herstellerfreigabe", self.oel_freigabe))
        self.add_row(labelled("Notiz (optional)", self.notiz))
        self._track_manual_edits()

    def _track_manual_edits(self) -> None:
        """Merkt sich, welche Profilfelder der Nutzer selbst angefasst hat.

        Diese Felder sind für die Katalog-Vorbelegung (und für spätere
        Katalog-Updates) tabu — was der Nutzer eingetragen hat, gewinnt immer.
        """
        felder = {
            "hersteller": self.hersteller, "modell": self.modell,
            "hubraum_ccm": self.hubraum, "leistung_ps": self.leistung,
            "oel_viskositaet": self.oel_viskositaet,
            "oel_freigabe": self.oel_freigabe,
        }
        for feld, widget in felder.items():
            # textEdited (nicht textChanged) feuert nur bei Tastatureingabe,
            # nicht beim programmatischen setText der Vorbelegung.
            widget.textEdited.connect(lambda _t, f=feld: self._dirty.add(f))
        combos = {
            "kraftstoff": self.kraftstoff, "motorbauform": self.motorbauform,
            "aufladung": self.aufladung, "partikelfilter": self.partikelfilter,
            "getriebe": self.getriebe,
            "direkteinspritzung": self.direkteinspritzung,
        }
        for feld, combo in combos.items():
            # activated feuert ebenfalls nur bei Nutzer-Interaktion.
            combo.activated.connect(lambda _i, f=feld: self._dirty.add(f))

    # -- Katalog-Vorbelegung ---------------------------------------------------
    def _pick_from_catalog(self) -> None:
        """Katalog-Auswahl öffnen und die Profilfelder vorbelegen.

        Von Hand geänderte Felder (``self._dirty``) bleiben unangetastet —
        der Nutzer hat dort bewusst etwas anderes stehen.
        """
        from ui.katalog_dialog import KatalogDialog

        auswahl = KatalogDialog.pick(self._db, self)
        if auswahl is None:
            return

        if auswahl.hersteller and "hersteller" not in self._dirty:
            self.hersteller.setText(_kba_titel(auswahl.hersteller))
        if auswahl.modell and "modell" not in self._dirty:
            self.modell.setText(_kba_titel(auswahl.modell))

        uebernommen = []
        mot = auswahl.motorisierung
        if mot is not None:
            self._katalog_motorisierung_id = mot.id
            for feld, wert in mot.werte.items():
                if wert is None or feld in self._dirty:
                    continue
                if self._set_field(feld, wert):
                    uebernommen.append(feld)

        # Motorcode NUR, wenn der Nutzer ihn im Dialog bestätigt hat.
        if auswahl.motorcode_bestaetigt and auswahl.motorcode:
            self._motorcode = auswahl.motorcode
            self._motorcode_herkunft = "nutzer"
        info = []
        if mot is not None:
            info.append(f"{mot.anzeigename} übernommen ({len(uebernommen)} Felder)")
        elif auswahl.hersteller:
            info.append(f"{auswahl.hersteller} · {auswahl.modell}")
        if self._motorcode_herkunft == "nutzer" and self._motorcode:
            info.append(f"Motorcode {self._motorcode} bestätigt")
        self._katalog_info.setText("  ·  ".join(info))

    def _set_field(self, feld: str, wert) -> bool:
        """Einen vorbelegten Wert in das passende Widget schreiben."""
        combos = {
            "kraftstoff": self.kraftstoff, "motorbauform": self.motorbauform,
            "aufladung": self.aufladung, "partikelfilter": self.partikelfilter,
            "getriebe": self.getriebe,
        }
        if feld in combos:
            idx = combos[feld].findData(wert)
            if idx >= 0:
                combos[feld].setCurrentIndex(idx)
                return True
            return False
        if feld == "direkteinspritzung":
            idx = self.direkteinspritzung.findData(bool(wert))
            if idx >= 0:
                self.direkteinspritzung.setCurrentIndex(idx)
                return True
            return False
        lines = {"hubraum_ccm": self.hubraum, "leistung_ps": self.leistung,
                 "oel_viskositaet": self.oel_viskositaet,
                 "oel_freigabe": self.oel_freigabe}
        if feld in lines:
            lines[feld].setText(str(wert))
            return True
        return False

    def build(self) -> None:
        name = self.name.text().strip()
        if not name:
            raise ValueError("Bitte einen Namen/Spitznamen eingeben.")
        km = _opt_int(self.km_stand.text(), "km-Stand")
        erstzulassung = _opt_date(self.erstzulassung.text())
        self.result_model = Vehicle(
            id=self._id, name=name,
            hersteller=self.hersteller.text().strip(),
            modell=self.modell.text().strip(),
            erstzulassung=erstzulassung,
            kennzeichen=self.kennzeichen.text().strip(),
            km_stand=km,
            km_stand_datum=dates.to_iso(dates.today()) if km is not None else None,
            kraftstoff=self.kraftstoff.currentData(),
            motorbauform=self.motorbauform.currentData(),
            hubraum_ccm=_opt_int(self.hubraum.text(), "Hubraum"),
            leistung_ps=_opt_int(self.leistung.text(), "Leistung"),
            aufladung=self.aufladung.currentData(),
            direkteinspritzung=self.direkteinspritzung.currentData(),
            partikelfilter=self.partikelfilter.currentData(),
            getriebe=self.getriebe.currentData(),
            antrieb=self.antrieb.currentData(),
            oel_viskositaet=self.oel_viskositaet.text().strip(),
            oel_freigabe=self.oel_freigabe.text().strip(),
            fahrprofil=self.fahrprofil.currentData(),
            notiz=self.notiz.text().strip(),
            katalog_motorisierung_id=self._katalog_motorisierung_id,
            motorcode=self._motorcode,
            motorcode_herkunft=self._motorcode_herkunft,
            profil_dirty=sorted(self._dirty),
        )


# --- Tank / charge entry ----------------------------------------------------
class TankDialog(_BaseDialog):
    """Add/edit a refuel or charge entry with odometer validation."""

    def __init__(self, vehicle: Vehicle, history: list[fuel.OdoReading],
                 item: TankEntry | None = None, parent=None) -> None:
        super().__init__("Eintrag bearbeiten" if item else "Tanken/Laden erfassen", parent)
        self._id = item.id if item else None
        self._vehicle = vehicle
        self._history = history

        default_date = dates.format_date(item.date) if item else dates.format_date(dates.today())
        self.date = QLineEdit(default_date)
        self.date.setPlaceholderText("TT.MM.JJJJ")
        self.odo = QLineEdit(str(item.odo_km) if item else "")
        self.odo.setPlaceholderText("km-Stand beim Tanken/Laden")

        self.art = QComboBox()
        self.art.addItem("Kraftstoff (Tanken)", "kraftstoff")
        self.art.addItem("Strom (Laden)", "strom")
        # Electric-only vehicles default to charging; combustion to fuel.
        default_art = item.art if item else ("strom" if vehicle.kraftstoff == "elektro"
                                             else "kraftstoff")
        self.art.setCurrentIndex(1 if default_art == "strom" else 0)
        self.art.currentIndexChanged.connect(lambda _i: self._sync_fields())

        self.menge = QLineEdit(
            f"{item.menge_ml / 1000:.2f}".replace(".", ",")
            if item and item.menge_ml else "")
        self.menge.setPlaceholderText("Liter · z. B. 42,5")
        self.energie = QLineEdit(
            f"{item.energie_wh / 1000:.2f}".replace(".", ",")
            if item and item.energie_wh else "")
        self.energie.setPlaceholderText("kWh · z. B. 38,2")
        self.betrag = MoneyLineEdit(item.betrag_cent if item else None)
        self.preis_hint = QLabel("")
        self.preis_hint.setObjectName("Faint")

        self.voll = QCheckBox("Vollbetankung (für die Verbrauchsberechnung)")
        self.voll.setChecked(item.voll if item else True)
        self.ladeort = _vocab_combo(LADEORTE, LADEORT_LABELS,
                                    item.ladeort if item else None)
        self.notiz = QLineEdit(item.notiz if item else "")

        self.add_row(labelled("Datum", self.date), labelled("km-Stand", self.odo))
        self.add_row(labelled("Art", self.art), labelled("Gesamtbetrag", self.betrag))
        self._menge_row = labelled("Menge (Liter)", self.menge)
        self._energie_row = labelled("Energie (kWh)", self.energie)
        self._ladeort_row = labelled("Ladeort", self.ladeort)
        self.add_row(self._menge_row, self._energie_row)
        self.add_row(self.voll)
        self.add_row(self._ladeort_row, labelled("Notiz (optional)", self.notiz))
        self.add_row(self.preis_hint)

        for editor in (self.menge, self.energie):
            editor.textChanged.connect(self._update_price_hint)
        self.betrag.textChanged.connect(self._update_price_hint)
        self._sync_fields()

    def _sync_fields(self) -> None:
        is_charge = self.art.currentData() == "strom"
        self._menge_row.setVisible(not is_charge)
        self.voll.setVisible(not is_charge)
        self._energie_row.setVisible(is_charge)
        self._ladeort_row.setVisible(is_charge)
        self._update_price_hint()

    def _update_price_hint(self) -> None:
        """Live €/Liter bzw. €/kWh preview derived from amount + quantity."""
        betrag = self.betrag.cents()
        if self.art.currentData() == "strom":
            qty = fuel.parse_decimal(self.energie.text())
            unit = "€/kWh"
        else:
            qty = fuel.parse_decimal(self.menge.text())
            unit = "€/Liter"
        if betrag and qty and qty > 0:
            per_unit = betrag / 100.0 / qty
            self.preis_hint.setText(f"≈ {per_unit:.3f} {unit}".replace(".", ","))
        else:
            self.preis_hint.setText("")

    def build(self) -> None:
        d = dates.parse_date(self.date.text())
        if d is None:
            raise ValueError("Bitte ein gültiges Datum (TT.MM.JJJJ) eingeben.")
        odo = _opt_int(self.odo.text(), "km-Stand")
        if odo is None:
            raise ValueError("Bitte den km-Stand eingeben.")
        # When editing, the entry's own old reading must not block corrections.
        ignore_date = d if self._id is not None else None
        error = fuel.validate_odo(self._history, d, odo, ignore_date=ignore_date)
        if error:
            raise ValueError(error + " Korrektur: bestehenden Eintrag bearbeiten.")
        betrag = self.betrag.cents()
        if betrag is None or betrag < 0:
            raise ValueError("Bitte einen gültigen Gesamtbetrag eingeben (0 ist erlaubt).")

        art = self.art.currentData()
        menge_ml = energie_wh = None
        if art == "kraftstoff":
            liters = fuel.parse_decimal(self.menge.text())
            if liters is None or liters <= 0:
                raise ValueError("Bitte die getankte Menge in Litern eingeben.")
            menge_ml = round(liters * 1000)
        else:
            kwh = fuel.parse_decimal(self.energie.text())
            if kwh is None or kwh <= 0:
                raise ValueError("Bitte die geladene Energie in kWh eingeben.")
            energie_wh = round(kwh * 1000)

        self.result_model = TankEntry(
            id=self._id, vehicle_id=self._vehicle.id, date=dates.to_iso(d),
            odo_km=odo, art=art, menge_ml=menge_ml, energie_wh=energie_wh,
            betrag_cent=betrag, voll=self.voll.isChecked() if art == "kraftstoff" else True,
            ladeort=self.ladeort.currentData() if art == "strom" else None,
            notiz=self.notiz.text().strip(),
        )


# --- Cost ---------------------------------------------------------------------
class CostDialog(_BaseDialog):
    def __init__(self, vehicle: Vehicle, item: Cost | None = None, parent=None) -> None:
        super().__init__("Kosten bearbeiten" if item else "Kosten erfassen", parent)
        self._id = item.id if item else None
        self._vehicle = vehicle

        default_date = dates.format_date(item.date) if item else dates.format_date(dates.today())
        self.date = QLineEdit(default_date)
        self.date.setPlaceholderText("TT.MM.JJJJ")
        self.betrag = MoneyLineEdit(item.betrag_cent if item else None)
        self.kategorie = QComboBox()
        self.kategorie.addItems(COST_CATEGORIES)
        if item and item.kategorie in COST_CATEGORIES:
            self.kategorie.setCurrentText(item.kategorie)
        self.notiz = QLineEdit(item.notiz if item else "")
        self.odo = QLineEdit(str(item.odo_km) if item and item.odo_km is not None else "")
        self.odo.setPlaceholderText("optional")

        self.add_row(labelled("Datum", self.date), labelled("Betrag", self.betrag))
        self.add_row(labelled("Kategorie", self.kategorie),
                     labelled("km-Stand (optional)", self.odo))
        self.add_row(labelled("Notiz", self.notiz))

    def build(self) -> None:
        d = dates.parse_date(self.date.text())
        if d is None:
            raise ValueError("Bitte ein gültiges Datum (TT.MM.JJJJ) eingeben.")
        betrag = self.betrag.cents()
        if betrag is None:
            raise ValueError("Bitte einen gültigen Betrag eingeben.")
        self.result_model = Cost(
            id=self._id, vehicle_id=self._vehicle.id, date=dates.to_iso(d),
            kategorie=self.kategorie.currentText(), betrag_cent=betrag,
            notiz=self.notiz.text().strip(),
            odo_km=_opt_int(self.odo.text(), "km-Stand"),
        )


# --- Appointment ------------------------------------------------------------------
class AppointmentDialog(_BaseDialog):
    def __init__(self, vehicle: Vehicle, item: Appointment | None = None, parent=None) -> None:
        super().__init__("Termin bearbeiten" if item else "Termin anlegen", parent)
        self._id = item.id if item else None
        self._vehicle = vehicle
        self._erledigt = item.erledigt if item else False
        self._erledigt_datum = item.erledigt_datum if item else None

        self.typ = QComboBox()
        self.typ.setEditable(True)  # eigene Typen erlaubt
        self.typ.addItems(APPOINTMENT_TYPES)
        if item:
            self.typ.setCurrentText(item.typ)
        self.beschreibung = QLineEdit(item.beschreibung if item else "")
        self.datum = QLineEdit(
            dates.format_date(item.faellig_datum) if item and item.faellig_datum else "")
        self.datum.setPlaceholderText("TT.MM.JJJJ · optional")
        self.km = QLineEdit(
            str(item.faellig_km) if item and item.faellig_km is not None else "")
        self.km.setPlaceholderText("optional")

        self.add_row(labelled("Typ", self.typ), labelled("Beschreibung", self.beschreibung))
        self.add_row(labelled("Fällig am (Datum)", self.datum),
                     labelled("Fällig bei km-Stand", self.km))
        hint = QLabel("Mindestens eines von beidem angeben — was zuerst eintritt, zählt.")
        hint.setObjectName("Faint")
        self.add_row(hint)

    def build(self) -> None:
        typ = self.typ.currentText().strip()
        if not typ:
            raise ValueError("Bitte einen Termin-Typ angeben.")
        datum = _opt_date(self.datum.text())
        km = _opt_int(self.km.text(), "km-Stand")
        if datum is None and km is None:
            raise ValueError("Bitte ein Fälligkeitsdatum und/oder einen km-Stand angeben.")
        self.result_model = Appointment(
            id=self._id, vehicle_id=self._vehicle.id, typ=typ,
            beschreibung=self.beschreibung.text().strip(),
            faellig_datum=datum, faellig_km=km,
            erledigt=self._erledigt, erledigt_datum=self._erledigt_datum,
        )


# --- Care rule ---------------------------------------------------------------------
class CareRuleDialog(_BaseDialog):
    """Add/edit an interval rule ('alle X km und/oder alle Y Monate')."""

    def __init__(self, vehicle: Vehicle, item: CareRule | None = None, parent=None) -> None:
        super().__init__("Pflege-Regel bearbeiten" if item else "Pflege-Regel anlegen", parent)
        self._id = item.id if item else None
        self._vehicle = vehicle
        self._catalog_id = item.catalog_id if item else None

        self.name = QLineEdit(item.name if item else "")
        self.name.setPlaceholderText("z. B. Motoröl + Filter wechseln")
        self.kategorie = QComboBox()
        self.kategorie.addItems(CATALOG_CATEGORIES)
        if item and item.kategorie in CATALOG_CATEGORIES:
            self.kategorie.setCurrentText(item.kategorie)
        self.intervall_km = QLineEdit(
            str(item.intervall_km) if item and item.intervall_km else "")
        self.intervall_km.setPlaceholderText("z. B. 15000 · optional")
        self.intervall_monate = QLineEdit(
            str(item.intervall_monate) if item and item.intervall_monate else "")
        self.intervall_monate.setPlaceholderText("z. B. 12 · optional")
        self.letzte_datum = QLineEdit(
            dates.format_date(item.letzte_datum) if item and item.letzte_datum else "")
        self.letzte_datum.setPlaceholderText("TT.MM.JJJJ · optional")
        self.letzte_km = QLineEdit(
            str(item.letzte_km) if item and item.letzte_km is not None else "")
        self.letzte_km.setPlaceholderText("optional")
        self.notiz = QLineEdit(item.notiz if item else "")

        self.add_row(labelled("Bezeichnung *", self.name),
                     labelled("Kategorie", self.kategorie))
        self.add_row(labelled("Intervall: alle … km", self.intervall_km),
                     labelled("Intervall: alle … Monate", self.intervall_monate))
        self.add_row(labelled("Zuletzt durchgeführt am", self.letzte_datum),
                     labelled("km-Stand damals", self.letzte_km))
        self.add_row(labelled("Notiz (optional)", self.notiz))
        hint = QLabel("„Was zuerst eintritt“ — es genügt eines der beiden Intervalle.")
        hint.setObjectName("Faint")
        self.add_row(hint)

    def build(self) -> None:
        name = self.name.text().strip()
        if not name:
            raise ValueError("Bitte eine Bezeichnung eingeben.")
        km = _opt_int(self.intervall_km.text(), "km-Intervall")
        monate = _opt_int(self.intervall_monate.text(), "Monats-Intervall")
        if not km and not monate:
            raise ValueError("Bitte mindestens ein Intervall (km oder Monate) angeben.")
        self.result_model = CareRule(
            id=self._id, vehicle_id=self._vehicle.id, catalog_id=self._catalog_id,
            name=name, kategorie=self.kategorie.currentText(),
            intervall_km=km or None, intervall_monate=monate or None,
            letzte_datum=_opt_date(self.letzte_datum.text()),
            letzte_km=_opt_int(self.letzte_km.text(), "km-Stand"),
            notiz=self.notiz.text().strip(),
        )


# --- Complete a care rule ------------------------------------------------------------
class CompleteRuleDialog(_BaseDialog):
    """Erledigen: record date/km, optional cost, note — resets the interval.

    The caller reads ``result`` (dict) and performs the writes: reset rule
    anchor, optional linked cost row, logbook entry.
    """

    def __init__(self, rule: CareRule, km_now: int | None, parent=None) -> None:
        super().__init__(f"„{rule.name}“ erledigen", parent)
        self._rule = rule

        self.datum = QLineEdit(dates.format_date(dates.today()))
        self.km = QLineEdit(str(km_now) if km_now is not None else "")
        self.km.setPlaceholderText("km-Stand bei Durchführung")
        self.kosten = MoneyLineEdit(None)
        self.kosten.setPlaceholderText("optional · erzeugt Kosteneintrag")
        self.notiz = QLineEdit("")

        self.add_row(labelled("Durchgeführt am", self.datum),
                     labelled("km-Stand", self.km))
        self.add_row(labelled("Kosten (optional)", self.kosten),
                     labelled("Notiz (optional)", self.notiz))
        info = QLabel("Das Intervall wird zurückgesetzt und der Eintrag wandert "
                      "ins Scheckheft.")
        info.setObjectName("Faint")
        self.add_row(info)

    def build(self) -> None:
        d = dates.parse_date(self.datum.text())
        if d is None:
            raise ValueError("Bitte ein gültiges Datum (TT.MM.JJJJ) eingeben.")
        km = _opt_int(self.km.text(), "km-Stand")
        kosten = None
        if self.kosten.text().strip():
            kosten = self.kosten.cents()
            if kosten is None:
                raise ValueError("Bitte einen gültigen Kostenbetrag eingeben (oder leer lassen).")
        self.result_model = {
            "datum": dates.to_iso(d),
            "km": km,
            "kosten_cent": kosten,
            "notiz": self.notiz.text().strip(),
        }


# --- Logbook entry (manual) ----------------------------------------------------------
class LogbookDialog(_BaseDialog):
    def __init__(self, vehicle: Vehicle, item: LogbookEntry | None = None, parent=None) -> None:
        super().__init__("Scheckheft-Eintrag bearbeiten" if item
                         else "Scheckheft-Eintrag anlegen", parent)
        self._id = item.id if item else None
        self._vehicle = vehicle
        self._cost_id = item.cost_id if item else None
        self._rule_id = item.rule_id if item else None

        default_date = dates.format_date(item.date) if item else dates.format_date(dates.today())
        self.date = QLineEdit(default_date)
        self.titel = QLineEdit(item.titel if item else "")
        self.titel.setPlaceholderText("z. B. Bremsbeläge vorn erneuert")
        self.art = QComboBox()
        for key in LOGBOOK_KINDS:
            self.art.addItem(LOGBOOK_KIND_LABELS[key], key)
        if item:
            idx = self.art.findData(item.art)
            if idx >= 0:
                self.art.setCurrentIndex(idx)
        self.odo = QLineEdit(str(item.odo_km) if item and item.odo_km is not None else "")
        self.odo.setPlaceholderText("optional")
        self.kosten = MoneyLineEdit(item.kosten_cent if item and item.kosten_cent else None)
        self.kosten.setPlaceholderText("optional · nur Anzeige")
        self.beschreibung = QLineEdit(item.beschreibung if item else "")

        self.add_row(labelled("Datum", self.date), labelled("Art", self.art))
        self.add_row(labelled("Titel *", self.titel),
                     labelled("km-Stand (optional)", self.odo))
        self.add_row(labelled("Kosten (optional)", self.kosten),
                     labelled("Beschreibung", self.beschreibung))

    def build(self) -> None:
        d = dates.parse_date(self.date.text())
        if d is None:
            raise ValueError("Bitte ein gültiges Datum (TT.MM.JJJJ) eingeben.")
        titel = self.titel.text().strip()
        if not titel:
            raise ValueError("Bitte einen Titel eingeben.")
        kosten = None
        if self.kosten.text().strip():
            kosten = self.kosten.cents()
            if kosten is None:
                raise ValueError("Bitte einen gültigen Kostenbetrag eingeben (oder leer lassen).")
        self.result_model = LogbookEntry(
            id=self._id, vehicle_id=self._vehicle.id, date=dates.to_iso(d),
            titel=titel, art=self.art.currentData(),
            odo_km=_opt_int(self.odo.text(), "km-Stand"),
            beschreibung=self.beschreibung.text().strip(),
            kosten_cent=kosten, cost_id=self._cost_id, rule_id=self._rule_id,
        )


# --- Own catalog entry -------------------------------------------------------------
class CatalogItemDialog(_BaseDialog):
    """Create/edit a user catalog entry (conditions kept simple: none)."""

    def __init__(self, item: CatalogItem | None = None, item_id: str = "", parent=None) -> None:
        super().__init__("Katalog-Eintrag bearbeiten" if item
                         else "Eigenen Katalog-Eintrag anlegen", parent)
        self._item = item
        self._item_id = item.id if item else item_id

        self.name = QLineEdit(item.name if item else "")
        self.name.setPlaceholderText("z. B. Unterbodenwäsche")
        self.kategorie = QComboBox()
        self.kategorie.addItems(CATALOG_CATEGORIES)
        if item and item.kategorie in CATALOG_CATEGORIES:
            self.kategorie.setCurrentText(item.kategorie)
        self.intervall_km = QLineEdit(
            str(item.intervall_km) if item and item.intervall_km else "")
        self.intervall_km.setPlaceholderText("optional")
        self.intervall_monate = QLineEdit(
            str(item.intervall_monate) if item and item.intervall_monate else "")
        self.intervall_monate.setPlaceholderText("optional")
        self.warum = QLineEdit(item.warum if item else "")
        self.warum.setPlaceholderText("Warum ist das sinnvoll?")
        self.produkt = QLineEdit(item.produkt_beispiel if item else "")
        self.produkt.setPlaceholderText("optional · z. B. Produktname")

        self.add_row(labelled("Bezeichnung *", self.name),
                     labelled("Kategorie", self.kategorie))
        self.add_row(labelled("Empfehlung: alle … km", self.intervall_km),
                     labelled("Empfehlung: alle … Monate", self.intervall_monate))
        self.add_row(labelled("Warum (Erklärtext)", self.warum))
        self.add_row(labelled("Produktbeispiel", self.produkt))

    def build(self) -> None:
        name = self.name.text().strip()
        if not name:
            raise ValueError("Bitte eine Bezeichnung eingeben.")
        km = _opt_int(self.intervall_km.text(), "km-Intervall")
        monate = _opt_int(self.intervall_monate.text(), "Monats-Intervall")
        self.result_model = CatalogItem(
            id=self._item_id, name=name, kategorie=self.kategorie.currentText(),
            bedingungen=(self._item.bedingungen if self._item else {}) or {},
            intervall_km=km or None, intervall_monate=monate or None,
            warum=self.warum.text().strip(),
            produkt_beispiel=self.produkt.text().strip(),
            quelle="user" if (self._item is None or self._item.quelle == "user") else self._item.quelle,
        )
