import json
import logging
import time
from pathlib import Path
from typing import Any

import requests

from ..config import AppConfig
from ..models import CacheRecord, ObserverFix, SatelliteSnapshot, Target
from ..storage import AtomicCache
from .geometry import deduplicate_and_sort, optical_visibility


logger = logging.getLogger(__name__)
OMM_KEYS = {"OBJECT_NAME", "EPOCH", "MEAN_MOTION", "ECCENTRICITY", "INCLINATION", "RA_OF_ASC_NODE", "ARG_OF_PERICENTER", "MEAN_ANOMALY", "NORAD_CAT_ID"}


def valid_omm_records(payload: object) -> bool:
    return isinstance(payload, list) and bool(payload) and all(isinstance(record, dict) and OMM_KEYS.issubset(record) for record in payload)


class OrbitService:
    def __init__(self, config: AppConfig, cache: AtomicCache, package_dir: Path, session: requests.Session | None = None):
        self.config = config
        self.cache = cache
        self.package_dir = package_dir
        self.session = session or requests.Session()
        self.next_attempt: dict[str, float] = {}
        self.failure_delay: dict[str, float] = {}
        self.records: tuple[dict[str, Any], ...] = ()
        self.loaded_at = 0.0

    def _name(self, group: str) -> str:
        return f"omm_{group}"

    def _download(self, group: str) -> list[dict[str, Any]]:
        url = f"https://celestrak.org/NORAD/elements/gp.php?GROUP={group}&FORMAT=json"
        response = self.session.get(url, timeout=self.config.orbit_request_timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        if not valid_omm_records(payload):
            raise ValueError(f"CelesTrak group {group} returned invalid OMM JSON")
        return payload

    def refresh_records(self, now: float | None = None) -> tuple[dict[str, Any], ...]:
        current = time.time() if now is None else now
        selected: dict[str, dict[str, Any]] = {}
        for group in self.config.orbit_groups:
            cache_name = self._name(group)
            cached = self.cache.read(cache_name, valid_omm_records)
            payload: list[dict[str, Any]] | None = None
            is_due = cached is None or current - cached.timestamp >= self.config.orbit_refresh_seconds
            if is_due and current >= self.next_attempt.get(group, 0.0):
                try:
                    payload = self._download(group)
                    self.cache.write(cache_name, CacheRecord(current, f"celestrak:{group}", payload, {"group": group}))
                    self.failure_delay[group] = 60.0
                except (requests.RequestException, ValueError, TypeError) as error:
                    delay = self.failure_delay.get(group, 60.0)
                    self.next_attempt[group] = current + delay
                    self.failure_delay[group] = min(delay * 2.0, self.config.orbit_refresh_seconds)
                    logger.warning("Orbital refresh for %s failed: %s", group, error)
            if payload is None and cached is not None:
                payload = cached.payload
            if payload is not None:
                for record in payload:
                    identifier = str(record["NORAD_CAT_ID"])
                    selected[identifier] = record
        if "25544" not in selected:
            cached_iss = self.cache.read(self._name("stations"), valid_omm_records)
            if cached_iss:
                for record in cached_iss.payload:
                    if str(record.get("NORAD_CAT_ID")) == "25544":
                        selected["25544"] = record
        self.records = tuple(selected.values())
        self.loaded_at = current
        return self.records

    def _skyfield(self) -> tuple[Any, Any, Any]:
        from skyfield.api import load, load_file, wgs84
        ephemeris_path = self.package_dir / "skyfield_data" / "de421.bsp"
        if not ephemeris_path.exists():
            raise FileNotFoundError(f"Missing ephemeris: {ephemeris_path}")
        return load.timescale(), load_file(ephemeris_path), wgs84

    def satellites(self) -> tuple[Any, ...]:
        from skyfield.api import EarthSatellite
        timescale, _, _ = self._skyfield()
        records = self.records or self.refresh_records()
        satellites = []
        for record in records:
            try:
                satellites.append(EarthSatellite.from_omm(timescale, record))
            except (KeyError, TypeError, ValueError) as error:
                logger.warning("Skipping invalid OMM record: %s", error)
        return tuple(satellites)

    def snapshot(self, observer_fix: ObserverFix, now: float | None = None) -> SatelliteSnapshot:
        current = time.time() if now is None else now
        try:
            self.refresh_records(current)
            timescale, ephemeris, wgs84 = self._skyfield()
            observer = wgs84.latlon(observer_fix.latitude, observer_fix.longitude, elevation_m=observer_fix.elevation_m)
            instant = timescale.utc(*time.gmtime(current)[:6])
            earth = ephemeris["earth"]
            sun_altitude = (earth + observer).at(instant).observe(ephemeris["sun"]).apparent().altaz()[0].degrees
            targets: list[Target] = []
            iss = None
            for satellite in self.satellites():
                topocentric = (satellite - observer).at(instant)
                altitude, azimuth, distance = topocentric.altaz()
                geocentric = satellite.at(instant)
                subpoint = wgs84.subpoint_of(geocentric)
                sunlit = bool(geocentric.is_sunlit(ephemeris))
                visible = optical_visibility(altitude.degrees, sunlit, sun_altitude, self.config.target_elevation_threshold_deg, self.config.visible_twilight_threshold_deg)
                identifier = str(satellite.model.satnum)
                kind = "iss" if identifier == "25544" else "satellite"
                target = Target(identifier=f"satellite:{identifier}", kind=kind, name=satellite.name, azimuth_deg=azimuth.degrees, elevation_deg=altitude.degrees, range_km=distance.km, altitude_m=subpoint.elevation.m, latitude=subpoint.latitude.degrees, longitude=subpoint.longitude.degrees, source="celestrak", above_horizon=altitude.degrees >= 0.0, optically_visible=visible)
                targets.append(target)
                if kind == "iss":
                    iss = satellite
            next_rise = self._next_iss_rise(iss, observer, timescale, current) if iss is not None else None
            return SatelliteSnapshot(deduplicate_and_sort(targets), current, "celestrak", False, next_rise)
        except (OSError, ValueError, KeyError, TypeError, requests.RequestException) as error:
            return SatelliteSnapshot((), current, "unavailable", False, None, str(error))

    def _next_iss_rise(self, satellite: Any, observer: Any, timescale: Any, current: float) -> float | None:
        start = timescale.utc(*time.gmtime(current)[:6])
        end = timescale.utc(*time.gmtime(current + 86400.0)[:6])
        moments, events = satellite.find_events(observer, start, end, altitude_degrees=self.config.target_elevation_threshold_deg)
        for moment, event in zip(moments, events):
            if event == 0:
                return moment.utc_datetime().timestamp()
        return None
