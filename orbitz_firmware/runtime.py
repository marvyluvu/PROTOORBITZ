import logging
import signal
import threading
import time
from dataclasses import replace

from .alerts import AlertController
from .config import AppConfig
from .drivers.alerts import LedStrip, PassiveBuzzer
from .drivers.display import ILI9341Display
from .drivers.inputs import InputDriver
from .models import AircraftSnapshot, AppView, Command, Mode, SatelliteSnapshot, StatusSnapshot, Target
from .services.adsb import AdsbService
from .services.gps import GpsService
from .services.orbits import OrbitService
from .storage import AtomicCache
from .ui.render import RadarRenderer


logger = logging.getLogger(__name__)


def route_command(mode: Mode, selected_identifier: str | None, targets: tuple[Target, ...], command: Command) -> tuple[Mode, str | None]:
    if command == Command.TOGGLE_MODE:
        return (Mode.SATELLITES if mode == Mode.PLANES else Mode.PLANES), None
    if not targets:
        return mode, None
    current = next((index for index, target in enumerate(targets) if target.identifier == selected_identifier), 0)
    if command == Command.NEXT:
        return mode, targets[(current + 1) % len(targets)].identifier
    if command == Command.PREVIOUS:
        return mode, targets[(current - 1) % len(targets)].identifier
    return mode, selected_identifier


class OrbitzRuntime:
    def __init__(self, config: AppConfig):
        self.config = config
        self.cache = AtomicCache(config.state_dir)
        self.gps = GpsService(config, self.cache)
        self.adsb = AdsbService(config, self.cache)
        self.orbits = OrbitService(config, self.cache, __import__("pathlib").Path(__file__).resolve().parent)
        self.display = ILI9341Display(config)
        self.inputs = InputDriver(config)
        self.leds = LedStrip(config)
        self.buzzer = PassiveBuzzer(config)
        self.renderer = RadarRenderer(config.display_width, config.display_height)
        self.alerts = AlertController(config, self)
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.aircraft = AircraftSnapshot()
        self.satellites = SatelliteSnapshot()
        self.hardware_errors: list[str] = []
        self.threads: list[threading.Thread] = []

    def set_color(self, color: tuple[int, int, int]) -> None:
        self.leds.set_color(color)

    def play(self, pattern: tuple[tuple[int, float], ...]) -> None:
        self.buzzer.play(pattern)

    def _start_component(self, name: str, initializer: object) -> None:
        try:
            initializer.initialize()
        except Exception as error:
            logger.exception("%s initialization failed", name)
            self.hardware_errors.append(f"{name}: {error}")

    def initialize(self) -> None:
        self.cache.initialize()
        self._start_component("display", self.display)
        self._start_component("inputs", self.inputs)
        self._start_component("leds", self.leds)
        self._start_component("buzzer", self.buzzer)
        self.threads = [
            threading.Thread(target=self.gps.run, args=(self.stop_event,), name="orbitz-gps", daemon=True),
            threading.Thread(target=self._aircraft_worker, name="orbitz-adsb", daemon=True),
            threading.Thread(target=self._orbit_worker, name="orbitz-orbits", daemon=True),
        ]
        for thread in self.threads:
            thread.start()

    def _aircraft_worker(self) -> None:
        while not self.stop_event.is_set():
            snapshot = self.adsb.refresh(self.gps.observer())
            with self.lock:
                self.aircraft = snapshot
            self.stop_event.wait(3.0)

    def _orbit_worker(self) -> None:
        while not self.stop_event.is_set():
            snapshot = self.orbits.snapshot(self.gps.observer())
            with self.lock:
                self.satellites = snapshot
            self.stop_event.wait(self.config.geometry_refresh_seconds)

    def _status(self) -> StatusSnapshot:
        with self.lock:
            return StatusSnapshot(self.gps.observer(), self.aircraft, self.satellites, tuple(self.hardware_errors))

    def run(self) -> int:
        mode = Mode.PLANES
        selected_identifier: str | None = None
        interval = 1.0 / self.config.display_frame_rate
        while not self.stop_event.is_set():
            started = time.monotonic()
            status = self._status()
            targets = status.aircraft.targets if mode == Mode.PLANES else status.satellites.targets
            if selected_identifier not in {target.identifier for target in targets}:
                selected_identifier = targets[0].identifier if targets else None
            for command in self.inputs.drain():
                if command == Command.DIAGNOSTICS:
                    logger.info("Diagnostics request received")
                    continue
                mode, selected_identifier = route_command(mode, selected_identifier, targets, command)
                targets = status.aircraft.targets if mode == Mode.PLANES else status.satellites.targets
            view = AppView(mode, selected_identifier, targets, status, time.time())
            self.alerts.update(view)
            try:
                self.display.present(self.renderer.frame(view))
            except Exception as error:
                message = f"display: {error}"
                if message not in self.hardware_errors:
                    logger.exception("Display rendering failed")
                    self.hardware_errors.append(message)
            self.stop_event.wait(max(0.0, interval - (time.monotonic() - started)))
        return 0

    def request_stop(self, signum: int | None = None, frame: object | None = None) -> None:
        if signum is not None:
            logger.info("Received signal %s", signum)
        self.stop_event.set()

    def shutdown(self) -> None:
        self.stop_event.set()
        for thread in self.threads:
            thread.join(timeout=3.0)
        for component in (self.inputs, self.buzzer, self.leds, self.display):
            try:
                component.close()
            except Exception:
                logger.exception("Shutdown failure")

    def install_signal_handlers(self) -> None:
        signal.signal(signal.SIGINT, self.request_stop)
        signal.signal(signal.SIGTERM, self.request_stop)
