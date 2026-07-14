"""Fahrzeuge: manage the vehicle pool (add/edit/delete, profile overview)."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from modules import attachments as attach_mod
from modules import dates
from modules.models import (
    AUFLADUNG_LABELS,
    FAHRPROFIL_LABELS,
    GETRIEBE_LABELS,
    KRAFTSTOFF_LABELS,
    MOTORBAUFORM_LABELS,
    PARTIKELFILTER_LABELS,
    label_for,
)
from ui.dialogs import VehicleDialog
from ui.views.base_view import BaseView
from ui.widgets.common import clear_layout, heading, muted, primary_button


class FahrzeugeView(BaseView):
    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        outer.addWidget(scroll)
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        scroll.setWidget(container)
        self._layout = QVBoxLayout(container)
        self._layout.setContentsMargins(30, 26, 30, 24)
        self._layout.setSpacing(12)

    def refresh(self) -> None:
        clear_layout(self._layout)
        head = QHBoxLayout()
        head_box = QVBoxLayout()
        head_box.setSpacing(2)
        head_box.addWidget(heading("Fahrzeuge"))
        head_box.addWidget(muted("Profile treiben die Empfehlungen — je "
                                 "vollständiger, desto passgenauer."))
        head.addLayout(head_box)
        head.addStretch(1)
        add_btn = primary_button("+ Fahrzeug anlegen", self.ctx.colors)
        add_btn.clicked.connect(self.create_new)
        head.addWidget(add_btn)
        self._layout.addLayout(head)

        vehicles = self.ctx.vehicles.list()
        if not vehicles:
            empty = QLabel("Noch kein Fahrzeug angelegt.")
            empty.setObjectName("Muted")
            self._layout.addWidget(empty)

        for vehicle in vehicles:
            self._layout.addWidget(self._vehicle_card(vehicle))
        self._layout.addStretch(1)

    def _vehicle_card(self, v) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        box = QVBoxLayout(card)
        box.setContentsMargins(20, 14, 20, 14)
        box.setSpacing(6)

        top = QHBoxLayout()
        name = QLabel(v.display_name + ("   (aktiv)" if v.id == self.ctx.vehicle_id else ""))
        name.setObjectName("H2")
        top.addWidget(name)
        top.addStretch(1)
        if v.id != self.ctx.vehicle_id:
            select_btn = QPushButton("Auswählen")
            select_btn.setObjectName("Ghost")
            select_btn.clicked.connect(lambda _c, vid=v.id: self.ctx.set_vehicle(vid))
            top.addWidget(select_btn)
        edit_btn = QPushButton("Bearbeiten")
        edit_btn.setObjectName("Ghost")
        edit_btn.clicked.connect(lambda _c, veh=v: self._edit(veh))
        del_btn = QPushButton("Löschen")
        del_btn.setObjectName("Danger")
        del_btn.clicked.connect(lambda _c, veh=v: self._delete(veh))
        top.addWidget(edit_btn)
        top.addWidget(del_btn)
        box.addLayout(top)

        bits = []
        if v.kennzeichen:
            bits.append(v.kennzeichen)
        if v.erstzulassung:
            bits.append(f"EZ {dates.format_date(v.erstzulassung)}")
        if v.km_stand is not None:
            bits.append(f"{v.km_stand:,} km".replace(",", "."))
        bits.append(label_for(v.kraftstoff, KRAFTSTOFF_LABELS))
        if v.motorbauform:
            bits.append(label_for(v.motorbauform, MOTORBAUFORM_LABELS))
        if v.hubraum_ccm:
            bits.append(f"{v.hubraum_ccm} cm³")
        if v.leistung_ps:
            bits.append(f"{v.leistung_ps} PS")
        if v.aufladung:
            bits.append(label_for(v.aufladung, AUFLADUNG_LABELS))
        if v.direkteinspritzung is not None:
            bits.append("Direkteinspritzung" if v.direkteinspritzung
                        else "Saugrohreinspritzung")
        if v.partikelfilter and v.partikelfilter != "keiner":
            bits.append(label_for(v.partikelfilter, PARTIKELFILTER_LABELS))
        if v.getriebe:
            bits.append(label_for(v.getriebe, GETRIEBE_LABELS))
        if v.oel_viskositaet:
            bits.append(f"Öl {v.oel_viskositaet}"
                        + (f" ({v.oel_freigabe})" if v.oel_freigabe else ""))
        if v.fahrprofil:
            bits.append(label_for(v.fahrprofil, FAHRPROFIL_LABELS))
        profile = QLabel(" · ".join(bits))
        profile.setObjectName("Muted")
        profile.setWordWrap(True)
        box.addWidget(profile)
        if v.notiz:
            note = QLabel(v.notiz)
            note.setObjectName("Faint")
            note.setWordWrap(True)
            box.addWidget(note)
        return card

    def create_new(self) -> bool:
        dlg = VehicleDialog(parent=self)
        if dlg.exec():
            new_id = self.ctx.vehicles.add(dlg.result_model)
            # The first vehicle (or a newly created one) becomes active.
            self.ctx.set_vehicle(new_id)
            self.ctx.notify_changed()
        return True

    def _edit(self, vehicle) -> None:
        dlg = VehicleDialog(item=vehicle, parent=self)
        if dlg.exec():
            self.ctx.vehicles.update(dlg.result_model)
            self.ctx.notify_changed()

    def _delete(self, vehicle) -> None:
        if vehicle.id is None:
            return
        if QMessageBox.warning(
                self, "Fahrzeug löschen",
                f"„{vehicle.display_name}“ mit ALLEN Einträgen (Tankbuch, "
                "Kosten, Termine, Pflegeplan, Scheckheft, Anhänge) löschen?\n"
                "Das kann nicht rückgängig gemacht werden.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        # Delete attachment FILES first (DB rows fall via ON DELETE CASCADE).
        for att in self.ctx.attachments.list_all():
            if att.vehicle_id == vehicle.id:
                attach_mod.delete_file(att.rel_path)
        self.ctx.vehicles.delete(vehicle.id)
        if self.ctx.vehicle_id == vehicle.id:
            remaining = self.ctx.vehicles.list()
            self.ctx.set_vehicle(remaining[0].id if remaining else None)
        self.ctx.notify_changed()
