import queue
from typing import Any

from ..config import AppConfig
from ..models import Command


class InputDriver:
    def __init__(self, config: AppConfig):
        self.config = config
        self.events: queue.SimpleQueue[Command] = queue.SimpleQueue()
        self.devices: list[Any] = []
        self.encoder_a: Any | None = None
        self.encoder_b: Any | None = None
        self.last_state = 0
        self.accumulator = 0

    def initialize(self) -> None:
        from gpiozero import Button
        settings: dict[str, object]
        if self.config.external_pull_up:
            settings = {"pull_up": None, "active_state": False}
        else:
            settings = {"pull_up": True}
        common = {**settings, "bounce_time": self.config.input_debounce_seconds}
        self.encoder_a = Button(self.config.encoder_a_pin, **common)
        self.encoder_b = Button(self.config.encoder_b_pin, **common)
        encoder_switch = Button(self.config.encoder_switch_pin, hold_time=self.config.diagnostics_hold_seconds, hold_repeat=False, **common)
        previous = Button(self.config.button_previous_pin, **common)
        following = Button(self.config.button_next_pin, **common)
        self.devices = [self.encoder_a, self.encoder_b, encoder_switch, previous, following]
        self.last_state = self._state()
        self.encoder_a.when_pressed = self._encoder_changed
        self.encoder_a.when_released = self._encoder_changed
        self.encoder_b.when_pressed = self._encoder_changed
        self.encoder_b.when_released = self._encoder_changed
        encoder_switch.when_pressed = lambda: self.events.put(Command.TOGGLE_MODE)
        if self.config.enable_diagnostics_hold:
            encoder_switch.when_held = lambda: self.events.put(Command.DIAGNOSTICS)
        previous.when_pressed = lambda: self.events.put(Command.PREVIOUS)
        following.when_pressed = lambda: self.events.put(Command.NEXT)

    def _state(self) -> int:
        return (int(bool(self.encoder_a and self.encoder_a.is_pressed)) << 1) | int(bool(self.encoder_b and self.encoder_b.is_pressed))

    def _encoder_changed(self) -> None:
        current = self._state()
        transition = (self.last_state << 2) | current
        direction = {1: 1, 7: 1, 14: 1, 8: 1, 2: -1, 11: -1, 13: -1, 4: -1}.get(transition, 0)
        self.last_state = current
        self.accumulator += direction
        if abs(self.accumulator) >= 4:
            clockwise = self.accumulator > 0
            self.accumulator = 0
            if self.config.encoder_inverted:
                clockwise = not clockwise
            self.events.put(Command.NEXT if clockwise else Command.PREVIOUS)

    def drain(self) -> tuple[Command, ...]:
        received: list[Command] = []
        while True:
            try:
                received.append(self.events.get_nowait())
            except queue.Empty:
                return tuple(received)

    def close(self) -> None:
        for device in self.devices:
            device.close()
        self.devices = []
