from math import atan2, cos, degrees, radians, sin, sqrt
from typing import Iterable

from ..models import Target

EARTH_RADIUS_M = 6371008.8


def finite_number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def ground_range_m(latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float) -> float:
    phi_a = radians(latitude_a)
    phi_b = radians(latitude_b)
    delta_phi = radians(latitude_b - latitude_a)
    delta_lambda = radians(longitude_b - longitude_a)
    value = sin(delta_phi / 2.0) ** 2 + cos(phi_a) * cos(phi_b) * sin(delta_lambda / 2.0) ** 2
    return EARTH_RADIUS_M * 2.0 * atan2(sqrt(value), sqrt(max(0.0, 1.0 - value)))


def bearing_deg(latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float) -> float:
    phi_a = radians(latitude_a)
    phi_b = radians(latitude_b)
    delta_lambda = radians(longitude_b - longitude_a)
    x = sin(delta_lambda) * cos(phi_b)
    y = cos(phi_a) * sin(phi_b) - sin(phi_a) * cos(phi_b) * cos(delta_lambda)
    return (degrees(atan2(x, y)) + 360.0) % 360.0


def elevation_deg(ground_m: float, observer_elevation_m: float, target_elevation_m: float, curvature: bool) -> float:
    if ground_m <= 0.0:
        return 90.0 if target_elevation_m >= observer_elevation_m else -90.0
    if not curvature:
        return degrees(atan2(target_elevation_m - observer_elevation_m, ground_m))
    theta = ground_m / EARTH_RADIUS_M
    observer_radius = EARTH_RADIUS_M + observer_elevation_m
    target_radius = EARTH_RADIUS_M + target_elevation_m
    numerator = target_radius * cos(theta) - observer_radius
    denominator = target_radius * sin(theta)
    return degrees(atan2(numerator, denominator))


def plane_geometry(observer_latitude: float, observer_longitude: float, observer_elevation_m: float, latitude: float, longitude: float, altitude_m: float, curvature: bool) -> tuple[float, float, float]:
    distance_m = ground_range_m(observer_latitude, observer_longitude, latitude, longitude)
    return bearing_deg(observer_latitude, observer_longitude, latitude, longitude), elevation_deg(distance_m, observer_elevation_m, altitude_m, curvature), distance_m / 1000.0


def deduplicate_and_sort(targets: Iterable[Target]) -> tuple[Target, ...]:
    selected: dict[str, Target] = {}
    for target in targets:
        existing = selected.get(target.identifier)
        if existing is None or (target.elevation_deg, -target.range_km, target.name) > (existing.elevation_deg, -existing.range_km, existing.name):
            selected[target.identifier] = target
    return tuple(sorted(selected.values(), key=lambda item: (-item.elevation_deg, item.range_km, item.name.casefold(), item.identifier)))


def optical_visibility(elevation: float, sunlit: bool, sun_altitude: float, target_threshold: float, twilight_threshold: float) -> bool:
    return elevation >= target_threshold and sunlit and sun_altitude <= twilight_threshold
