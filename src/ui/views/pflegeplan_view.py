"""Pflegeplan: interval rules with due forecast and the Erledigen flow."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from modules import dates, intervals
from modules.fuel import current_km
from modules.models import Cost, LogbookEntry
from ui import theme
from ui.dialogs import CareRuleDialog, CompleteRuleDialog
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

_COLS = ["Status", "Pflege", "Intervall", "Fälligkeit", "Zuletzt"]

_AMPEL = {
    intervals.STATUS_OVERDUE: ("überfällig", "red"),
    intervals.STATUS_SOON: ("bald fällig", "amber"),
    intervals.STATUS_OK: ("ok", "green"),
    intervals.STATUS_UNKNOWN: ("offen", "grey"),
}


class PflegeplanView(BaseView):
    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 24)
        layout.setSpacing(14)

        head = QHBoxLayout()
        head_box = QVBoxLayout()
        head_box.setSpacing(2)
        head_box.addWidget(heading("Pflegeplan"))
        self._sub = muted("")
        head_box.addWidget(self._sub)
        head.addLayout(head_box)
        head.addStretch(1)
        self._add_btn = primary_button("+ Pflege-Regel", ctx.colors)
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
        self._table.setWordWrap(True)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        align_table_headers(self._table)
        self._table.itemDoubleClicked.connect(lambda _i: self._edit())
        table_shortcuts(self._table, self._edit, self._delete)

        self._panel = TablePanel(
            self._table, "Noch keine Pflege-Regeln",
            "Regeln wie „alle 15.000 km oder 12 Monate“ — die App rechnet "
            "km-Intervalle über deine Fahrleistung in ein konkretes Datum um. "
            "Tipp: Die Ansicht „Empfehlungen“ schlägt passende Regeln für "
            "dein Fahrzeugprofil vor.",
            "+ Erste Regel anlegen", self.create_new)
        layout.addWidget(self._panel, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        done_btn = primary_button("Erledigt …", ctx.colors)
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

        self._statuses: list[intervals.RuleStatus] = []

    def refresh(self) -> None:
        vehicle = self.ctx.vehicle
        self._add_btn.setEnabled(vehicle is not None)
        self._table.setRowCount(0)
        self._statuses = []
        if vehicle is None or vehicle.id is None:
            self._sub.setText("Kein Fahrzeug gewählt.")
            self._panel.update_state()
            return

        history = self.ctx.km_history(vehicle)
        rate = intervals.evaluate_all(
            self.ctx.rules.list(vehicle.id), history,
            lead_days=int(self.ctx.config.get("reminder_lead_days", 30)),
            lead_km=int(self.ctx.config.get("reminder_lead_km", 1000)))
        self._statuses = rate
        rate_info = ""
        if rate and rate[0].km_per_day:
            rate_info = (f" · Ø-Fahrleistung: {rate[0].km_per_day:.1f} km/Tag"
                         .replace(".", ","))
        self._sub.setText(f"Fahrzeug: {vehicle.display_name}{rate_info}")

        colors = self.ctx.colors
        self._table.setRowCount(len(self._statuses))
        for row, s in enumerate(self._statuses):
            text, key = _AMPEL.get(s.status, ("offen", "grey"))
            pill = Pill(text, theme.ampel_color(key, colors),
                        theme.ampel_soft(key, colors))
            self._table.setCellWidget(row, 0, pill_cell(pill))
            self._table.setItem(row, 1, QTableWidgetItem(s.rule.name))
            self._table.setItem(row, 2, QTableWidgetItem(s.rule.interval_text()))
            due = intervals.status_text(s)
            if s.hint:
                due += f"\n{s.hint}"
            self._table.setItem(row, 3, QTableWidgetItem(due))
            last = ""
            if s.rule.letzte_datum:
                last = dates.format_date(s.rule.letzte_datum)
                if s.rule.letzte_km is not None:
                    last += f" · {s.rule.letzte_km:,} km".replace(",", ".")
            self._table.setItem(row, 4, QTableWidgetItem(last or "nie"))
        self._table.resizeRowsToContents()
        self._panel.update_state()

    def create_new(self) -> bool:
        vehicle = self.ctx.vehicle
        if vehicle is None:
            return False
        dlg = CareRuleDialog(vehicle, parent=self)
        if dlg.exec():
            self.ctx.rules.add(dlg.result_model)
            self.ctx.notify_changed()
        return True

    def _selected(self):
        row = self._table.currentRow()
        return self._statuses[row].rule if 0 <= row < len(self._statuses) else None

    def _edit(self) -> None:
        rule = self._selected()
        vehicle = self.ctx.vehicle
        if rule is None or vehicle is None:
            return
        dlg = CareRuleDialog(vehicle, item=rule, parent=self)
        if dlg.exec():
            self.ctx.rules.update(dlg.result_model)
            self.ctx.notify_changed()

    def _complete(self) -> None:
        """Erledigen: resets the interval, optionally books a cost, writes the
        Scheckheft entry — the full completion flow from the spec."""
        rule = self._selected()
        vehicle = self.ctx.vehicle
        if rule is None or rule.id is None or vehicle is None:
            return
        km_now = current_km(self.ctx.km_history(vehicle))
        dlg = CompleteRuleDialog(rule, km_now, parent=self)
        if not dlg.exec():
            return
        data = dlg.result_model

        # 1) Optional linked cost entry.
        cost_id = None
        if data["kosten_cent"]:
            cost_id = self.ctx.costs.add(Cost(
                vehicle_id=vehicle.id, date=data["datum"], kategorie="Pflege",
                betrag_cent=data["kosten_cent"],
                notiz=f"{rule.name}" + (f" — {data['notiz']}" if data["notiz"] else ""),
                odo_km=data["km"]))

        # 2) Scheckheft entry (timeline).
        self.ctx.logbook.add(LogbookEntry(
            vehicle_id=vehicle.id, date=data["datum"], odo_km=data["km"],
            art="pflege", titel=rule.name, beschreibung=data["notiz"],
            kosten_cent=data["kosten_cent"], cost_id=cost_id, rule_id=rule.id))

        # 3) Reset the interval anchor.
        rule.letzte_datum = data["datum"]
        if data["km"] is not None:
            rule.letzte_km = data["km"]
        self.ctx.rules.update(rule)

        # 4) Keep the profile km fresh when the completion is the newest reading.
        if data["km"] is not None and (vehicle.km_stand is None
                                       or data["km"] > vehicle.km_stand):
            vehicle.km_stand = data["km"]
            vehicle.km_stand_datum = data["datum"]
            self.ctx.vehicles.update(vehicle)

        self.ctx.notify_changed()

    def _delete(self) -> None:
        rule = self._selected()
        if rule is None or rule.id is None:
            return
        if QMessageBox.question(
                self, "Regel löschen",
                f"Pflege-Regel „{rule.name}“ wirklich löschen?\n"
                "Scheckheft-Einträge bleiben erhalten.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.ctx.rules.delete(rule.id)
        self.ctx.notify_changed()
