import logging
import os
import time
from typing import Any

import requests

from ..config import AppConfig
from ..models import AircraftSnapshot, CacheRecord, ObserverFix, Target
from ..storage import AtomicCache
from .geometry import deduplicate_and_sort, finite_number, plane_geometry


logger = logging.getLogger(__name__)


def parse_local_aircraft(payload: object, observer: ObserverFix, config: AppConfig) -> tuple[Target, ...]:
    if not isinstance(payload, dict) or not isinstance(payload.get("aircraft"), list):
        raise ValueError("Local ADS-B payload does not contain an aircraft list")
    targets: list[Target] = []
    for item in payload["aircraft"]:
        if not isinstance(item, dict):
            continue
        identifier = str(item.get("hex") or "").strip().lower()
        latitude = finite_number(item.get("lat"))
        longitude = finite_number(item.get("lon"))
        altitude_feet = finite_number(item.get("alt_geom"))
        if altitude_feet is None:
            altitude_feet = finite_number(item.get("alt_baro"))
        seen = finite_number(item.get("seen"))
        seen_position = finite_number(item.get("seen_pos"))
        if not identifier or latitude is None or longitude is None or altitude_feet is None or not -90.0 <= latitude <= 90.0 or not -180.0 <= longitude <= 180.0:
            continue
        if item.get("ground") is True or (seen is not None and seen > config.adsb_stale_seconds) or (seen_position is not None and seen_position > config.adsb_stale_seconds):
            continue
        azimuth, elevation, range_km = plane_geometry(observer.latitude, observer.longitude, observer.elevation_m, latitude, longitude, altitude_feet * 0.3048, config.earth_curvature_correction)
        if range_km > config.adsb_max_range_km:
            continue
        speed_knots = finite_number(item.get("gs")) or 0.0
        speed = speed_knots if config.speed_unit == "knots" else speed_knots * 1.852
        callsign = str(item.get("flight") or "").strip()
        heading = finite_number(item.get("track"))
        targets.append(Target(identifier=f"aircraft:{identifier}", kind="plane", name=callsign or identifier.upper(), azimuth_deg=azimuth, elevation_deg=elevation, range_km=range_km, altitude_m=altitude_feet * 0.3048, latitude=latitude, longitude=longitude, heading_deg=heading, speed=speed, source="local", above_horizon=elevation >= 0.0))
    return deduplicate_and_sort(targets)


def parse_opensky_aircraft(payload: object, observer: ObserverFix, config: AppConfig) -> tuple[Target, ...]:
    if not isinstance(payload, dict) or not isinstance(payload.get("states"), list):
        raise ValueError("OpenSky payload does not contain states")
    local_payload: dict[str, list[dict[str, object]]] = {"aircraft": []}
    for state in payload["states"]:
        if not isinstance(state, list) or len(state) < 11:
            continue
        local_payload["aircraft"].append({"hex": state[0], "flight": state[1], "lon": state[5], "lat": state[6], "alt_baro": None if state[7] is None else float(state[7]) / 0.3048, "ground": state[8], "gs": 0.0 if state[9] is None else float(state[9]) / 0.514444, "track": state[10], "seen": 0.0, "seen_pos": 0.0})
    return parse_local_aircraft(local_payload, observer, config)


class AdsbService:
    def __init__(self, config: AppConfig, cache: AtomicCache, session: requests.Session | None = None):
        self.config = config
        self.cache = cache
        self.session = session or requests.Session()
        self.next_opensky_request = 0.0

    def _read_json(self, url: str) -> object:
        response = self.session.get(url, timeout=self.config.adsb_timeout_seconds)
        response.raise_for_status()
        return response.json()

    def refresh(self, observer: ObserverFix, now: float | None = None) -> AircraftSnapshot:
        current = time.time() if now is None else now
        try:
            payload = self._read_json(self.config.adsb_local_url)
            targets = parse_local_aircraft(payload, observer, self.config)
            self.cache.write("adsb_snapshot", CacheRecord(current, "local", payload, {"target_count": len(targets)}))
            return AircraftSnapshot(targets, current, "local", False)
        except (requests.RequestException, ValueError, TypeError) as error:
            local_error = str(error)
            logger.warning("Local ADS-B refresh failed: %s", local_error)
        if self.config.opensky_enabled and current >= self.next_opensky_request:
            self.next_opensky_request = current + self.config.opensky_min_interval_seconds
            credentials = None
            username = os.getenv("ORBITZ_OPENSKY_USERNAME")
            password = os.getenv("ORBITZ_OPENSKY_PASSWORD")
            if username and password:
                credentials = (username, password)
            try:
                response = self.session.get(self.config.opensky_url, timeout=self.config.adsb_timeout_seconds, auth=credentials)
                response.raise_for_status()
                payload = response.json()
                targets = parse_opensky_aircraft(payload, observer, self.config)
                self.cache.write("adsb_snapshot", CacheRecord(current, "opensky", payload, {"target_count": len(targets)}))
                return AircraftSnapshot(targets, current, "opensky", False)
            except (requests.RequestException, ValueError, TypeError) as error:
                local_error = f"{local_error}; OpenSky: {error}"
        cached = self.cache.read("adsb_snapshot")
        if cached is not None and current - cached.timestamp <= self.config.adsb_stale_seconds:
            try:
                parser = parse_local_aircraft if cached.source == "local" else parse_opensky_aircraft
                return AircraftSnapshot(parser(cached.payload, observer, self.config), cached.timestamp, cached.source, True, local_error)
            except (ValueError, TypeError):
                pass
        return AircraftSnapshot((), current, "unavailable", False, local_error)
