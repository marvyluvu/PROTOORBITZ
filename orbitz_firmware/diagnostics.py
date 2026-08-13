import logging
import time
from dataclasses import dataclass

from .config import AppConfig
from .drivers.alerts import LedStrip, PassiveBuzzer
from .drivers.display import ILI9341Display
from .drivers.inputs import InputDriver
from .services.adsb import AdsbService
from .services.gps import GpsService
from .storage import AtomicCache
from .ui.render import RadarRenderer


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiagnosticResult:
    name: str
    success: bool
    detail: str


class DiagnosticRunner:
    def __init__(self, config: AppConfig):
        self.config = config
        self.cache = AtomicCache(config.state_dir)

    def run(self, selected: tuple[str, ...]) -> tuple[DiagnosticResult, ...]:
        names = ("display", "input", "led", "buzzer", "gps", "adsb", "orbit-cache") if not selected or "all" in selected else selected
        methods = {"display": self.display, "input": self.input, "led": self.led, "buzzer": self.buzzer, "gps": self.gps, "adsb": self.adsb, "orbit-cache": self.orbit_cache}
        return tuple(methods[name]() if name in methods else DiagnosticResult(name, False, "Unknown diagnostic") for name in names)

    def display(self) -> DiagnosticResult:
        device = ILI9341Display(self.config)
        try:
            device.initialize()
            device.present(RadarRenderer().diagnostic("ORBITZ DISPLAY", "Color and text check"))
            return DiagnosticResult("display", True, "Rendered color-and-text test screen")
        except Exception as error:
            return DiagnosticResult("display", False, str(error))
        finally:
            device.close()

    def input(self) -> DiagnosticResult:
        inputs = InputDriver(self.config)
        display = ILI9341Display(self.config)
        display_ready = False
        try:
            inputs.initialize()
            try:
                display.initialize()
                display_ready = True
            except Exception as error:
                logger.warning("Input diagnostic display unavailable: %s", error)
            deadline = time.monotonic() + 10.0
            events = []
            while time.monotonic() < deadline:
                events.extend(command.value for command in inputs.drain())
                if display_ready:
                    detail = ", ".join(events[-5:]) if events else "Rotate or press a control"
                    display.present(RadarRenderer().diagnostic("ORBITZ INPUT", detail))
                time.sleep(0.05)
            suffix = ", display unavailable" if not display_ready else ""
            return DiagnosticResult("input", True, "Events: " + (", ".join(events) if events else "none within 10 seconds") + suffix)
        except Exception as error:
            return DiagnosticResult("input", False, str(error))
        finally:
            inputs.close()
            display.close()

    def led(self) -> DiagnosticResult:
        device = LedStrip(self.config)
        try:
            device.initialize()
            device.set_color((32, 32, 32))
            time.sleep(0.5)
            return DiagnosticResult("led", True, "Conservative white LED test completed")
        except Exception as error:
            return DiagnosticResult("led", False, str(error))
        finally:
            device.close()

    def buzzer(self) -> DiagnosticResult:
        device = PassiveBuzzer(self.config)
        try:
            device.initialize()
            device.play(((660, 0.08), (0, 0.04), (880, 0.08)))
            time.sleep(0.35)
            return DiagnosticResult("buzzer", True, "Short tone sequence completed")
        except Exception as error:
            return DiagnosticResult("buzzer", False, str(error))
        finally:
            device.close()

    def gps(self) -> DiagnosticResult:
        service = GpsService(self.config, self.cache)
        fix = service.observer()
        return DiagnosticResult("gps", fix.valid, f"{fix.source}: {fix.latitude:.5f}, {fix.longitude:.5f}")

    def adsb(self) -> DiagnosticResult:
        service = AdsbService(self.config, self.cache)
        snapshot = service.refresh(GpsService(self.config, self.cache).observer())
        return DiagnosticResult("adsb", snapshot.error is None, f"{snapshot.source}: {len(snapshot.targets)} targets" if snapshot.error is None else snapshot.error)

    def orbit_cache(self) -> DiagnosticResult:
        available = []
        for group in self.config.orbit_groups:
            record = self.cache.read(f"omm_{group}")
            if record is not None:
                available.append(f"{group}:{int(time.time() - record.timestamp)}s")
        if not available:
            return DiagnosticResult("orbit-cache", False, "No validated orbital cache is available")
        return DiagnosticResult("orbit-cache", True, ", ".join(available))
