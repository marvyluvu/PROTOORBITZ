import logging
from typing import Any

from PIL import Image

from ..config import AppConfig


logger = logging.getLogger(__name__)


class ILI9341Display:
    def __init__(self, config: AppConfig):
        self.config = config
        self.device: Any | None = None

    def initialize(self) -> None:
        from luma.core.interface.serial import spi
        from luma.lcd.device import ili9341
        serial = spi(port=self.config.display_spi_port, device=self.config.display_spi_device, gpio_DC=self.config.display_dc_pin, gpio_RST=self.config.display_reset_pin, bus_speed_hz=self.config.display_spi_hz)
        self.device = ili9341(serial, width=self.config.display_width, height=self.config.display_height, rotate=self.config.display_rotation)

    def present(self, image: Image.Image) -> None:
        if self.device is None:
            raise RuntimeError("Display is not initialized")
        self.device.display(image.convert("RGB"))

    def close(self) -> None:
        if self.device is not None:
            try:
                self.device.cleanup()
            except AttributeError:
                pass
            self.device = None
