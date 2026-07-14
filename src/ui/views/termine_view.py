"""Termine: TÜV/HU, Inspektion & Co. — fällig per Datum und/oder km-Stand."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from modules import dates, reminders
from modules.fuel import current_km
from modules.models import LogbookEntry
from ui import theme
from ui.dialogs import AppointmentDialog
from ui.views.base_view import BaseView
from ui.widgets.common import (
    Pill,
    TablePanel,
    align_table_headers,
    heading,
    muted,
    pill_cell,
    primary_button,
    table_shortcuts,
)

_COLS = ["Status", "Typ", "Fällig", "Beschreibung"]

_AMPEL = {
    reminders.STATUS_OVERDUE: ("überfällig", "red"),
    reminders.STATUS_SOON: ("bald fällig", "amber"),
    reminders.STATUS_OK: ("ok", "green"),
}


class TermineView(BaseView):
    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 24)
        layout.setSpacing(14)

        head = QHBoxLayout()
        head_box = QVBoxLayout()
        head_box.setSpacing(2)
        head_box.addWidget(heading("Termine & Erinnerungen"))
        self._sub = muted("")
        head_box.addWidget(self._sub)
        head.addLayout(head_box)
        head.addStretch(1)
        self._show_done = QCheckBox("Erledigte anzeigen")
        self._show_done.toggled.connect(lambda _v: self.refresh())
        head.addWidget(self._show_done)
        head.addSpacing(10)
        self._add_btn = primary_button("+ Termin", ctx.colors)
        self._add_btn.clicked.connect(self.create_new)
        head.addWidget(self._add_btn)
        layout.addLayout(head)

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
        align_table_headers(self._table)
        self._table.itemDoubleClicked.connect(lambda _i: self._edit())
        table_shortcuts(self._table, self._edit, self._delete)

        self._panel = TablePanel(
            self._table, "Keine Termine",
            "TÜV/HU, Inspektion, Versicherung, Reifenwechsel — die App "
            "erinnert dich beim Start mit einstellbarem Vorlauf.",
            "+ Termin anlegen", self.create_new)
        layout.addWidget(self._panel, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        done_btn = QPushButton("Als erledigt markieren")
        done_btn.setObjectName("Ghost")
        done_btn.clicked.connect(self._complete)
        edit_btn = QPushButton("Bearbeiten")
        edit_btn.setObjectName("Ghost")
        edit_btn.clicked.connect(self._edit)
        del_btn = QPushButton("Löschen")
        del_btn.setObjectName("Danger")
        del_btn.clicked.connect(self._delete)
        row.addWidget(done_btn)
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
            self._panel.update_state()
            return
        self._sub.setText(f"Fahrzeug: {vehicle.display_name}")

        km_now = current_km(self.ctx.km_history(vehicle))
        lead_days = int(self.ctx.config.get("reminder_lead_days", 30))
        lead_km = int(self.ctx.config.get("reminder_lead_km", 1000))
        colors = self.ctx.colors

        self._entries = self.ctx.appointments.list(
            vehicle.id, include_done=self._show_done.isChecked())
        self._table.setRowCount(len(self._entries))
        for row, appt in enumerate(self._entries):
            if appt.erledigt:
                text, key = ("erledigt", "grey")
                detail = (f"am {dates.format_date(appt.erledigt_datum)}"
                          if appt.erledigt_datum else "")
            else:
                status, detail = reminders.appointment_status(
                    appt, km_now, lead_days=lead_days, lead_km=lead_km)
                text, key = _AMPEL.get(status, ("ok", "green"))
            pill = Pill(text, theme.ampel_color(key, colors),
                        theme.ampel_soft(key, colors))
            self._table.setCellWidget(row, 0, pill_cell(pill))
            self._table.setItem(row, 1, QTableWidgetItem(appt.typ))
            self._table.setItem(row, 2, QTableWidgetItem(detail))
            self._table.setItem(row, 3, QTableWidgetItem(appt.beschreibung))
        self._panel.update_state()

    def create_new(self) -> bool:
        vehicle = self.ctx.vehicle
        if vehicle is None:
            return False
        dlg = AppointmentDialog(vehicle, parent=self)
        if dlg.exec():
            self.ctx.appointments.add(dlg.result_model)
            self.ctx.notify_changed()
        return True

    def _selected(self):
        row = self._table.currentRow()
        return self._entries[row] if 0 <= row < len(self._entries) else None

    def _edit(self) -> None:
        appt = self._selected()
        vehicle = self.ctx.vehicle
        if appt is None or vehicle is None:
            return
        dlg = AppointmentDialog(vehicle, item=appt, parent=self)
        if dlg.exec():
            self.ctx.appointments.update(dlg.result_model)
            self.ctx.notify_changed()

    def _complete(self) -> None:
        appt = self._selected()
        vehicle = self.ctx.vehicle
        if appt is None or appt.erledigt or vehicle is None:
            return
        appt.erledigt = True
        appt.erledigt_datum = dates.to_iso(dates.today())
        self.ctx.appointments.update(appt)
        # A completed appointment becomes part of the vehicle's history.
        self.ctx.logbook.add(LogbookEntry(
            vehicle_id=vehicle.id, date=appt.erledigt_datum,
            titel=appt.typ, art="wartung",
            beschreibung=appt.beschreibung or "Termin erledigt",
        ))
        self.ctx.notify_changed()

    def _delete(self) -> None:
        appt = self._selected()
        if appt is None or appt.id is None:
            return
        if QMessageBox.question(
                self, "Termin löschen", f"Termin „{appt.typ}“ wirklich löschen?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.ctx.appointments.delete(appt.id)
        self.ctx.notify_changed()
