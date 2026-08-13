import time
from typing import Protocol

from .config import AppConfig
from .models import AlertDecision, AppView, Mode


class AlertOutput(Protocol):
    def set_color(self, color: tuple[int, int, int]) -> None: ...
    def play(self, pattern: tuple[tuple[int, float], ...]) -> None: ...


class AlertController:
    def __init__(self, config: AppConfig, output: AlertOutput):
        self.config = config
        self.output = output
        self.boot_started = time.monotonic()
        self.alerted: set[str] = set()

    def decide(self, view: AppView) -> AlertDecision:
        if view.status.hardware_errors or view.status.aircraft.error or view.status.satellites.error:
            return AlertDecision((128, 0, 0))
        if time.monotonic() - self.boot_started < 1.5:
            return AlertDecision((0, 0, 32))
        selected = next((target for target in view.targets if target.identifier == view.selected_identifier), None)
        if selected is not None and selected.kind == "satellite" and selected.optically_visible:
            return AlertDecision((0, 96, 0))
        rise = view.status.satellites.iss_next_rise
        if rise is not None and 0.0 <= rise - view.rendered_at <= self.config.pass_alert_lead_seconds:
            key = f"iss:{int(rise)}"
            return AlertDecision((128, 64, 0), ((880, 0.08), (0, 0.05), (880, 0.08)), key)
        if view.mode == Mode.PLANES:
            return AlertDecision((0, 0, 64))
        return AlertDecision((0, 64, 64))

    def update(self, view: AppView) -> None:
        decision = self.decide(view)
        self.output.set_color(decision.color)
        if decision.key is not None and decision.key not in self.alerted:
            self.alerted.add(decision.key)
            self.output.play(decision.tone)
