"""Main application window: sidebar navigation, vehicle switcher, view stack.

Follows the sister app's layout: fixed sidebar with tinted vector icons and a
QStackedWidget of views. New here is the top bar with the GLOBAL vehicle
switcher — every view renders for the vehicle selected there. The window
remembers its size/position between runs and exposes a light/dark toggle.
"""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QCloseEvent, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app_meta import APP_DISPLAY_NAME, APP_VERSION, GITHUB_REPO, app_icon_path
from modules.updater import updater
from ui import icons, theme
from ui.app_context import AppContext
from ui.views.base_view import BaseView
from ui.views.dashboard_view import DashboardView
from ui.views.einstellungen_view import EinstellungenView
from ui.views.empfehlungen_view import EmpfehlungenView
from ui.views.fahrzeuge_view import FahrzeugeView
from ui.views.kosten_view import KostenView
from ui.views.pflegeplan_view import PflegeplanView
from ui.views.scheckheft_view import ScheckheftView
from ui.views.tankbuch_view import TankbuchView
from ui.views.termine_view import TermineView

# (label, icon name, view class). Einstellungen must stay last — the update flow
# and thread cleanup reference it as self._views[-1].
_NAV = [
    ("Dashboard", "dashboard", DashboardView),
    ("Tankbuch", "fuel", TankbuchView),
    ("Kosten", "wallet", KostenView),
    ("Termine", "bell", TermineView),
    ("Pflegeplan", "wrench", PflegeplanView),
    ("Empfehlungen", "sparkle", EmpfehlungenView),
    ("Scheckheft", "clipboard", ScheckheftView),
    ("Fahrzeuge", "car", FahrzeugeView),
    ("Einstellungen", "settings", EinstellungenView),
]


