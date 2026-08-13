import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    pass


DEFAULTS: dict[str, Any] = {
    "runtime": {
        "state_dir": "/var/lib/orbitz",
        "log_level": "INFO",
        "display_frame_rate": 12.0,
        "input_debounce_seconds": 0.03,
        "enable_diagnostics_hold": False,
        "diagnostics_hold_seconds": 2.0,
    },
    "display": {
        "width": 240,
        "height": 320,
        "rotation": 0,
        "spi_port": 0,
        "spi_device": 0,
        "spi_hz": 32000000,
        "mosi_pin": 10,
        "sclk_pin": 11,
        "cs_pin": 8,
        "dc_pin": 24,
        "reset_pin": 25,
    },
    "inputs": {
        "encoder_a_pin": 17,
        "encoder_b_pin": 27,
        "encoder_switch_pin": 22,
        "button_previous_pin": 23,
        "button_next_pin": 5,
        "external_pull_up": True,
        "encoder_inverted": False,
    },
    "leds": {
        "pin": 18,
        "count": 8,
        "brightness_cap": 0.25,
        "color_order": "GRB",
        "dma_channel": 10,
    },
    "buzzer": {
        "pin": 12,
        "muted": False,
    },
    "observer": {
        "fallback_latitude": 25.3463,
        "fallback_longitude": 55.4209,
        "fallback_elevation_m": 0.0,
        "gps_grace_seconds": 300.0,
    },
    "gpsd": {
        "host": "127.0.0.1",
        "port": 2947,
        "reconnect_max_seconds": 60.0,
    },
    "adsb": {
        "local_url": "http://127.0.0.1:8080/data/aircraft.json",
        "timeout_seconds": 1.5,
        "stale_seconds": 30.0,
        "max_range_km": 400.0,
        "earth_curvature_correction": True,
        "opensky_enabled": False,
        "opensky_min_interval_seconds": 30.0,
        "opensky_url": "https://opensky-network.org/api/states/all",
        "speed_unit": "knots",
    },
    "orbits": {
        "groups": ["stations", "visual"],
        "refresh_seconds": 43200.0,
        "geometry_refresh_seconds": 10.0,
        "target_elevation_threshold_deg": 10.0,
        "visible_twilight_threshold_deg": -6.0,
        "pass_alert_lead_seconds": 600.0,
        "request_timeout_seconds": 8.0,
    },
}

ENVIRONMENT_OVERRIDES = {
    "ORBITZ_STATE_DIR": ("runtime", "state_dir", str),
    "ORBITZ_LOG_LEVEL": ("runtime", "log_level", str),
    "ORBITZ_DISPLAY_FRAME_RATE": ("runtime", "display_frame_rate", float),
    "ORBITZ_OBSERVER_LATITUDE": ("observer", "fallback_latitude", float),
    "ORBITZ_OBSERVER_LONGITUDE": ("observer", "fallback_longitude", float),
    "ORBITZ_OBSERVER_ELEVATION_M": ("observer", "fallback_elevation_m", float),
    "ORBITZ_GPSD_HOST": ("gpsd", "host", str),
    "ORBITZ_GPSD_PORT": ("gpsd", "port", int),
    "ORBITZ_ADSB_LOCAL_URL": ("adsb", "local_url", str),
    "ORBITZ_OPENSKY_ENABLED": ("adsb", "opensky_enabled", "bool"),
    "ORBITZ_OPENSKY_MIN_INTERVAL_SECONDS": ("adsb", "opensky_min_interval_seconds", float),
    "ORBITZ_LED_BRIGHTNESS_CAP": ("leds", "brightness_cap", float),
    "ORBITZ_ALERT_MUTED": ("buzzer", "muted", "bool"),
    "ORBITZ_ORBIT_GROUPS": ("orbits", "groups", "csv"),
    "ORBITZ_ORBIT_REFRESH_SECONDS": ("orbits", "refresh_seconds", float),
}


