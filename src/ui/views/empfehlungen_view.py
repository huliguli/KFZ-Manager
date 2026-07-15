"""Empfehlungen: catalog suggestions filtered by the vehicle profile.

Each matching suggestion can be adopted into the Pflegeplan (creates an
interval rule linked via catalog_id), hidden per vehicle, or complemented by
user-created catalog entries. A visible disclaimer reminds that the
manufacturer's service schedule always wins.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from modules import catalog as catalog_mod
from modules import vehicle_catalog
from modules.fuel import current_km
from modules.models import CareRule
from ui.dialogs import CatalogItemDialog
from ui.views.base_view import BaseView
from ui.widgets.common import clear_layout, heading, muted, primary_button


class EmpfehlungenView(BaseView):
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
        self._show_hidden = False

    def refresh(self) -> None:
        clear_layout(self._layout)
        vehicle = self.ctx.vehicle

        head = QHBoxLayout()
        head_box = QVBoxLayout()
        head_box.setSpacing(2)
        head_box.addWidget(heading("Empfehlungen"))
        sub = muted(f"Fahrzeug: {vehicle.display_name}" if vehicle
                    else "Kein Fahrzeug gewählt.")
        head_box.addWidget(sub)
        head.addLayout(head_box)
        head.addStretch(1)
        toggle = QCheckBox("Ausgeblendete anzeigen")
        toggle.setChecked(self._show_hidden)
        toggle.toggled.connect(self._toggle_hidden)
        head.addWidget(toggle)
        head.addSpacing(10)
        own_btn = primary_button("+ Eigener Eintrag", self.ctx.colors)
        own_btn.clicked.connect(self._add_own)
        head.addWidget(own_btn)
        self._layout.addLayout(head)

        disclaimer = QLabel(
            "Hinweis: Diese Empfehlungen ersetzen keine Herstellervorgaben — "
            "das Serviceheft deines Fahrzeugs hat immer Vorrang.")
        disclaimer.setObjectName("Faint")
        disclaimer.setWordWrap(True)
        self._layout.addWidget(disclaimer)

        if vehicle is None or vehicle.id is None:
            self._layout.addStretch(1)
            return

        items = self.ctx.catalog.list()
        hidden = self.ctx.catalog.hidden_ids(vehicle.id)
        adopted = {i.id for i in items
                   if self.ctx.rules.has_catalog_rule(vehicle.id, i.id)}
        km_now = current_km(self.ctx.km_history(vehicle))
        # Motorfamilie nur aus einem BESTÄTIGTEN Motorcode und nur bei
        # eindeutiger Auflösung (siehe modules.vehicle_catalog) — sonst None,
        # und motorcode-abhängige Empfehlungen bleiben still.
        motorfamilie = None
        if vehicle.motorcode_herkunft == "nutzer" and vehicle.motorcode:
            motorfamilie = vehicle_catalog.motorfamilie_fuer_code(
                self.ctx.db, vehicle.motorcode)
        suggestions = catalog_mod.suggestions_for(
            items, vehicle, hidden, adopted, km_now, motorfamilie=motorfamilie)

        if not suggestions and not self._show_hidden:
            empty = QLabel(
                "Keine offenen Empfehlungen für dieses Profil. Je vollständiger "
                "das Fahrzeugprofil (Kraftstoff, Einspritzung, Filter, "
                "Fahrprofil …), desto gezielter die Vorschläge.")
            empty.setObjectName("Muted")
            empty.setWordWrap(True)
            self._layout.addWidget(empty)

        for item in suggestions:
            self._layout.addWidget(self._suggestion_card(item, vehicle, hidden=False))

        if self._show_hidden:
            hidden_items = [i for i in items if i.id in hidden]
            if hidden_items:
                self._layout.addWidget(heading("Ausgeblendet", 2))
                for item in hidden_items:
                    self._layout.addWidget(self._suggestion_card(item, vehicle, hidden=True))

        self._layout.addStretch(1)

    def _toggle_hidden(self, value: bool) -> None:
        self._show_hidden = bool(value)
        self.refresh()

    def _suggestion_card(self, item, vehicle, hidden: bool) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        box = QVBoxLayout(card)
        box.setContentsMargins(20, 14, 20, 14)
        box.setSpacing(6)

        top = QHBoxLayout()
        name = QLabel(item.name)
        name.setObjectName("H2")
        cat = QLabel(f"{item.kategorie} · {item.interval_text()}"
                     + (" · eigener Eintrag" if item.quelle == "user" else ""))
        cat.setObjectName("Faint")
        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        title_box.addWidget(name)
        title_box.addWidget(cat)
        top.addLayout(title_box)
        top.addStretch(1)

        if hidden:
            unhide = QPushButton("Wieder einblenden")
            unhide.setObjectName("Ghost")
            unhide.clicked.connect(lambda _c, i=item: self._unhide(i))
            top.addWidget(unhide)
        else:
            hide_btn = QPushButton("Ausblenden")
            hide_btn.setObjectName("Ghost")
            hide_btn.clicked.connect(lambda _c, i=item: self._hide(i))
            adopt = primary_button("In Pflegeplan übernehmen", self.ctx.colors)
            adopt.clicked.connect(lambda _c, i=item: self._adopt(i))
            top.addWidget(hide_btn)
            top.addWidget(adopt)
        if item.quelle == "user":
            edit_btn = QPushButton("Bearbeiten")
            edit_btn.setObjectName("Ghost")
            edit_btn.clicked.connect(lambda _c, i=item: self._edit_own(i))
            top.addWidget(edit_btn)
        box.addLayout(top)

        if item.warum:
            why = QLabel(item.warum)
            why.setWordWrap(True)
            box.addWidget(why)
        if item.produkt_beispiel:
            product = QLabel(f"Produktbeispiel: {item.produkt_beispiel}")
            product.setObjectName("Muted")
            product.setWordWrap(True)
            box.addWidget(product)
        return card

    # -- actions ---------------------------------------------------------------
    def _adopt(self, item) -> None:
        vehicle = self.ctx.vehicle
        if vehicle is None or vehicle.id is None:
            return
        self.ctx.rules.add(CareRule(
            vehicle_id=vehicle.id, catalog_id=item.id, name=item.name,
            kategorie=item.kategorie, intervall_km=item.intervall_km,
            intervall_monate=item.intervall_monate, notiz=item.warum))
        self.ctx.notify_changed()

    def _hide(self, item) -> None:
        if self.ctx.vehicle_id is None:
            return
        self.ctx.catalog.hide(self.ctx.vehicle_id, item.id)
        self.refresh()

    def _unhide(self, item) -> None:
        if self.ctx.vehicle_id is None:
            return
        self.ctx.catalog.unhide(self.ctx.vehicle_id, item.id)
        self.refresh()

    def _add_own(self) -> None:
        existing = {i.id for i in self.ctx.catalog.list()}
        dlg = CatalogItemDialog(item_id=catalog_mod.next_user_id(existing), parent=self)
        if dlg.exec():
            self.ctx.catalog.add(dlg.result_model)
            self.refresh()

    def _edit_own(self, item) -> None:
        dlg = CatalogItemDialog(item=item, parent=self)
        if dlg.exec():
            self.ctx.catalog.update(dlg.result_model)
            self.refresh()

    def create_new(self) -> bool:
        self._add_own()
        return True
