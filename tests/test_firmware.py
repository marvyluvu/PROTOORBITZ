import time

import pytest

from orbitz_firmware.alerts import AlertController
from orbitz_firmware.config import ConfigError, load_config
from orbitz_firmware.models import AircraftSnapshot, AppView, Mode, ObserverFix, SatelliteSnapshot, StatusSnapshot, Target
from orbitz_firmware.runtime import route_command
from orbitz_firmware.services.adsb import parse_local_aircraft
from orbitz_firmware.services.geometry import bearing_deg, deduplicate_and_sort, elevation_deg, optical_visibility, plane_geometry
from orbitz_firmware.services.orbits import valid_omm_records


def configuration(tmp_path, body=""):
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_defaults_are_valid_and_environment_overrides_apply(tmp_path):
    loaded = load_config(configuration(tmp_path), {"ORBITZ_STATE_DIR": str(tmp_path / "state"), "ORBITZ_ORBIT_GROUPS": "stations,visual", "ORBITZ_ALERT_MUTED": "true"})
    assert loaded.state_dir == tmp_path / "state"
    assert loaded.adsb_local_url == "http://127.0.0.1:8080/data/aircraft.json"
    assert loaded.orbit_groups == ("stations", "visual")
    assert loaded.alert_muted is True


def test_invalid_configuration_is_rejected(tmp_path):
    with pytest.raises(ConfigError):
        load_config(configuration(tmp_path, "[observer]\nfallback_latitude = 91.0\n"), {})
    with pytest.raises(ConfigError):
        load_config(configuration(tmp_path, "[leds]\nbrightness_cap = 0.5\n"), {})


def observer():
    return ObserverFix(25.3463, 55.4209, 10.0, time.time(), "test", True)


def target(identifier, elevation, distance):
    return Target(identifier, "plane", identifier, 0.0, elevation, distance, 1000.0)


def test_target_deduplication_and_sorting_are_deterministic():
    ordered = deduplicate_and_sort((target("a", 10.0, 100.0), target("b", 20.0, 200.0), target("a", 15.0, 300.0), target("c", 20.0, 50.0)))
    assert [item.identifier for item in ordered] == ["c", "b", "a"]
    assert ordered[-1].elevation_deg == 15.0


def test_aircraft_parser_rejects_bad_ground_and_stale_records(tmp_path):
    config = load_config(configuration(tmp_path), {"ORBITZ_STATE_DIR": str(tmp_path / "state")})
    payload = {"aircraft": [
        {"hex": "a1", "flight": " ORB123 ", "lat": 25.4, "lon": 55.5, "alt_geom": 12000, "gs": 250, "track": 90, "seen": 1, "seen_pos": 1},
        {"hex": "a1", "flight": "DUP", "lat": 25.4, "lon": 55.5, "alt_geom": 13000, "gs": 250, "track": 90, "seen": 1, "seen_pos": 1},
        {"hex": "b2", "lat": 25.5, "lon": 55.5, "alt_geom": 12000, "ground": True, "seen": 1},
        {"hex": "c3", "lat": 25.5, "lon": 55.5, "alt_geom": 12000, "seen": 1000},
        {"hex": "d4", "lat": "bad", "lon": 55.5, "alt_geom": 12000},
    ]}
    targets = parse_local_aircraft(payload, observer(), config)
    assert len(targets) == 1
    assert targets[0].identifier == "aircraft:a1"
    assert targets[0].name in {"ORB123", "DUP"}
    assert targets[0].speed == 250.0


def test_geometric_bearing_and_elevation_behave_as_expected():
    assert bearing_deg(0.0, 0.0, 1.0, 0.0) == pytest.approx(0.0, abs=0.01)
    assert bearing_deg(0.0, 0.0, 0.0, 1.0) == pytest.approx(90.0, abs=0.01)
    assert elevation_deg(1000.0, 0.0, 1000.0, False) == pytest.approx(45.0, abs=0.1)
    azimuth, elevation, distance = plane_geometry(0.0, 0.0, 0.0, 0.0, 0.01, 1000.0, True)
    assert azimuth == pytest.approx(90.0, abs=0.1)
    assert elevation > 0.0
    assert distance > 1.0


def test_omm_validation_and_optical_visibility_logic():
    record = {"OBJECT_NAME": "ISS (ZARYA)", "EPOCH": "2026-01-01T00:00:00.000000", "MEAN_MOTION": 15.5, "ECCENTRICITY": 0.0001, "INCLINATION": 51.6, "RA_OF_ASC_NODE": 0.0, "ARG_OF_PERICENTER": 0.0, "MEAN_ANOMALY": 0.0, "NORAD_CAT_ID": 25544}
    assert valid_omm_records([record])
    assert not valid_omm_records([{"OBJECT_NAME": "broken"}])
    assert optical_visibility(15.0, True, -8.0, 10.0, -6.0)
    assert not optical_visibility(9.0, True, -8.0, 10.0, -6.0)
    assert not optical_visibility(15.0, False, -8.0, 10.0, -6.0)
    assert not optical_visibility(15.0, True, -4.0, 10.0, -6.0)


def test_event_routing_changes_selection_and_mode():
    targets = (target("one", 10.0, 20.0), target("two", 5.0, 30.0))
    from orbitz_firmware.models import Command
    assert route_command(Mode.PLANES, "one", targets, Command.NEXT) == (Mode.PLANES, "two")
    assert route_command(Mode.PLANES, "one", targets, Command.PREVIOUS) == (Mode.PLANES, "two")
    assert route_command(Mode.PLANES, "one", targets, Command.TOGGLE_MODE) == (Mode.SATELLITES, None)


class Output:
    def __init__(self):
        self.colors = []
        self.tones = []

    def set_color(self, color):
        self.colors.append(color)

    def play(self, pattern):
        self.tones.append(pattern)


def test_alert_controller_deduplicates_iss_prepass_alert(tmp_path):
    config = load_config(configuration(tmp_path), {"ORBITZ_STATE_DIR": str(tmp_path / "state")})
    output = Output()
    controller = AlertController(config, output)
    controller.boot_started -= 10.0
    now = time.time()
    status = StatusSnapshot(observer(), AircraftSnapshot(), SatelliteSnapshot(iss_next_rise=now + 60.0))
    view = AppView(Mode.SATELLITES, None, (), status, now)
    controller.update(view)
    controller.update(view)
    assert output.colors[-1] == (128, 64, 0)
    assert len(output.tones) == 1
