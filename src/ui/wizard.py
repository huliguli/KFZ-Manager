"""First-run wizard: create one or more vehicles before the app opens.

Collects vehicles in memory via the standard VehicleDialog and commits them
only when the user finishes — the same collect-then-commit pattern as the
sister app's quick setup. Re-openable any time (more vehicles can also be
added later via the toolbar or the Fahrzeuge view).
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from modules.models import KRAFTSTOFF_LABELS, label_for
from ui.dialogs import VehicleDialog


class _VehiclePage(QWizardPage):
    """Collects a list of vehicles via the add dialog."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("Fahrzeug anlegen")
        self.setSubTitle("Lege ein Fahrzeug oder mehrere an — weitere sind "
                         "später jederzeit möglich.")
        self.items: list = []

        layout = QVBoxLayout(self)
        self.list = QListWidget()
        layout.addWidget(self.list, 1)

        buttons = QHBoxLayout()
        add = QPushButton("+ Fahrzeug hinzufügen")
        add.setObjectName("Primary")
        add.clicked.connect(self._add)
        remove = QPushButton("Entfernen")
        remove.setObjectName("Ghost")
        remove.clicked.connect(self._remove)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def isComplete(self) -> bool:  # noqa: N802 - Qt naming
        # At least one vehicle before the wizard can finish.
        return len(self.items) > 0

    def _add(self) -> None:
        dlg = VehicleDialog(parent=self)
        if dlg.exec():
            self.items.append(dlg.result_model)
            self._refresh()

    def _remove(self) -> None:
        row = self.list.currentRow()
        if 0 <= row < len(self.items):
            del self.items[row]
            self._refresh()

    def _refresh(self) -> None:
        self.list.clear()
        for item in self.items:
            fuel_label = label_for(item.kraftstoff, KRAFTSTOFF_LABELS, "")
            text = item.display_name + (f" · {fuel_label}" if fuel_label else "")
            self.list.addItem(text)
        self.completeChanged.emit()


class FirstRunWizard(QWizard):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Willkommen")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setMinimumSize(600, 500)
        self.setButtonText(QWizard.WizardButton.NextButton, "Weiter")
        self.setButtonText(QWizard.WizardButton.BackButton, "Zurück")
        self.setButtonText(QWizard.WizardButton.FinishButton, "Fertig")
        self.setButtonText(QWizard.WizardButton.CancelButton, "Abbrechen")

        self.addPage(self._intro())
        self.vehicle_page = _VehiclePage()
        self.addPage(self.vehicle_page)

    def _intro(self) -> QWizardPage:
        page = QWizardPage()
        page.setTitle("Willkommen beim KFZ-Manager")
        page.setSubTitle("Dein Hub für alles rund ums Auto.")
        layout = QVBoxLayout(page)
        text = QLabel(
            "Der KFZ-Manager begleitet deine Fahrzeuge:\n\n"
            "  •  Tank- & Ladebuch mit Verbrauch und Kosten/km\n"
            "  •  Kostenübersicht je Fahrzeug\n"
            "  •  Termine (TÜV/HU, Inspektion …) mit Erinnerung\n"
            "  •  Pflegeplaner mit km/Zeit-Intervallen und Datums-Prognose\n"
            "  •  Empfehlungen passend zum Fahrzeugprofil\n"
            "  •  Digitales Scheckheft mit Fotos und Rechnungen\n\n"
            "Im nächsten Schritt legst du dein erstes Fahrzeug an. Je mehr "
            "Profilfelder du füllst, desto passgenauer werden die Empfehlungen — "
            "alles außer dem Namen ist optional.")
        text.setWordWrap(True)
        layout.addWidget(text)
        layout.addStretch(1)
        return page

    def commit(self, ctx) -> int:
        """Persist all collected vehicles; returns the count."""
        first_id = None
        for item in self.vehicle_page.items:
            new_id = ctx.vehicles.add(item)
            if first_id is None:
                first_id = new_id
        if first_id is not None:
            ctx.set_vehicle(first_id)
        ctx.config.set("wizard_completed", True)
        ctx.notify_changed()
        return len(self.vehicle_page.items)


def run_wizard(ctx, parent=None) -> bool:
    """Show the wizard and commit on finish. Returns True if completed."""
    wizard = FirstRunWizard(parent)
    if wizard.exec():
        wizard.commit(ctx)
        return True
    return False