@dataclass(frozen=True)
class AppConfig:
    state_dir: Path
    log_level: str
    display_frame_rate: float
    input_debounce_seconds: float
    enable_diagnostics_hold: bool
    diagnostics_hold_seconds: float
    display_width: int
    display_height: int
    display_rotation: int
    display_spi_port: int
    display_spi_device: int
    display_spi_hz: int
    display_mosi_pin: int
    display_sclk_pin: int
    display_cs_pin: int
    display_dc_pin: int
    display_reset_pin: int
    encoder_a_pin: int
    encoder_b_pin: int
    encoder_switch_pin: int
    button_previous_pin: int
    button_next_pin: int
    external_pull_up: bool
    encoder_inverted: bool
    led_pin: int
    led_count: int
    led_brightness_cap: float
    led_color_order: str
    led_dma_channel: int
    buzzer_pin: int
    alert_muted: bool
    fallback_latitude: float
    fallback_longitude: float
    fallback_elevation_m: float
    gps_grace_seconds: float
    gpsd_host: str
    gpsd_port: int
    gps_reconnect_max_seconds: float
    adsb_local_url: str
    adsb_timeout_seconds: float
    adsb_stale_seconds: float
    adsb_max_range_km: float
    earth_curvature_correction: bool
    opensky_enabled: bool
    opensky_min_interval_seconds: float
    opensky_url: str
    speed_unit: str
    orbit_groups: tuple[str, ...]
    orbit_refresh_seconds: float
    geometry_refresh_seconds: float
    target_elevation_threshold_deg: float
    visible_twilight_threshold_deg: float
    pass_alert_lead_seconds: float
    orbit_request_timeout_seconds: float


def _copy_defaults() -> dict[str, Any]:
    return {section: dict(values) for section, values in DEFAULTS.items()}


def _merge(base: dict[str, Any], override: dict[str, Any]) -> None:
    for section, values in override.items():
        if section not in base or not isinstance(values, dict):
            raise ConfigError(f"Unsupported configuration section: {section}")
        for key, value in values.items():
            if key not in base[section]:
                raise ConfigError(f"Unsupported configuration key: {section}.{key}")
            base[section][key] = value


def _environment_value(raw: str, converter: object) -> object:
    if converter == "bool":
        if raw.lower() in {"1", "true", "yes", "on"}:
            return True
        if raw.lower() in {"0", "false", "no", "off"}:
            return False
        raise ConfigError(f"Invalid boolean override: {raw}")
    if converter == "csv":
        return [part.strip() for part in raw.split(",") if part.strip()]
    return converter(raw)


def _validate_pin(value: int, name: str) -> int:
    if not isinstance(value, int) or not 0 <= value <= 27:
        raise ConfigError(f"{name} must be a BCM GPIO number from 0 to 27")
    return value


def _value(config: dict[str, Any], section: str, key: str, expected: type) -> Any:
    value = config[section][key]
    if expected is float and isinstance(value, int):
        return float(value)
    if not isinstance(value, expected):
        raise ConfigError(f"{section}.{key} must be {expected.__name__}")
    return value


