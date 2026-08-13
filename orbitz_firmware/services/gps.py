import json
import logging
import socket
import threading
import time
from typing import Callable

from ..config import AppConfig
from ..models import CacheRecord, ObserverFix
from ..storage import AtomicCache
from .geometry import finite_number


logger = logging.getLogger(__name__)


def valid_fix(payload: object, source: str, now: float, fallback_elevation_m: float) -> ObserverFix | None:
    if not isinstance(payload, dict) or payload.get("class") != "TPV":
        return None
    latitude = finite_number(payload.get("lat"))
    longitude = finite_number(payload.get("lon"))
    altitude = finite_number(payload.get("altHAE"))
    if altitude is None:
        altitude = finite_number(payload.get("alt"))
    if latitude is None or longitude is None or not -90.0 <= latitude <= 90.0 or not -180.0 <= longitude <= 180.0:
        return None
    return ObserverFix(latitude, longitude, fallback_elevation_m if altitude is None else altitude, now, source, True)


class GpsService:
    def __init__(self, config: AppConfig, cache: AtomicCache):
        self.config = config
        self.cache = cache
        self.lock = threading.Lock()
        cached = cache.read("gps_position")
        self.last_fix = self._record_to_fix(cached) if cached else None

    def _record_to_fix(self, record: CacheRecord | None) -> ObserverFix | None:
        if record is None or not isinstance(record.payload, dict):
            return None
        try:
            return ObserverFix(float(record.payload["latitude"]), float(record.payload["longitude"]), float(record.payload["elevation_m"]), record.timestamp, record.source, True)
        except (KeyError, TypeError, ValueError):
            return None

    def observer(self, now: float | None = None) -> ObserverFix:
        current = time.time() if now is None else now
        with self.lock:
            fix = self.last_fix
        if fix is not None and current - fix.timestamp <= self.config.gps_grace_seconds:
            return fix
        return ObserverFix(self.config.fallback_latitude, self.config.fallback_longitude, self.config.fallback_elevation_m, current, "fallback", False)

    def _accept(self, fix: ObserverFix) -> None:
        with self.lock:
            self.last_fix = fix
        self.cache.write("gps_position", CacheRecord(fix.timestamp, fix.source, {"latitude": fix.latitude, "longitude": fix.longitude, "elevation_m": fix.elevation_m}, {}))

    def run(self, stop_event: threading.Event, on_change: Callable[[ObserverFix], None] | None = None) -> None:
        delay = 1.0
        while not stop_event.is_set():
            try:
                with socket.create_connection((self.config.gpsd_host, self.config.gpsd_port), timeout=5.0) as connection:
                    connection.settimeout(2.0)
                    connection.sendall(b'?WATCH={"enable":true,"json":true};\n')
                    buffer = b""
                    delay = 1.0
                    while not stop_event.is_set():
                        try:
                            chunk = connection.recv(4096)
                        except socket.timeout:
                            continue
                        if not chunk:
                            raise ConnectionError("GPSD closed the connection")
                        buffer += chunk
                        while b"\n" in buffer:
                            line, buffer = buffer.split(b"\n", 1)
                            try:
                                payload = json.loads(line.decode("utf-8"))
                            except (UnicodeDecodeError, json.JSONDecodeError):
                                continue
                            fix = valid_fix(payload, "gpsd", time.time(), self.config.fallback_elevation_m)
                            if fix is not None:
                                self._accept(fix)
                                if on_change is not None:
                                    on_change(fix)
            except OSError as error:
                logger.warning("GPSD connection failed: %s", error)
                stop_event.wait(delay)
                delay = min(delay * 2.0, self.config.gps_reconnect_max_seconds)
