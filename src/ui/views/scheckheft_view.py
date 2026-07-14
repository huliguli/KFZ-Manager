"""Digitales Scheckheft: chronological history with attachments.

The timeline shows care completions, maintenance and manual entries in one
list. Attachments (photos/PDFs) can be added per entry: files are copied into
the hardened attachment store (see modules.attachments), image thumbnails are
rendered inline, PDFs open in the system viewer.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QFileDialog,
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
from modules import dates, platform_util
from modules.models import LOGBOOK_KIND_LABELS
from modules.money import format_eur
from ui.dialogs import LogbookDialog
from ui.views.base_view import BaseView
from ui.widgets.common import clear_layout, heading, muted, primary_button

_THUMB_SIZE = 68


class ScheckheftView(BaseView):
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
        vehicle = self.ctx.vehicle

        head = QHBoxLayout()
        head_box = QVBoxLayout()
        head_box.setSpacing(2)
        head_box.addWidget(heading("Digitales Scheckheft"))
        head_box.addWidget(muted(
            f"Fahrzeug: {vehicle.display_name}" if vehicle else "Kein Fahrzeug gewählt."))
        head.addLayout(head_box)
        head.addStretch(1)
        add_btn = primary_button("+ Eintrag", self.ctx.colors)
        add_btn.clicked.connect(self.create_new)
        add_btn.setEnabled(vehicle is not None)
        head.addWidget(add_btn)
        self._layout.addLayout(head)

        if vehicle is None or vehicle.id is None:
            self._layout.addStretch(1)
            return

        entries = self.ctx.logbook.list(vehicle.id)
        if not entries:
            empty = QLabel(
                "Noch keine Einträge. Erledigte Pflege-Regeln und Termine "
                "erscheinen hier automatisch; Werkstattbesuche kannst du "
                "manuell mit Fotos/Rechnungen (PDF) festhalten.")
            empty.setObjectName("Muted")
            empty.setWordWrap(True)
            self._layout.addWidget(empty)

        for entry in entries:
            self._layout.addWidget(self._entry_card(entry))
        self._layout.addStretch(1)

    def _entry_card(self, entry) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        box = QVBoxLayout(card)
        box.setContentsMargins(20, 14, 20, 14)
        box.setSpacing(6)

        top = QHBoxLayout()
        title = QLabel(entry.titel)
        title.setObjectName("H2")
        meta_bits = [dates.format_date(entry.date),
                     LOGBOOK_KIND_LABELS.get(entry.art, entry.art)]
        if entry.odo_km is not None:
            meta_bits.append(f"{entry.odo_km:,} km".replace(",", "."))
        if entry.kosten_cent:
            meta_bits.append(format_eur(entry.kosten_cent))
        meta = QLabel(" · ".join(meta_bits))
        meta.setObjectName("Faint")
        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        title_box.addWidget(title)
        title_box.addWidget(meta)
        top.addLayout(title_box)
        top.addStretch(1)

        attach_btn = QPushButton("+ Anhang")
        attach_btn.setObjectName("Ghost")
        attach_btn.clicked.connect(lambda _c, e=entry: self._add_attachment(e))
        edit_btn = QPushButton("Bearbeiten")
        edit_btn.setObjectName("Ghost")
        edit_btn.clicked.connect(lambda _c, e=entry: self._edit(e))
        del_btn = QPushButton("Löschen")
        del_btn.setObjectName("Danger")
        del_btn.clicked.connect(lambda _c, e=entry: self._delete(e))
        top.addWidget(attach_btn)
        top.addWidget(edit_btn)
        top.addWidget(del_btn)
        box.addLayout(top)

        if entry.beschreibung:
            desc = QLabel(entry.beschreibung)
            desc.setWordWrap(True)
            box.addWidget(desc)

        attachments = self.ctx.attachments.list_for_entry("logbook", entry.id)
        if attachments:
            att_row = QHBoxLayout()
            att_row.setSpacing(8)
            for att in attachments:
                att_row.addWidget(self._attachment_widget(att))
            att_row.addStretch(1)
            box.addLayout(att_row)
        return card

    def _attachment_widget(self, att) -> QWidget:
        """Thumbnail (images) or a filename chip (PDF/HEIC); click to open."""
        wrap = QWidget()
        box = QVBoxLayout(wrap)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)

        path = attach_mod.resolve_path(att.rel_path)
        ext = Path(att.original_name).suffix.lstrip(".").lower()
        open_btn = QPushButton()
        open_btn.setObjectName("Ghost")
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if path and ext in attach_mod.IMAGE_EXTENSIONS:
            pm = QPixmap(str(path))
            if not pm.isNull():
                open_btn.setIconSize(pm.scaled(
                    _THUMB_SIZE, _THUMB_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation).size())
                from PyQt6.QtGui import QIcon
                open_btn.setIcon(QIcon(pm))
            else:
                open_btn.setText(att.original_name)
        else:
            open_btn.setText(att.original_name)
        open_btn.setToolTip(f"{att.original_name} öffnen")
        open_btn.clicked.connect(lambda _c, p=path: platform_util.open_path(p) if p else None)
        box.addWidget(open_btn)

        remove = QPushButton("Entfernen")
        remove.setObjectName("Link")
        remove.clicked.connect(lambda _c, a=att: self._remove_attachment(a))
        box.addWidget(remove)
        return wrap

    # -- actions -----------------------------------------------------------------
    def create_new(self) -> bool:
        vehicle = self.ctx.vehicle
        if vehicle is None:
            return False
        dlg = LogbookDialog(vehicle, parent=self)
        if dlg.exec():
            self.ctx.logbook.add(dlg.result_model)
            self.ctx.notify_changed()
        return True

    def _edit(self, entry) -> None:
        vehicle = self.ctx.vehicle
        if vehicle is None:
            return
        dlg = LogbookDialog(vehicle, item=entry, parent=self)
        if dlg.exec():
            self.ctx.logbook.update(dlg.result_model)
            self.ctx.notify_changed()

    def _delete(self, entry) -> None:
        if entry.id is None:
            return
        if QMessageBox.question(
                self, "Eintrag löschen",
                f"„{entry.titel}“ inklusive Anhängen löschen?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        attach_mod.delete_for_entry(self.ctx.attachments, "logbook", entry.id)
        self.ctx.logbook.delete(entry.id)
        self.ctx.notify_changed()

    def _add_attachment(self, entry) -> None:
        vehicle = self.ctx.vehicle
        if vehicle is None or vehicle.id is None or entry.id is None:
            return
        path, _f = QFileDialog.getOpenFileName(
            self, "Anhang wählen", "", attach_mod.FILE_FILTER)
        if not path:
            return
        try:
            model = attach_mod.store_file(path, vehicle.id, "logbook", entry.id)
        except attach_mod.AttachmentError as exc:
            QMessageBox.warning(self, "Anhang abgelehnt", str(exc))
            return
        self.ctx.attachments.add(model)
        self.ctx.notify_changed()

    def _remove_attachment(self, att) -> None:
        if QMessageBox.question(
                self, "Anhang entfernen",
                f"Anhang „{att.original_name}“ löschen?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        attach_mod.delete_file(att.rel_path)
        if att.id is not None:
            self.ctx.attachments.delete(att.id)
        self.ctx.notify_changed()