def _build(config: dict[str, Any]) -> AppConfig:
    runtime = config["runtime"]
    display = config["display"]
    inputs = config["inputs"]
    leds = config["leds"]
    buzzer = config["buzzer"]
    observer = config["observer"]
    gpsd = config["gpsd"]
    adsb = config["adsb"]
    orbits = config["orbits"]
    latitude = float(_value(config, "observer", "fallback_latitude", float))
    longitude = float(_value(config, "observer", "fallback_longitude", float))
    if not -90.0 <= latitude <= 90.0 or not -180.0 <= longitude <= 180.0:
        raise ConfigError("Observer fallback coordinates are out of range")
    brightness = float(_value(config, "leds", "brightness_cap", float))
    if not 0.0 <= brightness <= 0.25:
        raise ConfigError("leds.brightness_cap must be between 0.0 and 0.25")
    groups = _value(config, "orbits", "groups", list)
    if not groups or any(not isinstance(group, str) or not group.isidentifier() for group in groups):
        raise ConfigError("orbits.groups must contain CelesTrak group names")
    color_order = _value(config, "leds", "color_order", str).upper()
    if color_order not in {"RGB", "GRB", "BRG", "RBG", "GBR", "BGR"}:
        raise ConfigError("leds.color_order is not supported")
    speed_unit = _value(config, "adsb", "speed_unit", str).lower()
    if speed_unit not in {"knots", "kmh"}:
        raise ConfigError("adsb.speed_unit must be knots or kmh")
    positive = [
        (runtime["display_frame_rate"], "runtime.display_frame_rate"),
        (runtime["input_debounce_seconds"], "runtime.input_debounce_seconds"),
        (observer["gps_grace_seconds"], "observer.gps_grace_seconds"),
        (gpsd["reconnect_max_seconds"], "gpsd.reconnect_max_seconds"),
        (adsb["timeout_seconds"], "adsb.timeout_seconds"),
        (adsb["stale_seconds"], "adsb.stale_seconds"),
        (adsb["max_range_km"], "adsb.max_range_km"),
        (adsb["opensky_min_interval_seconds"], "adsb.opensky_min_interval_seconds"),
        (orbits["refresh_seconds"], "orbits.refresh_seconds"),
        (orbits["geometry_refresh_seconds"], "orbits.geometry_refresh_seconds"),
        (orbits["pass_alert_lead_seconds"], "orbits.pass_alert_lead_seconds"),
        (orbits["request_timeout_seconds"], "orbits.request_timeout_seconds"),
    ]
    if any(not isinstance(value, (int, float)) or value <= 0 for value, _ in positive):
        invalid = next(name for value, name in positive if not isinstance(value, (int, float)) or value <= 0)
        raise ConfigError(f"{invalid} must be positive")
    pins = {
        "display.dc_pin": display["dc_pin"], "display.reset_pin": display["reset_pin"],
        "inputs.encoder_a_pin": inputs["encoder_a_pin"], "inputs.encoder_b_pin": inputs["encoder_b_pin"],
        "inputs.encoder_switch_pin": inputs["encoder_switch_pin"], "inputs.button_previous_pin": inputs["button_previous_pin"],
        "inputs.button_next_pin": inputs["button_next_pin"], "leds.pin": leds["pin"], "buzzer.pin": buzzer["pin"],
    }
    for name, pin in pins.items():
        _validate_pin(pin, name)
    if len(set(pins.values())) != len(pins):
        raise ConfigError("GPIO assignments must not overlap")
    if (display["width"], display["height"]) != (240, 320):
        raise ConfigError("display dimensions must be 240 by 320 for the ORBITZ PCB")
    if not isinstance(display["rotation"], int) or display["rotation"] not in {0, 1, 2, 3}:
        raise ConfigError("display.rotation must be 0, 1, 2, or 3")
    if not isinstance(display["spi_port"], int) or display["spi_port"] != 0 or not isinstance(display["spi_device"], int) or display["spi_device"] != 0:
        raise ConfigError("ORBITZ uses SPI0 CE0 with display.spi_port = 0 and display.spi_device = 0")
    if not isinstance(display["spi_hz"], int) or display["spi_hz"] <= 0:
        raise ConfigError("display.spi_hz must be a positive integer")
    display_signals = {"display.mosi_pin": display["mosi_pin"], "display.sclk_pin": display["sclk_pin"], "display.cs_pin": display["cs_pin"]}
    for name, pin in display_signals.items():
        _validate_pin(pin, name)
    if (display["mosi_pin"], display["sclk_pin"], display["cs_pin"]) != (10, 11, 8):
        raise ConfigError("ORBITZ requires SPI0 MOSI 10, SCLK 11, and CE0 8")
    if not isinstance(leds["count"], int) or leds["count"] <= 0:
        raise ConfigError("leds.count must be a positive integer")
    if not isinstance(leds["dma_channel"], int) or leds["dma_channel"] < 0:
        raise ConfigError("leds.dma_channel must be a non-negative integer")
    if not isinstance(gpsd["port"], int) or not 1 <= gpsd["port"] <= 65535:
        raise ConfigError("gpsd.port must be between 1 and 65535")
    if not isinstance(orbits["target_elevation_threshold_deg"], (int, float)) or not -90.0 <= float(orbits["target_elevation_threshold_deg"]) <= 90.0:
        raise ConfigError("orbits.target_elevation_threshold_deg must be between -90 and 90")
    if not isinstance(orbits["visible_twilight_threshold_deg"], (int, float)) or not -90.0 <= float(orbits["visible_twilight_threshold_deg"]) <= 0.0:
        raise ConfigError("orbits.visible_twilight_threshold_deg must be between -90 and 0")
    return AppConfig(
        state_dir=Path(_value(config, "runtime", "state_dir", str)), log_level=_value(config, "runtime", "log_level", str).upper(),
        display_frame_rate=float(runtime["display_frame_rate"]), input_debounce_seconds=float(runtime["input_debounce_seconds"]), enable_diagnostics_hold=_value(config, "runtime", "enable_diagnostics_hold", bool), diagnostics_hold_seconds=float(runtime["diagnostics_hold_seconds"]),
        display_width=display["width"], display_height=display["height"], display_rotation=display["rotation"], display_spi_port=display["spi_port"], display_spi_device=display["spi_device"], display_spi_hz=display["spi_hz"], display_mosi_pin=display["mosi_pin"], display_sclk_pin=display["sclk_pin"], display_cs_pin=display["cs_pin"], display_dc_pin=display["dc_pin"], display_reset_pin=display["reset_pin"],
        encoder_a_pin=inputs["encoder_a_pin"], encoder_b_pin=inputs["encoder_b_pin"], encoder_switch_pin=inputs["encoder_switch_pin"], button_previous_pin=inputs["button_previous_pin"], button_next_pin=inputs["button_next_pin"], external_pull_up=_value(config, "inputs", "external_pull_up", bool), encoder_inverted=_value(config, "inputs", "encoder_inverted", bool),
        led_pin=leds["pin"], led_count=leds["count"], led_brightness_cap=brightness, led_color_order=color_order, led_dma_channel=leds["dma_channel"], buzzer_pin=buzzer["pin"], alert_muted=_value(config, "buzzer", "muted", bool),
        fallback_latitude=latitude, fallback_longitude=longitude, fallback_elevation_m=float(observer["fallback_elevation_m"]), gps_grace_seconds=float(observer["gps_grace_seconds"]), gpsd_host=_value(config, "gpsd", "host", str), gpsd_port=gpsd["port"], gps_reconnect_max_seconds=float(gpsd["reconnect_max_seconds"]),
        adsb_local_url=_value(config, "adsb", "local_url", str), adsb_timeout_seconds=float(adsb["timeout_seconds"]), adsb_stale_seconds=float(adsb["stale_seconds"]), adsb_max_range_km=float(adsb["max_range_km"]), earth_curvature_correction=_value(config, "adsb", "earth_curvature_correction", bool), opensky_enabled=_value(config, "adsb", "opensky_enabled", bool), opensky_min_interval_seconds=float(adsb["opensky_min_interval_seconds"]), opensky_url=_value(config, "adsb", "opensky_url", str), speed_unit=speed_unit,
        orbit_groups=tuple(groups), orbit_refresh_seconds=float(orbits["refresh_seconds"]), geometry_refresh_seconds=float(orbits["geometry_refresh_seconds"]), target_elevation_threshold_deg=float(orbits["target_elevation_threshold_deg"]), visible_twilight_threshold_deg=float(orbits["visible_twilight_threshold_deg"]), pass_alert_lead_seconds=float(orbits["pass_alert_lead_seconds"]), orbit_request_timeout_seconds=float(orbits["request_timeout_seconds"]),
    )


def load_config(path: Path | None = None, environ: dict[str, str] | None = None) -> AppConfig:
    values = _copy_defaults()
    selected_path = path or Path("/etc/orbitz/config.toml")
    if selected_path.exists():
        with selected_path.open("rb") as stream:
            loaded = tomllib.load(stream)
        if not isinstance(loaded, dict):
            raise ConfigError("Configuration root must be a TOML table")
        _merge(values, loaded)
    environment = environ if environ is not None else os.environ
    for variable, (section, key, converter) in ENVIRONMENT_OVERRIDES.items():
        if variable in environment:
            values[section][key] = _environment_value(environment[variable], converter)
    return _build(values)
