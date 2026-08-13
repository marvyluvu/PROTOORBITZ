from math import cos, pi, sin

from PIL import Image, ImageDraw, ImageFont

from ..models import AppView, Target


class RadarRenderer:
    def __init__(self, width: int = 240, height: int = 320):
        self.width = width
        self.height = height
        self.font = ImageFont.load_default()

    def frame(self, view: AppView) -> Image.Image:
        image = Image.new("RGB", (self.width, self.height), (0, 0, 0))
        draw = ImageDraw.Draw(image)
        self._header(draw, view)
        self._radar(draw, view.targets, view.selected_identifier)
        self._footer(draw, view)
        return image

    def diagnostic(self, title: str, detail: str) -> Image.Image:
        image = Image.new("RGB", (self.width, self.height), (0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, self.width - 1, self.height - 1), outline=(255, 255, 255))
        draw.rectangle((8, 32, 72, 96), fill=(255, 0, 0))
        draw.rectangle((88, 32, 152, 96), fill=(0, 255, 0))
        draw.rectangle((168, 32, 232, 96), fill=(0, 0, 255))
        draw.text((8, 120), title[:34], fill=(255, 255, 255), font=self.font)
        draw.multiline_text((8, 140), detail[:160], fill=(180, 220, 255), font=self.font, spacing=3)
        return image

    def _header(self, draw: ImageDraw.ImageDraw, view: AppView) -> None:
        draw.rectangle((0, 0, self.width, 24), fill=(8, 18, 30))
        aircraft = view.status.aircraft
        satellites = view.status.satellites
        source = aircraft.source if view.mode.value == "PLANES" else satellites.source
        gps = "GPS" if view.status.gps.valid else "FIX"
        draw.text((4, 7), f"{view.mode.value} {gps}", fill=(220, 240, 255), font=self.font)
        draw.text((150, 7), self._clip(source.upper(), 14), fill=(120, 210, 220), font=self.font)

    def _radar(self, draw: ImageDraw.ImageDraw, targets: tuple[Target, ...], selected: str | None) -> None:
        center_x, center_y, radius = 120, 135, 92
        for factor in (1.0, 0.66, 0.33):
            value = int(radius * factor)
            draw.ellipse((center_x - value, center_y - value, center_x + value, center_y + value), outline=(20, 78, 84))
        draw.line((center_x - radius, center_y, center_x + radius, center_y), fill=(20, 78, 84))
        draw.line((center_x, center_y - radius, center_x, center_y + radius), fill=(20, 78, 84))
        draw.text((center_x - 3, center_y - radius - 10), "N", fill=(100, 170, 180), font=self.font)
        for target in targets:
            if target.elevation_deg < 0.0:
                continue
            radial = radius * max(0.0, min(1.0, 1.0 - target.elevation_deg / 90.0))
            angle = radians(target.azimuth_deg - 90.0)
            x = center_x + cos(angle) * radial
            y = center_y + sin(angle) * radial
            color = (230, 230, 230) if target.kind == "plane" else (255, 180, 0) if target.kind == "iss" else (0, 230, 110) if target.optically_visible else (0, 180, 220)
            size = 4 if target.identifier == selected else 2
            draw.ellipse((x - size, y - size, x + size, y + size), fill=color)
            if target.identifier == selected:
                draw.rectangle((x - size - 2, y - size - 2, x + size + 2, y + size + 2), outline=(255, 255, 0))

    def _footer(self, draw: ImageDraw.ImageDraw, view: AppView) -> None:
        selected = next((target for target in view.targets if target.identifier == view.selected_identifier), None)
        draw.rectangle((0, 242, self.width, self.height), fill=(8, 18, 30))
        if selected is None:
            detail = "No targets"
        else:
            detail = f"{self._clip(selected.name, 25)} {selected.azimuth_deg:03.0f}/{selected.elevation_deg:+.0f} {selected.range_km:.0f}km"
        draw.text((4, 250), detail, fill=(240, 240, 240), font=self.font)
        snapshot = view.status.aircraft if view.mode.value == "PLANES" else view.status.satellites
        age = max(0, int(view.rendered_at - snapshot.timestamp)) if snapshot.timestamp else 0
        state = "STALE" if snapshot.stale else "LIVE"
        if snapshot.error:
            state = "ERROR"
        draw.text((4, 270), f"{state} {age}s {view.status.gps.source.upper()}", fill=(255, 160, 80) if state != "LIVE" else (130, 220, 160), font=self.font)
        if view.mode.value == "SATELLITES":
            rise = view.status.satellites.iss_next_rise
            message = "ISS no pass 24h" if rise is None else f"ISS {max(0, int((rise - view.rendered_at) / 60))} min"
            draw.text((4, 289), message, fill=(180, 220, 255), font=self.font)

    def _clip(self, value: str, length: int) -> str:
        return value if len(value) <= length else value[: max(1, length - 1)] + "…"


def radians(value: float) -> float:
    return value * pi / 180.0
