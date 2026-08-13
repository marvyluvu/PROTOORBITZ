from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


class Mode(str, Enum):
    PLANES = "PLANES"
    SATELLITES = "SATELLITES"


class Command(str, Enum):
    NEXT = "NEXT"
    PREVIOUS = "PREVIOUS"
    TOGGLE_MODE = "TOGGLE_MODE"
    DIAGNOSTICS = "DIAGNOSTICS"


@dataclass(frozen=True)
class ObserverFix:
    latitude: float
    longitude: float
    elevation_m: float
    timestamp: float
    source: str
    valid: bool


@dataclass(frozen=True)
class Target:
    identifier: str
    kind: str
    name: str
    azimuth_deg: float
    elevation_deg: float
    range_km: float
    altitude_m: float
    latitude: float | None = None
    longitude: float | None = None
    heading_deg: float | None = None
    speed: float | None = None
    source: str = ""
    above_horizon: bool = False
    optically_visible: bool = False


@dataclass(frozen=True)
class AircraftSnapshot:
    targets: tuple[Target, ...] = ()
    timestamp: float = 0.0
    source: str = "unavailable"
    stale: bool = False
    error: str | None = None


@dataclass(frozen=True)
class SatelliteSnapshot:
    targets: tuple[Target, ...] = ()
    timestamp: float = 0.0
    source: str = "unavailable"
    stale: bool = False
    iss_next_rise: float | None = None
    error: str | None = None


@dataclass(frozen=True)
class StatusSnapshot:
    gps: ObserverFix
    aircraft: AircraftSnapshot = field(default_factory=AircraftSnapshot)
    satellites: SatelliteSnapshot = field(default_factory=SatelliteSnapshot)
    hardware_errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class AlertDecision:
    color: tuple[int, int, int]
    tone: tuple[tuple[int, float], ...] = ()
    key: str | None = None


@dataclass(frozen=True)
class AppView:
    mode: Mode
    selected_identifier: str | None
    targets: tuple[Target, ...]
    status: StatusSnapshot
    rendered_at: float


@dataclass(frozen=True)
class CacheRecord:
    timestamp: float
    source: str
    payload: object
    metadata: Mapping[str, object]
