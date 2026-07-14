"""Kosten: monthly cost entries with a per-category summary."""

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

from modules import dates
from modules.money import format_eur
from ui.dialogs import CostDialog
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

_COLS = ["Datum", "Kategorie", "Betrag", "km-Stand", "Notiz"]


class _MonthNav(QHBoxLayout):
    """Minimal month navigator (‹ Monat Jahr ›) shared by Kosten."""

    def __init__(self, on_change) -> None:
        super().__init__()
        self._on_change = on_change
        today = dates.today()
        self.year, self.month = today.year, today.month
        prev_btn = QPushButton("‹")
        prev_btn.setObjectName("Ghost")
        prev_btn.setFixedWidth(40)
        prev_btn.clicked.connect(lambda: self.step(-1))
        next_btn = QPushButton("›")
        next_btn.setObjectName("Ghost")
        next_btn.setFixedWidth(40)
        next_btn.clicked.connect(lambda: self.step(1))
        self._label = QLabel("")
        self._label.setObjectName("H2")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setMinimumWidth(190)
        self.addWidget(prev_btn)
        self.addWidget(self._label)
        self.addWidget(next_btn)
        self._update_label()

    def step(self, delta: int) -> None:
        self.year, self.month = dates.shift_month(self.year, self.month, delta)
        self._update_label()
        self._on_change()

    def _update_label(self) -> None:
        self._label.setText(f"{dates.month_name(self.month)} {self.year}")


class KostenView(BaseView):
    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 24)
        layout.setSpacing(14)

        head = QHBoxLayout()
        head_box = QVBoxLayout()
        head_box.setSpacing(2)
        head_box.addWidget(heading("Kosten"))
        self._sub = muted("")
        head_box.addWidget(self._sub)
        head.addLayout(head_box)
        head.addStretch(1)
        self._nav = _MonthNav(self.refresh)
        head.addLayout(self._nav)
        head.addSpacing(14)
        self._add_btn = primary_button("+ Kosten erfassen", ctx.colors)
        self._add_btn.clicked.connect(self.create_new)
        head.addWidget(self._add_btn)
        layout.addLayout(head)

        self._summary = QLabel("")
        self._summary.setObjectName("Muted")
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)

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
        align_table_headers(self._table, right_cols=(2, 3))
        self._table.itemDoubleClicked.connect(lambda _i: self._edit())
        table_shortcuts(self._table, self._edit, self._delete)

        self._panel = TablePanel(
            self._table, "Keine Kosten in diesem Monat",
            "Werkstatt, Versicherung, Steuer, Pflege, Zubehör — alles pro "
            "Fahrzeug an einem Ort.",
            "+ Kosten erfassen", self.create_new)
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

    def refresh(self) -> None:
        vehicle = self.ctx.vehicle
        self._add_btn.setEnabled(vehicle is not None)
        self._table.setRowCount(0)
        self._entries = []
        if vehicle is None or vehicle.id is None:
            self._sub.setText("Kein Fahrzeug gewählt.")
            self._summary.setText("")
            self._panel.update_state()
            return
        self._sub.setText(f"Fahrzeug: {vehicle.display_name}")

        year, month = self._nav.year, self._nav.month
        totals = self.ctx.costs.month_totals(vehicle.id, year, month)
        if totals:
            total = sum(totals.values())
            parts = [f"{cat}: {format_eur(val)}" for cat, val in
                     sorted(totals.items(), key=lambda kv: -kv[1])]
            self._summary.setText(f"Summe {format_eur(total)}   ·   " + "  ·  ".join(parts))
        else:
            self._summary.setText("Keine Ausgaben in diesem Monat erfasst.")

        self._entries = self.ctx.costs.list_for_month(vehicle.id, year, month)
        self._table.setRowCount(len(self._entries))
        for row, e in enumerate(self._entries):
            km = f"{e.odo_km:,} km".replace(",", ".") if e.odo_km is not None else ""
            values = [dates.format_date(e.date), e.kategorie,
                      format_eur(e.betrag_cent), km, e.notiz]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col in (2, 3):
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._table.setItem(row, col, item)
        self._panel.update_state()

    def month_navigator(self):
        return None  # _MonthNav is layout-based; Strg+Bild handled app-wide later

    def create_new(self) -> bool:
        vehicle = self.ctx.vehicle
        if vehicle is None:
            return False
        dlg = CostDialog(vehicle, parent=self)
        if dlg.exec():
            self.ctx.costs.add(dlg.result_model)
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
        dlg = CostDialog(vehicle, item=entry, parent=self)
        if dlg.exec():
            self.ctx.costs.update(dlg.result_model)
            self.ctx.notify_changed()

    def _delete(self) -> None:
        entry = self._selected()
        if entry is None or entry.id is None:
            return
        if QMessageBox.question(
                self, "Kosten löschen",
                f"{entry.kategorie} über {format_eur(entry.betrag_cent)} löschen?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        # Attachments of this cost row are removed with it (files + rows).
        from modules import attachments as attach_mod
        attach_mod.delete_for_entry(self.ctx.attachments, "cost", entry.id)
        self.ctx.costs.delete(entry.id)
        self.ctx.notify_changed()
        restore = entry

        def _undo() -> None:
            restore.id = None
            self.ctx.costs.add(restore)
            self.ctx.notify_changed()

        show_undo(self, "Kosteneintrag gelöscht.", _undo)