class MainWindow(QWidget):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.setObjectName("Root")
        self.setWindowTitle(APP_DISPLAY_NAME)
        self.setMinimumSize(1060, 680)
        _icon = app_icon_path()
        if _icon.exists():
            self.setWindowIcon(QIcon(str(_icon)))

        self._views: list[BaseView] = []
        self._nav_buttons: list[QPushButton] = []
        self._update_checker = None
        self._switcher_updating = False

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_sidebar())

        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)
        content.addWidget(self._build_topbar())

        self._stack = QStackedWidget()
        for _label, _icon, view_cls in _NAV:
            view = view_cls(ctx)
            self._views.append(view)
            self._stack.addWidget(view)
        content.addWidget(self._stack, 1)
        root.addLayout(content, 1)

        self.ctx.data_changed.connect(self._on_data_changed)
        self.ctx.theme_changed.connect(self._on_theme_changed)
        self.ctx.vehicle_changed.connect(self._on_vehicle_changed)

        self._init_shortcuts()
        self._restore_geometry()
        self._reload_switcher()
        self._select(0)

    # -- keyboard layer -----------------------------------------------------------
    def _init_shortcuts(self) -> None:
        """App-wide shortcuts (Qt maps Ctrl to Cmd on macOS automatically).

        Strg+1..9 switch views, Strg+N opens the active view's "new entry"
        dialog, Strg+Tab cycles through the vehicles.
        """
        for i in range(len(_NAV)):
            sc = QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self)
            sc.activated.connect(lambda i=i: self._select(i))
        QShortcut(QKeySequence("Ctrl+N"), self).activated.connect(self._shortcut_new)
        QShortcut(QKeySequence("Ctrl+Tab"), self).activated.connect(self._next_vehicle)

    def _current_view(self) -> BaseView:
        return self._views[self._stack.currentIndex()]

    def _shortcut_new(self) -> None:
        self._current_view().create_new()

    def _next_vehicle(self) -> None:
        count = self._switcher.count()
        if count > 1:
            self._switcher.setCurrentIndex((self._switcher.currentIndex() + 1) % count)

    # -- sidebar ---------------------------------------------------------------
    def _build_sidebar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("Sidebar")
        bar.setFixedWidth(232)
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(16, 22, 16, 18)
        layout.setSpacing(6)

        brand = QLabel(APP_DISPLAY_NAME)
        brand.setObjectName("Brand")
        sub = QLabel("AUTOLIEBHABER-HUB")
        sub.setObjectName("BrandSub")
        layout.addWidget(brand)
        layout.addWidget(sub)
        layout.addSpacing(18)

        group = QButtonGroup(self)
        group.setExclusive(True)
        icon_color = theme.palette(self.ctx.theme_name)["sidebar_text"]
        for index, (label, icon_name, _cls) in enumerate(_NAV):
            btn = QPushButton(f"  {label}")
            btn.setObjectName("NavButton")
            btn.setCheckable(True)
            btn.setToolTip(f"{label} (Strg+{index + 1})")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setIcon(icons.icon(icon_name, icon_color, 20))
            btn.setIconSize(QSize(20, 20))
            btn.clicked.connect(lambda _checked, i=index: self._select(i))
            group.addButton(btn, index)
            self._nav_buttons.append(btn)
            layout.addWidget(btn)

        layout.addStretch(1)

        self._theme_btn = QPushButton("  Dunkles Design")
        self._theme_btn.setObjectName("NavButton")
        self._theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._theme_btn.clicked.connect(self._toggle_theme)
        layout.addWidget(self._theme_btn)

        version = QLabel(f"v{APP_VERSION}")
        version.setObjectName("BrandSub")
        version.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(version)

        self._update_theme_button()
        return bar

    # -- top bar (vehicle switcher) -----------------------------------------------
    def _build_topbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("TopBar")
        bar.setStyleSheet("QWidget#TopBar { background: transparent; }")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(30, 14, 30, 0)
        layout.setSpacing(10)
        layout.addStretch(1)

        label = QLabel("Fahrzeug:")
        label.setObjectName("Muted")
        layout.addWidget(label)

        self._switcher = QComboBox()
        self._switcher.setMinimumWidth(240)
        self._switcher.setToolTip("Globaler Fahrzeug-Umschalter (Strg+Tab)")
        self._switcher.currentIndexChanged.connect(self._on_switcher_changed)
        layout.addWidget(self._switcher)

        add_btn = QPushButton("+")
        add_btn.setObjectName("Ghost")
        add_btn.setFixedWidth(36)
        add_btn.setToolTip("Neues Fahrzeug anlegen")
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.clicked.connect(self._add_vehicle)
        layout.addWidget(add_btn)
        return bar

    def _reload_switcher(self) -> None:
        """Refill the vehicle combo without firing selection events."""
        self._switcher_updating = True
        try:
            self._switcher.clear()
            for vehicle in self.ctx.vehicles.list():
                self._switcher.addItem(vehicle.display_name, vehicle.id)
            current = self.ctx.vehicle_id
            if current is not None:
                idx = self._switcher.findData(current)
                if idx >= 0:
                    self._switcher.setCurrentIndex(idx)
        finally:
            self._switcher_updating = False

    def _on_switcher_changed(self, index: int) -> None:
        if self._switcher_updating or index < 0:
            return
        vehicle_id = self._switcher.itemData(index)
        if vehicle_id is not None and vehicle_id != self.ctx.vehicle_id:
            self.ctx.set_vehicle(vehicle_id)

    def _add_vehicle(self) -> None:
        from ui.dialogs import VehicleDialog
        dlg = VehicleDialog(parent=self)
        if dlg.exec():
            new_id = self.ctx.vehicles.add(dlg.result_model)
            self.ctx.set_vehicle(new_id)
            self.ctx.notify_changed()

    def _on_vehicle_changed(self, _vehicle) -> None:
        self._reload_switcher()
        self._refresh_current()

    # -- navigation --------------------------------------------------------------
    def _select(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        if 0 <= index < len(self._nav_buttons):
            self._nav_buttons[index].setChecked(True)
        self._views[index].refresh()

    def _refresh_current(self) -> None:
        self._views[self._stack.currentIndex()].refresh()

    def _on_data_changed(self) -> None:
        self._reload_switcher()
        self._refresh_current()

    # -- theme -------------------------------------------------------------------
    def _toggle_theme(self) -> None:
        new = "light" if self.ctx.theme_name == "dark" else "dark"
        self.ctx.set_theme(new)

    def _update_theme_button(self) -> None:
        is_dark = self.ctx.theme_name == "dark"
        color = theme.palette(self.ctx.theme_name)["sidebar_text"]
        self._theme_btn.setText("  Helles Design" if is_dark else "  Dunkles Design")
        self._theme_btn.setIcon(icons.icon("sun" if is_dark else "moon", color, 20))
        self._theme_btn.setIconSize(QSize(20, 20))

    def _on_theme_changed(self, _name: str) -> None:
        from PyQt6.QtWidgets import QApplication
        QApplication.instance().setStyleSheet(theme.build_qss(self.ctx.colors))
        color = self.ctx.colors["sidebar_text"]
        for (_label, icon_name, _cls), btn in zip(_NAV, self._nav_buttons):
            btn.setIcon(icons.icon(icon_name, color, 20))
        self._update_theme_button()
        for view in self._views:
            view.on_theme_changed()

    # -- startup update check ---------------------------------------------------------
    def maybe_check_updates(self) -> None:
        """Start a non-blocking update check if the user enabled it."""
        updater.cleanup_temp_downloads()
        if not self.ctx.config.get("update_check_enabled", True):
            return
        # Parent the thread to the window so its C++ lifetime is tied to ours;
        # closeEvent additionally waits for it.
        self._update_checker = updater.UpdateChecker(GITHUB_REPO, APP_VERSION, parent=self)
        self._update_checker.result.connect(self._on_startup_update)
        self._update_checker.start()

    def _on_startup_update(self, info) -> None:
        if info is None or info.tag == self.ctx.config.get("skipped_version"):
            return
        # The Settings view owns the update dialog/installer flow.
        settings_view = self._views[-1]
        if self.ctx.config.get("update_auto_install", False) and info.asset_url \
                and hasattr(settings_view, "auto_install"):
            settings_view.auto_install(info)
            return
        if hasattr(settings_view, "show_update_dialog"):
            settings_view.show_update_dialog(info)

    # -- startup reminders -----------------------------------------------------------
    def show_startup_reminders(self) -> None:
        """One dialog listing everything due/soon across all vehicles."""
        from modules import reminders as reminders_mod
        vehicles = self.ctx.vehicles.list()
        if not vehicles:
            return
        items = reminders_mod.collect(
            vehicles,
            {v.id: self.ctx.appointments.list(v.id) for v in vehicles},
            {v.id: self.ctx.rules.list(v.id) for v in vehicles},
            {v.id: self.ctx.km_history(v) for v in vehicles},
            lead_days=int(self.ctx.config.get("reminder_lead_days", 30)),
            lead_km=int(self.ctx.config.get("reminder_lead_km", 1000)),
        )
        if not items:
            return
        from PyQt6.QtWidgets import QMessageBox
        lines = []
        for item in items[:12]:
            prefix = "‼" if item.status == reminders_mod.STATUS_OVERDUE else "•"
            lines.append(f"{prefix} {item.vehicle.name} — {item.title}: {item.detail}")
        if len(items) > 12:
            lines.append(f"… und {len(items) - 12} weitere.")
        QMessageBox.information(
            self, "Fällige Termine & Pflege",
            "Folgende Punkte sind fällig oder bald fällig:\n\n" + "\n".join(lines))

    # -- geometry persistence --------------------------------------------------------
    def _restore_geometry(self) -> None:
        win = self.ctx.config.window
        self.resize(int(win.get("w", 1240)), int(win.get("h", 820)))
        if win.get("x") is not None and win.get("y") is not None:
            self.move(int(win["x"]), int(win["y"]))
        if win.get("maximized"):
            self.showMaximized()

    def _stop_background_threads(self) -> None:
        """Stop any running update threads so none is destroyed while running."""
        threads = [self._update_checker]
        settings = self._views[-1] if self._views else None
        if settings is not None and hasattr(settings, "background_threads"):
            threads += settings.background_threads()
        for thread in threads:
            if thread is not None and thread.isRunning():
                thread.requestInterruption()
                thread.wait(4000)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._stop_background_threads()
        maximized = self.isMaximized()
        geo = self.normalGeometry()
        self.ctx.config.window = {
            "w": geo.width(), "h": geo.height(),
            "x": geo.x(), "y": geo.y(), "maximized": maximized,
        }
        self.ctx.db.close()
        super().closeEvent(event)
