"""Fahrzeug aus dem Katalog wählen — erspart das Abtippen des Profils.

Zwei gleichwertige Einstiege (bewusste Produktentscheidung, weil beide
Zielgruppen real sind):

* **Fahrzeugschein (HSN/TSN)** — zwei Zahlen aus Feld 2.1/2.2 lösen über die
  KBA-Liste sofort Hersteller und Handelsname auf. Für Alltagsfahrzeuge der
  schnellste Weg, schlägt jede Dropdown-Kaskade.
* **Kaskade Marke → Baureihe → Generation → Motorisierung** — für alle, die
  den Schein nicht zur Hand haben, und für Fahrzeuge, deren Schlüsselnummern
  nichts über den Motor verraten.

Beides mündet in dieselbe Auswahl; Freitext („nicht dabei") bleibt im
Fahrzeug-Dialog jederzeit möglich — der Katalog ist Angebot, nie Zwang.

**Motorcode:** Der Katalog schlägt vor, der NUTZER bestätigt. Nie umgekehrt —
siehe modules.vehicle_catalog (die Zuordnung ist mehrdeutig, ein geratener
Code würde falsche Wartungsempfehlungen auslösen). „Weiß ich nicht" ist ein
vollwertiger, folgenloser Ausgang.
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from modules import vehicle_catalog as vc
from modules.models import (
    AUFLADUNG_LABELS,
    KRAFTSTOFF_LABELS,
    MOTORBAUFORM_LABELS,
    label_for,
)
from ui.widgets.common import heading, muted, primary_button
from ui.widgets.inputs import labelled


@dataclass
class KatalogAuswahl:
    """Ergebnis des Dialogs — reine Daten, der Aufrufer entscheidet, was er nimmt."""
    motorisierung: vc.Motorisierung | None = None
    hersteller: str = ""          # aus HSN/TSN oder Katalog-Marke
    modell: str = ""              # aus HSN/TSN oder Baureihe+Generation
    motorcode: str = ""           # nur wenn vom Nutzer bestätigt
    motorcode_bestaetigt: bool = False


class KatalogDialog(QDialog):
    def __init__(self, db, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self.result_auswahl = KatalogAuswahl()
        self._vorschlaege: list[vc.MotorcodeVorschlag] = []

        self.setWindowTitle("Fahrzeug aus Katalog übernehmen")
        self.setModal(True)
        self.setMinimumWidth(660)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(14)
        root.addWidget(heading("Fahrzeug aus Katalog übernehmen", 2))
        root.addWidget(muted("Zwei Wege, gleiches Ziel — beide sind optional."))

        root.addWidget(self._schein_card())
        root.addWidget(self._kaskade_card())
        root.addWidget(self._motorcode_card())

        hint = QLabel("Katalogdaten ohne Gewähr — bitte gegen Fahrzeugschein "
                      "und Serviceheft prüfen. Maßgeblich sind die Angaben des "
                      "Herstellers. Alle Felder bleiben danach frei änderbar.")
        hint.setObjectName("Faint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Abbrechen")
        cancel.setObjectName("Ghost")
        cancel.clicked.connect(self.reject)
        self._ok = primary_button("Werte übernehmen", self._colors())
        self._ok.clicked.connect(self._accept)
        self._ok.setEnabled(False)
        buttons.addWidget(cancel)
        buttons.addWidget(self._ok)
        root.addLayout(buttons)

        self._load_marken()

    def _colors(self) -> dict:
        from ui import theme
        parent = self.parent()
        ctx = getattr(parent, "ctx", None)
        return ctx.colors if ctx is not None else theme.palette("light")

    # -- Einstieg 1: Fahrzeugschein ------------------------------------------
    def _schein_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Panel")
        box = QVBoxLayout(card)
        box.setContentsMargins(16, 12, 16, 12)
        box.setSpacing(8)
        title = QLabel("Aus dem Fahrzeugschein")
        title.setStyleSheet("font-weight: 700;")
        box.addWidget(title)

        row = QHBoxLayout()
        self._hsn = QLineEdit()
        self._hsn.setPlaceholderText("z. B. 0588")
        self._hsn.setMaxLength(4)
        self._hsn.setFixedWidth(110)
        self._tsn = QLineEdit()
        self._tsn.setPlaceholderText("z. B. 300")
        self._tsn.setMaxLength(3)
        self._tsn.setFixedWidth(110)
        find = QPushButton("Suchen")
        find.setObjectName("Ghost")
        find.clicked.connect(self._lookup_kba)
        self._hsn.returnPressed.connect(self._lookup_kba)
        self._tsn.returnPressed.connect(self._lookup_kba)
        row.addWidget(labelled("HSN (Feld 2.1)", self._hsn))
        row.addWidget(labelled("TSN (Feld 2.2)", self._tsn))
        row.addWidget(find, alignment=Qt.AlignmentFlag.AlignBottom)
        row.addStretch(1)
        box.addLayout(row)

        self._kba_result = QLabel("")
        self._kba_result.setObjectName("Muted")
        self._kba_result.setWordWrap(True)
        box.addWidget(self._kba_result)
        if not vc.kba_available(self.db):
            self._kba_result.setText("Schlüsselnummern-Liste ist nicht verfügbar.")
            for w in (self._hsn, self._tsn, find):
                w.setEnabled(False)
        return card

    def _lookup_kba(self) -> None:
        treffer = vc.kba_lookup(self.db, self._hsn.text(), self._tsn.text())
        if treffer is None:
            self._kba_result.setText(
                "Keine Übereinstimmung. HSN ist 4-stellig (Feld 2.1), TSN "
                "3-stellig (Feld 2.2) — bitte prüfen.")
            return
        self.result_auswahl.hersteller = treffer.hersteller
        self.result_auswahl.modell = treffer.handelsname
        self._kba_result.setText(
            f"Gefunden: {treffer.hersteller} · {treffer.handelsname}")
        self._ok.setEnabled(True)
        # Komfort: passende Marke in der Kaskade vorwählen, damit der Nutzer nur
        # noch Generation + Motor wählt. Findet der Katalog nichts, bleibt der
        # KBA-Treffer trotzdem nutzbar (Hersteller/Modell als Text).
        self._preselect_marke(treffer.hersteller)

    def _preselect_marke(self, hersteller: str) -> None:
        """Marke anhand des KBA-Herstellertexts vorwählen (best effort).

        Der KBA-Text ist eine Behördenschreibweise („VOLKSWAGEN-VW",
        „BAYER.MOT.WERKE-BMW"), unser Katalog führt die Wortmarke („Volkswagen",
        „BMW") — deshalb Teilstring-Vergleich statt Gleichheit; schlägt er fehl,
        passiert schlicht nichts.
        """
        needle = hersteller.upper()
        for index in range(self._marke.count()):
            name = (self._marke.itemText(index) or "").upper()
            if name and (name in needle or needle.startswith(name[:4])):
                self._marke.setCurrentIndex(index)
                return

    # -- Einstieg 2: Kaskade --------------------------------------------------
    def _kaskade_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Panel")
        box = QVBoxLayout(card)
        box.setContentsMargins(16, 12, 16, 12)
        box.setSpacing(8)
        title = QLabel("Oder auswählen")
        title.setStyleSheet("font-weight: 700;")
        box.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        self._marke = QComboBox()
        self._baureihe = QComboBox()
        self._generation = QComboBox()
        self._motor = QComboBox()
        for combo in (self._marke, self._baureihe, self._generation, self._motor):
            combo.setMinimumWidth(150)
        self._marke.currentIndexChanged.connect(self._on_marke)
        self._baureihe.currentIndexChanged.connect(self._on_baureihe)
        self._generation.currentIndexChanged.connect(self._on_generation)
        self._motor.currentIndexChanged.connect(self._on_motor)
        grid.addWidget(labelled("Marke", self._marke), 0, 0)
        grid.addWidget(labelled("Baureihe", self._baureihe), 0, 1)
        grid.addWidget(labelled("Generation", self._generation), 0, 2)
        grid.addWidget(labelled("Motorisierung", self._motor), 1, 0, 1, 3)
        box.addLayout(grid)

        self._motor_info = QLabel("")
        self._motor_info.setObjectName("Muted")
        self._motor_info.setWordWrap(True)
        box.addWidget(self._motor_info)
        self._quelle = QLabel("")
        self._quelle.setObjectName("Faint")
        self._quelle.setWordWrap(True)
        self._quelle.setOpenExternalLinks(True)
        box.addWidget(self._quelle)
        return card

    def _load_marken(self) -> None:
        self._marke.clear()
        self._marke.addItem("— bitte wählen —", None)
        for marke_id, name in vc.marken(self.db):
            self._marke.addItem(name, marke_id)
        if self._marke.count() <= 1:
            self._marke.setEnabled(False)
            self._motor_info.setText(
                "Der Fahrzeug-Katalog enthält noch keine Einträge — "
                "bitte die Felder von Hand ausfüllen.")

    def _on_marke(self) -> None:
        self._baureihe.clear()
        self._baureihe.addItem("— bitte wählen —", None)
        marke_id = self._marke.currentData()
        if marke_id:
            for bid, name in vc.baureihen(self.db, marke_id):
                self._baureihe.addItem(name, bid)

    def _on_baureihe(self) -> None:
        self._generation.clear()
        self._generation.addItem("— bitte wählen —", None)
        baureihe_id = self._baureihe.currentData()
        if baureihe_id:
            for gid, text in vc.generationen(self.db, baureihe_id):
                self._generation.addItem(text, gid)

    def _on_generation(self) -> None:
        self._motor.clear()
        self._motor.addItem("— bitte wählen —", None)
        gen_id = self._generation.currentData()
        if gen_id:
            for mot in vc.motorisierungen(self.db, gen_id):
                span = mot.zeitraum_text()
                self._motor.addItem(
                    f"{mot.anzeigename}{f'  ·  {span}' if span else ''}", mot.id)

    def _on_motor(self) -> None:
        motor_id = self._motor.currentData()
        if not motor_id:
            self._motor_info.setText("")
            self._quelle.setText("")
            self._reset_motorcode()
            return
        mot = vc.get_motorisierung(self.db, motor_id)
        if mot is None:
            return
        self.result_auswahl.motorisierung = mot
        # Anzeige der Werte, die übernommen würden — Transparenz statt Autorität.
        w = mot.werte
        bits = [label_for(w.get("kraftstoff"), KRAFTSTOFF_LABELS)]
        if w.get("hubraum_ccm"):
            bits.append(f"{w['hubraum_ccm']} cm³")
        if w.get("leistung_ps"):
            bits.append(f"{w['leistung_ps']} PS")
        if w.get("motorbauform"):
            bits.append(label_for(w["motorbauform"], MOTORBAUFORM_LABELS))
        if w.get("aufladung"):
            bits.append(label_for(w["aufladung"], AUFLADUNG_LABELS))
        if w.get("direkteinspritzung") is not None:
            bits.append("Direkteinspritzung" if w["direkteinspritzung"]
                        else "Saugrohreinspritzung")
        if w.get("oel_freigabe"):
            bits.append(f"Öl {w['oel_freigabe']}")
        self._motor_info.setText("Wird übernommen: " + " · ".join(b for b in bits if b))
        self._quelle.setText(
            f'Quelle: <a href="{mot.quelle_url}">{mot.quelle_url}</a><br>'
            f'„{mot.quelle_zitat}"')
        # Marke/Modell aus dem Katalog ableiten, falls kein KBA-Treffer da war.
        if not self.result_auswahl.hersteller:
            self.result_auswahl.hersteller = self._marke.currentText()
        if not self.result_auswahl.modell:
            gen_text = self._generation.currentText().split(" (")[0]
            self.result_auswahl.modell = f"{self._baureihe.currentText()} {gen_text}".strip()
        self._ok.setEnabled(True)
        self._load_motorcodes(motor_id)

    # -- Motorcode: vorschlagen, nie setzen -----------------------------------
    def _motorcode_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Panel")
        box = QVBoxLayout(card)
        box.setContentsMargins(16, 12, 16, 12)
        box.setSpacing(6)
        title = QLabel("Motorcode (optional)")
        title.setStyleSheet("font-weight: 700;")
        box.addWidget(title)
        self._mc_frage = QLabel(
            "Wähle zuerst eine Motorisierung — falls dazu Motorkennbuchstaben "
            "bekannt sind, kannst du sie hier bestätigen.")
        self._mc_frage.setObjectName("Muted")
        self._mc_frage.setWordWrap(True)
        box.addWidget(self._mc_frage)

        self._mc_group = QButtonGroup(self)
        self._mc_box = QWidget()
        self._mc_layout = QVBoxLayout(self._mc_box)
        self._mc_layout.setContentsMargins(0, 0, 0, 0)
        self._mc_layout.setSpacing(4)
        box.addWidget(self._mc_box)

        eigen = QHBoxLayout()
        self._mc_eigen = QLineEdit()
        self._mc_eigen.setPlaceholderText("z. B. CDHB")
        self._mc_eigen.setMaxLength(10)
        self._mc_eigen.setFixedWidth(140)
        self._mc_eigen.textChanged.connect(self._on_eigen_code)
        eigen.addWidget(QLabel("Anderer Code:"))
        eigen.addWidget(self._mc_eigen)
        eigen.addStretch(1)
        box.addLayout(eigen)

        hilfe = QLabel(
            "Der Motorcode steht in der Zulassungsbescheinigung Teil I bei "
            "Feld D.2, im CoC-Papier, im Serviceheft oder als Prägung am "
            "Motorblock. Bei älteren Fahrzeugen fehlt der Eintrag oft — "
            "dann einfach „Weiß ich nicht“ lassen. Nur ein bestätigter Code "
            "schaltet motorgenaue Empfehlungen frei.")
        hilfe.setObjectName("Faint")
        hilfe.setWordWrap(True)
        box.addWidget(hilfe)
        return card

    def _reset_motorcode(self) -> None:
        for btn in list(self._mc_group.buttons()):
            self._mc_group.removeButton(btn)
            btn.setParent(None)
        self._vorschlaege = []

    def _load_motorcodes(self, motorisierung_id: str) -> None:
        self._reset_motorcode()
        self._vorschlaege = vc.motorcode_vorschlaege(self.db, motorisierung_id)
        if not self._vorschlaege:
            self._mc_frage.setText(
                "Für diese Motorisierung sind keine gesicherten "
                "Motorkennbuchstaben hinterlegt. Du kannst deinen Code unten "
                "selbst eintragen.")
            return
        if len(self._vorschlaege) == 1:
            v = self._vorschlaege[0]
            self._mc_frage.setText(
                f"Vermutlich <b>{v.code}</b> — steht dieser Code in deinem "
                f"Fahrzeugschein (Feld D.2)?")
        else:
            self._mc_frage.setText(
                "Für diese Motorisierung sind mehrere Motorcodes möglich. "
                "Welcher steht in deinem Fahrzeugschein (Feld D.2)?")
        self._mc_frage.setTextFormat(Qt.TextFormat.RichText)

        for v in self._vorschlaege:
            extra = []
            if v.motorfamilie:
                extra.append(v.motorfamilie)
            if v.bj_von:
                extra.append(f"{v.bj_von}–{v.bj_bis}" if v.bj_bis else f"ab {v.bj_von}")
            label = f"Ja, {v.code}" + (f"  ({', '.join(extra)})" if extra else "")
            radio = QRadioButton(label)
            radio.setProperty("code", v.code)
            radio.toggled.connect(self._on_code_choice)
            self._mc_group.addButton(radio)
            self._mc_layout.addWidget(radio)
        # „Weiß ich nicht" ist die VORAUSWAHL: ohne aktive Bestätigung des
        # Nutzers darf kein Code gesetzt werden.
        unknown = QRadioButton("Weiß ich nicht / steht nicht im Schein")
        unknown.setProperty("code", "")
        unknown.setChecked(True)
        unknown.toggled.connect(self._on_code_choice)
        self._mc_group.addButton(unknown)
        self._mc_layout.addWidget(unknown)

    def _on_code_choice(self, checked: bool) -> None:
        if not checked:
            return
        button = self.sender()
        code = str(button.property("code") or "")
        if code:
            self._mc_eigen.clear()
        self.result_auswahl.motorcode = code
        self.result_auswahl.motorcode_bestaetigt = bool(code)

    def _on_eigen_code(self, text: str) -> None:
        code = text.strip().upper()
        if not code:
            return
        # Freie Eingabe schlägt jede Vorauswahl — sie kommt direkt vom Nutzer.
        for btn in self._mc_group.buttons():
            btn.setChecked(False)
        self.result_auswahl.motorcode = code
        self.result_auswahl.motorcode_bestaetigt = True

    def _accept(self) -> None:
        self.accept()

    @staticmethod
    def pick(db, parent=None) -> KatalogAuswahl | None:
        dlg = KatalogDialog(db, parent)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        return dlg.result_auswahl
