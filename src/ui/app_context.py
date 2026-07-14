"""Shared application context: services, current vehicle and a Qt signal bus.

A single ``AppContext`` is created at startup and passed to every view. It owns
the database, repositories and config, tracks the globally selected vehicle
(the toolbar switcher), exposes the current theme palette and provides the
signals views use to stay in sync:

    * ``data_changed`` — emitted after any data mutation; views refresh.
    * ``theme_changed`` — emitted when the user toggles light/dark.
    * ``vehicle_changed`` — emitted when the toolbar switcher selects another
      vehicle; every view re-renders for the new selection.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from modules import dates, fuel, interop
from modules.config import Config
from modules.db_handler.database import Database
from modules.db_handler.repositories import (
    AppointmentRepository,
    AttachmentRepository,
    CareRuleRepository,
    CatalogRepository,
    CostRepository,
    LogbookRepository,
    SettingsRepository,
    TankRepository,
    VehicleRepository,
)
from modules.logging_setup import get_logger
from modules.models import Vehicle


class AppContext(QObject):
    data_changed = pyqtSignal()
    theme_changed = pyqtSignal(str)
    vehicle_changed = pyqtSignal(object)   # Vehicle | None

    def __init__(self, db: Database, config: Config) -> None:
        super().__init__()
        self.db = db
        self.config = config
        self.log = get_logger("ui")

        self.vehicles = VehicleRepository(db)
        self.tank = TankRepository(db)
        self.costs = CostRepository(db)
        self.appointments = AppointmentRepository(db)
        self.rules = CareRuleRepository(db)
        self.logbook = LogbookRepository(db)
        self.attachments = AttachmentRepository(db)
        self.catalog = CatalogRepository(db)
        self.settings = SettingsRepository(db)

        # Sister-app discovery once per session (fail-silent by contract).
        self.sister = interop.discover_sister()

        self._current_vehicle: Vehicle | None = None
        self._restore_vehicle_selection()

    # -- vehicle selection ----------------------------------------------------
    def _restore_vehicle_selection(self) -> None:
        vehicles = self.vehicles.list()
        wanted = self.config.get("last_vehicle_id")
        chosen = next((v for v in vehicles if v.id == wanted), None)
        self._current_vehicle = chosen or (vehicles[0] if vehicles else None)

    @property
    def vehicle(self) -> Vehicle | None:
        """The globally selected vehicle (None only before the first one exists)."""
        return self._current_vehicle

    @property
    def vehicle_id(self) -> int | None:
        return self._current_vehicle.id if self._current_vehicle else None

    def set_vehicle(self, vehicle_id: int | None) -> None:
        vehicle = self.vehicles.get(vehicle_id) if vehicle_id is not None else None
        self._current_vehicle = vehicle
        self.config.set("last_vehicle_id", vehicle.id if vehicle else None)
        self.vehicle_changed.emit(vehicle)

    def reload_vehicle(self) -> None:
        """Refresh the cached vehicle after edits (or pick a fallback)."""
        if self._current_vehicle and self._current_vehicle.id is not None:
            fresh = self.vehicles.get(self._current_vehicle.id)
            if fresh is not None:
                self._current_vehicle = fresh
                return
        self._restore_vehicle_selection()

    # -- km history convenience ------------------------------------------------
    def km_history(self, vehicle: Vehicle | None = None) -> list[fuel.OdoReading]:
        vehicle = vehicle or self._current_vehicle
        if vehicle is None or vehicle.id is None:
            return []
        entries = self.tank.list_chronological(vehicle.id)
        # Logbook entries with a recorded odometer feed the history too (a
        # workshop visit is often the freshest reading available).
        extra = []
        for entry in self.logbook.list(vehicle.id):
            if entry.odo_km is None:
                continue
            d = dates.parse_date(entry.date)
            if d is not None:
                extra.append(fuel.OdoReading(d, entry.odo_km))
        return fuel.km_history(vehicle, entries, extra)

    def current_km(self, vehicle: Vehicle | None = None) -> int | None:
        return fuel.current_km(self.km_history(vehicle))

    # -- theme ---------------------------------------------------------------
    @property
    def theme_name(self) -> str:
        return self.config.theme

    @property
    def colors(self) -> dict:
        from ui import theme
        return theme.palette(self.config.theme)

    def set_theme(self, name: str) -> None:
        self.config.theme = name
        self.theme_changed.emit(name)

    # -- data events -----------------------------------------------------------
    def notify_changed(self) -> None:
        """Signal that data was mutated so open views can refresh."""
        self.reload_vehicle()
        self.data_changed.emit()
