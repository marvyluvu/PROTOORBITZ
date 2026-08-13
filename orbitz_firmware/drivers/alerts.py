import queue
import threading
import time
from typing import Any

from ..config import AppConfig


class LedStrip:
    def __init__(self, config: AppConfig):
        self.config = config
        self.strip: Any | None = None
        self.color: tuple[int, int, int] | None = None

    def initialize(self) -> None:
        import rpi_ws281x as ws
        ordering = getattr(ws, f"WS2811_STRIP_{self.config.led_color_order}")
        self.ws = ws
        self.strip = ws.PixelStrip(self.config.led_count, self.config.led_pin, 800000, False, int(self.config.led_brightness_cap * 255), self.config.led_dma_channel, 0, ordering)
        self.strip.begin()
        self.set_color((0, 0, 0))

    def set_color(self, color: tuple[int, int, int]) -> None:
        if self.strip is None or color == self.color:
            return
        encoded = self.ws.Color(*color)
        for index in range(self.config.led_count):
            self.strip.setPixelColor(index, encoded)
        self.strip.show()
        self.color = color

    def close(self) -> None:
        if self.strip is not None:
            self.color = None
            self.set_color((0, 0, 0))
            self.strip = None


class PassiveBuzzer:
    def __init__(self, config: AppConfig):
        self.config = config
        self.device: Any | None = None
        self.patterns: queue.SimpleQueue[tuple[tuple[int, float], ...]] = queue.SimpleQueue()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def initialize(self) -> None:
        from gpiozero import OutputDevice
        self.device = OutputDevice(self.config.buzzer_pin, active_high=True, initial_value=False)
        self.thread = threading.Thread(target=self._run, name="orbitz-buzzer", daemon=True)
        self.thread.start()

    def play(self, pattern: tuple[tuple[int, float], ...]) -> None:
        if not self.config.alert_muted and self.device is not None:
            self.patterns.put(pattern)

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                pattern = self.patterns.get(timeout=0.2)
            except queue.Empty:
                continue
            for frequency, duration in pattern:
                if self.stop_event.is_set():
                    break
                deadline = time.monotonic() + min(max(duration, 0.0), 1.0)
                if frequency <= 0:
                    self.device.off()
                    self.stop_event.wait(max(0.0, deadline - time.monotonic()))
                    continue
                half_period = max(0.001, min(0.02, 0.5 / frequency))
                while time.monotonic() < deadline and not self.stop_event.is_set():
                    self.device.on()
                    self.stop_event.wait(half_period)
                    self.device.off()
                    self.stop_event.wait(half_period)
            self.device.off()

    def close(self) -> None:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=1.0)
        if self.device is not None:
            self.device.off()
            self.device.close()
            self.device = None
