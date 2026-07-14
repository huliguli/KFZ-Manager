"""Dashboard: key figures, next due items and the family budget card."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from modules import dates, fuel, interop, intervals, reminders
from modules.money import format_eur
from ui import theme
from ui.views.base_view import BaseView
from ui.widgets.common import StatCard, clear_layout, heading, muted


_STATUS_AMPEL = {
    intervals.STATUS_OVERDUE: "red",
    intervals.STATUS_SOON: "amber",
    intervals.STATUS_OK: "green",
    intervals.STATUS_UNKNOWN: "grey",
}


class DashboardView(BaseView):
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
        self._layout.setSpacing(16)

    def refresh(self) -> None:
        clear_layout(self._layout)
        vehicle = self.ctx.vehicle
        today = dates.today()

        title = vehicle.display_name if vehicle else "Kein Fahrzeug angelegt"
        self._layout.addWidget(heading(title))
        self._layout.addWidget(muted(
            f"Überblick für {dates.month_name(today.month)} {today.year}."))

        if vehicle is None or vehicle.id is None:
            hint = QLabel("Lege über den Umschalter oben rechts dein erstes "
                          "Fahrzeug an — alle Ansichten beziehen sich auf das "
                          "gewählte Fahrzeug.")
            hint.setObjectName("Muted")
            hint.setWordWrap(True)
            self._layout.addWidget(hint)
            self._layout.addStretch(1)
            return

        colors = self.ctx.colors
        history = self.ctx.km_history(vehicle)
        km_now = fuel.current_km(history)
        entries = self.ctx.tank.list_chronological(vehicle.id)
        stats = fuel.stats(entries)
        month_costs = self.ctx.costs.month_total_all(vehicle.id, today.year, today.month)

        cards = QGridLayout()
        cards.setHorizontalSpacing(14)
        cards.setVerticalSpacing(14)

        km_card = StatCard("Kilometerstand", colors["primary"])
        km_card.set_value(fuel.format_km(km_now))
        rate = fuel.average_km_per_day(history)
        km_card.set_hint(f"Ø {rate * 30:.0f} km/Monat (letzte ~90 Tage)".replace(".", ",")
                         if rate else "Noch zu wenige km-Stände für einen Schnitt.")
        cards.addWidget(km_card, 0, 0)

        if vehicle.kraftstoff == "elektro":
            usage_value = fuel.format_consumption(stats.energy_kwh_per_100km, "kWh/100 km")
        else:
            usage_value = fuel.format_consumption(stats.fuel_l_per_100km, "l/100 km")
        usage_card = StatCard("Ø Verbrauch", colors["blue"])
        usage_card.set_value(usage_value)
        usage_card.set_hint("Voll-zu-voll über das gesamte Tankbuch."
                            if vehicle.kraftstoff != "elektro"
                            else "Über aufeinanderfolgende Ladungen.")
        cards.addWidget(usage_card, 0, 1)

        cost_card = StatCard("Kosten diesen Monat", colors["amber"])
        cost_card.set_value(format_eur(month_costs))
        if stats.cost_per_km_cent is not None:
            cost_card.set_hint(
                f"Tankbuch gesamt: {stats.cost_per_km_cent:.1f} Cent/km".replace(".", ","))
        cards.addWidget(cost_card, 0, 2)
        self._layout.addLayout(cards)

        # Family budget card — appears automatically once the sister app
        # provides interop_ausgaben_monat (HaushaltsManager >= 3.6).
        context = interop.budget_context(
            self.ctx.sister, month_costs, today.year, today.month)
        if context:
            card = QFrame()
            card.setObjectName("Card")
            box = QVBoxLayout(card)
            box.setContentsMargins(22, 16, 22, 16)
            title_lbl = QLabel("HAUSHALTS-KONTEXT")
            title_lbl.setObjectName("CardTitle")
            text = QLabel(context)
            text.setWordWrap(True)
            box.addWidget(title_lbl)
            box.addWidget(text)
            self._layout.addWidget(card)
        elif self.ctx.sister.status == "ohne-interop":
            note = QLabel(self.ctx.sister.message)
            note.setObjectName("Faint")
            self._layout.addWidget(note)

        # Next due items (appointments + care rules).
        self._layout.addWidget(heading("Als Nächstes fällig", 2))
        due_box = QVBoxLayout()
        due_box.setSpacing(6)
        items = reminders.collect(
            [vehicle],
            {vehicle.id: self.ctx.appointments.list(vehicle.id)},
            {vehicle.id: self.ctx.rules.list(vehicle.id)},
            {vehicle.id: history},
            lead_days=int(self.ctx.config.get("reminder_lead_days", 30)),
            lead_km=int(self.ctx.config.get("reminder_lead_km", 1000)),
        )
        if not items:
            ok = QLabel("Alles im grünen Bereich — nichts ist fällig oder bald fällig.")
            ok.setObjectName("Muted")
            due_box.addWidget(ok)
        for item in items[:8]:
            row = QFrame()
            row.setObjectName("Panel")
            line = QHBoxLayout(row)
            line.setContentsMargins(14, 10, 14, 10)
            kind = "Termin" if item.kind == "termin" else "Pflege"
            label = QLabel(f"{kind}: {item.title}")
            label.setStyleSheet("font-weight: 600;")
            detail = QLabel(item.detail)
            detail.setObjectName("Muted")
            dot = QLabel("●")
            dot.setStyleSheet(
                f"color: {theme.ampel_color(_STATUS_AMPEL.get(item.status, 'grey'), colors)};")
            line.addWidget(dot)
            line.addWidget(label)
            line.addStretch(1)
            line.addWidget(detail)
            due_box.addWidget(row)
        self._layout.addLayout(due_box)
        self._layout.addStretch(1)
