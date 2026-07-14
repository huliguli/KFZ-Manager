"""Tank-/Ladebuch: entries table with derived consumption and stats header."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from modules import dates, fuel
from modules.money import format_eur
from ui.dialogs import TankDialog
from ui.views.base_view import BaseView
from ui.widgets.common import (
    TablePanel,
    align_table_headers,
    heading,
    muted,
    primary_button,
    table_shortcuts,
)
from ui.widgets.toast import show_undo

_COLS = ["Datum", "km-Stand", "Art", "Menge", "Betrag", "Preis/Einheit",
         "Verbrauch", "Notiz"]


class TankbuchView(BaseView):
    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 24)
        layout.setSpacing(14)

        head = QHBoxLayout()
        head_box = QVBoxLayout()
        head_box.setSpacing(2)
        head_box.addWidget(heading("Tank- & Ladebuch"))
        self._sub = muted("")
        head_box.addWidget(self._sub)
        head.addLayout(head_box)
        head.addStretch(1)
        self._add_btn = primary_button("+ Tanken/Laden", ctx.colors)
        self._add_btn.clicked.connect(self.create_new)
        head.addWidget(self._add_btn)
        layout.addLayout(head)

        self._stats = QLabel("")
        self._stats.setObjectName("Muted")
        layout.addWidget(self._stats)

        self._table = QTableWidget(0, len(_COLS))
        self._table.setHorizontalHeaderLabels(_COLS)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(len(_COLS) - 1, QHeaderView.ResizeMode.Stretch)
        align_table_headers(self._table, right_cols=(1, 3, 4, 5, 6))
        self._table.itemDoubleClicked.connect(lambda _i: self._edit())
        table_shortcuts(self._table, self._edit, self._delete)

        self._panel = TablePanel(
            self._table, "Noch keine Einträge",
            "Erfasse deine erste Betankung oder Ladung — die km-Stände "
            "füttern auch die Fälligkeits-Prognosen des Pflegeplans.",
            "+ Ersten Eintrag anlegen", self.create_new)
        layout.addWidget(self._panel, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        edit_btn = QPushButton("Bearbeiten")
        edit_btn.setObjectName("Ghost")
        edit_btn.clicked.connect(self._edit)
        del_btn = QPushButton("Löschen")
        del_btn.setObjectName("Danger")
        del_btn.clicked.connect(self._delete)
        row.addWidget(edit_btn)
        row.addWidget(del_btn)
        layout.addLayout(row)

        self._entries: list = []

    # -- data -----------------------------------------------------------------
    def refresh(self) -> None:
        vehicle = self.ctx.vehicle
        self._add_btn.setEnabled(vehicle is not None)
        self._table.setRowCount(0)
        self._entries = []
        if vehicle is None or vehicle.id is None:
            self._sub.setText("Kein Fahrzeug gewählt.")
            self._stats.setText("")
            self._panel.update_state()
            return
        self._sub.setText(f"Fahrzeug: {vehicle.display_name}")

        chronological = self.ctx.tank.list_chronological(vehicle.id)
        stats = fuel.stats(chronological)
        per_entry = fuel.segment_consumption(chronological)

        pieces = []
        if stats.fuel_l_per_100km is not None:
            pieces.append("Ø " + fuel.format_consumption(stats.fuel_l_per_100km, "l/100 km"))
        if stats.energy_kwh_per_100km is not None:
            pieces.append("Ø " + fuel.format_consumption(stats.energy_kwh_per_100km,
                                                         "kWh/100 km"))
        if stats.cost_per_km_cent is not None:
            pieces.append(f"{stats.cost_per_km_cent:.1f} Cent/km".replace(".", ","))
        pieces.append(f"Gesamt: {format_eur(stats.total_cost_cents)}")
        self._stats.setText("   ·   ".join(pieces))

        self._entries = self.ctx.tank.list(vehicle.id)
        self._table.setRowCount(len(self._entries))
        for row, e in enumerate(self._entries):
            is_charge = e.art == "strom"
            menge = fuel.format_kwh(e.energie_wh) if is_charge else fuel.format_liters(e.menge_ml)
            qty = (e.energie_wh if is_charge else e.menge_ml) or 0
            unit_price = ""
            if qty > 0 and e.betrag_cent > 0:
                unit = "€/kWh" if is_charge else "€/l"
                unit_price = f"{e.betrag_cent / 100.0 / (qty / 1000.0):.3f} {unit}".replace(".", ",")
            verbrauch = ""
            if e.id in per_entry:
                verbrauch = fuel.format_consumption(per_entry[e.id], "l/100 km")
            art_label = "Laden" if is_charge else ("Tanken" + ("" if e.voll else " (Teil)"))
            values = [dates.format_date(e.date), fuel.format_km(e.odo_km), art_label,
                      menge, format_eur(e.betrag_cent), unit_price, verbrauch, e.notiz]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col in (1, 3, 4, 5, 6):
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._table.setItem(row, col, item)
        self._panel.update_state()

    # -- actions -----------------------------------------------------------------
    def create_new(self) -> bool:
        vehicle = self.ctx.vehicle
        if vehicle is None:
            return False
        dlg = TankDialog(vehicle, self.ctx.km_history(vehicle), parent=self)
        if dlg.exec():
            self.ctx.tank.add(dlg.result_model)
            self._maybe_bump_vehicle_km(dlg.result_model)
            self.ctx.notify_changed()
        return True

    def _selected(self):
        row = self._table.currentRow()
        return self._entries[row] if 0 <= row < len(self._entries) else None

    def _edit(self) -> None:
        entry = self._selected()
        vehicle = self.ctx.vehicle
        if entry is None or vehicle is None:
            return
        dlg = TankDialog(vehicle, self.ctx.km_history(vehicle), item=entry, parent=self)
        if dlg.exec():
            self.ctx.tank.update(dlg.result_model)
            self._maybe_bump_vehicle_km(dlg.result_model)
            self.ctx.notify_changed()

    def _delete(self) -> None:
        entry = self._selected()
        if entry is None or entry.id is None:
            return
        if QMessageBox.question(
                self, "Eintrag löschen",
                f"Eintrag vom {dates.format_date(entry.date)} wirklich löschen?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.ctx.tank.delete(entry.id)
        self.ctx.notify_changed()
        restore = entry

        def _undo() -> None:
            restore.id = None
            self.ctx.tank.add(restore)
            self.ctx.notify_changed()

        show_undo(self, "Eintrag gelöscht.", _undo)

    def _maybe_bump_vehicle_km(self, entry) -> None:
        """Keep the profile's km reading in sync with newer odometer values."""
        vehicle = self.ctx.vehicle
        if vehicle is None or vehicle.id is None:
            return
        if vehicle.km_stand is None or entry.odo_km > vehicle.km_stand:
            vehicle.km_stand = entry.odo_km
            vehicle.km_stand_datum = entry.date
            self.ctx.vehicles.update(vehicle)

    def focus_search(self) -> bool:
        return False
