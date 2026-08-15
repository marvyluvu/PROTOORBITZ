# ORBITZ

**ORBITZ** is a portable plane, satellite, and International Space Station tracker designed for a Raspberry Pi Zero 2 W connected to the ORBITZ PCB. The firmware renders a 240×320 ILI9341 radar interface, reads the physical EC11 encoder and two buttons, obtains position from GPSD, prioritizes a local ADS-B receiver, obtains orbital elements from CelesTrak, and drives the onboard WS2812B LED halo and passive piezo alert.

The production application is invoked as `python3 -m orbitz_firmware.main`. It is hardware-first: there is no desktop/Pygame mode, no keyboard control path, and no mock peripheral layer. Hardware initialization happens explicitly at runtime, allowing configuration, service, and geometry tests to run on a non-Pi host.

## Hardware contract

The ORBITZ PCB is the authoritative wiring source. The ILI9341 uses SPI0 with BCM 10, 11, and 8 for MOSI, SCLK, and CE0, with BCM 24 for D/C and BCM 25 for reset. This follows the standard Raspberry Pi SPI0 connection arrangement documented by Luma.LCD, while the PCB pin mapping remains authoritative.[[Luma.LCD hardware documentation](https://luma-lcd.readthedocs.io/en/latest/hardware.html)]

| Peripheral | BCM GPIO | Firmware behavior |
|---|---:|---|
| ILI9341 MOSI, SCLK, CS | 10, 11, 8 | SPI0 display transport |
| ILI9341 D/C, RST | 24, 25 | Display control pins |
| EC11 A, B, switch | 17, 27, 22 | Active-low event-driven input |
| Previous, next buttons | 23, 5 | Active-low target selection |
| WS2812B data | 18 | DMA/PWM timing through the PCB level shifter |
| Passive piezo control | 12 | Bounded software-timed alert output |

> **Electrical safety.** The ILI9341 and Raspberry Pi GPIO logic use **3.3 V**. The ORBITZ PCB’s 74AHCT125 is responsible for the separate **5 V WS2812B data path**. Do not bypass the PCB or its level shifter, and verify a stable, adequately rated 5 V supply before powering the Pi, display, LED halo, GPS receiver, and RTL-SDR together.

## Pi preparation

Use Raspberry Pi OS Bookworm or later on the Raspberry Pi Zero 2 W. Attach the ORBITZ PCB before running physical diagnostics. The installer enables SPI, installs the runtime dependencies in `/opt/orbitz-venv`, copies the repository into `/opt/orbitz`, creates `/etc/orbitz` and `/var/lib/orbitz`, preserves an existing live configuration and cache, installs the service unit, and disables the conflicting onboard PWM-audio module used by the WS2812B driver.[[rpi_ws281x documentation](https://github.com/jgarff/rpi_ws281x)]

```sh
git clone https://github.com/marvyluvu/ORBITZ.git
cd ORBITZ
git checkout hardware-firmware
sudo sh scripts/install_pi.sh
sudoedit /etc/orbitz/config.toml
sudo systemctl enable --now orbitz.service
sudo systemctl status orbitz.service
sudo journalctl -u orbitz.service -f
```

The service runs as root because the selected `rpi-ws281x` DMA/PWM backend commonly requires privileged access to its hardware resources. Its writable filesystem is restricted to `/var/lib/orbitz`; the service uses a protected system filesystem and private temporary directory. If a future verified backend supports non-root DMA access, the unit should be tightened further.

## GPSD and local ADS-B receiver

ORBITZ expects a local GPSD server at `127.0.0.1:2947`. The GPS client maintains a single JSON watch connection and automatically reconnects with bounded backoff. A valid last GPS fix remains available for the configured grace period; the interface then labels and uses the configured fallback observer location.

```sh
sudo systemctl enable --now gpsd
cgps -s
```

The primary aircraft source is a local dump1090/readsb-compatible endpoint at `http://127.0.0.1:8080/data/aircraft.json`. A reachable local receiver with zero aircraft is still considered a valid local result. OpenSky is an optional fallback that is contacted only if the local endpoint is unavailable, `opensky_enabled` is true, and the configured request interval permits it. OpenSky credentials, when used, must be supplied only through `ORBITZ_OPENSKY_USERNAME` and `ORBITZ_OPENSKY_PASSWORD` environment variables for the service; they must not be committed to configuration files.

```sh
curl --fail http://127.0.0.1:8080/data/aircraft.json
```

## Configuration

Configuration precedence is built-in safe defaults, `/etc/orbitz/config.toml`, then explicitly supported `ORBITZ_` environment variables. Copying `config.example.toml` gives the complete configuration surface. Every configured value is validated at startup.

| Setting group | Values to personalize | Purpose |
|---|---|---|
| `observer` | `fallback_latitude`, `fallback_longitude`, `fallback_elevation_m` | Used before a GPS fix or after the grace period |
| `display` | `rotation`, `spi_hz` | Aligns output with the fitted ILI9341 panel |
| `inputs` | `encoder_inverted`, `external_pull_up` | Corrects encoder direction and electrical input semantics |
| `leds` | `count`, `brightness_cap`, `color_order` | Matches halo wiring and caps brightness at 25% or less |
| `buzzer` | `muted` | Preserves visual alerts while disabling audio |
| `adsb` | `local_url`, `max_range_km`, `opensky_enabled`, `speed_unit` | Chooses aircraft source and presentation range |
| `orbits` | `groups`, `target_elevation_threshold_deg`, `visible_twilight_threshold_deg`, `pass_alert_lead_seconds` | Chooses orbital groups and alert/visibility thresholds |

```sh
sudo cp config.example.toml /etc/orbitz/config.toml
sudoedit /etc/orbitz/config.toml
sudo systemctl restart orbitz.service
```

ORBITZ stores atomic, timestamped GPS, ADS-B, and orbital caches below `/var/lib/orbitz`. It starts with valid cache data while offline. CelesTrak OMM JSON is cached independently for each group so one remote URL cannot overwrite another group’s data. OMM records are converted with `EarthSatellite.from_omm()`; the firmware includes the ISS exactly once and evaluates horizon visibility, satellite sunlight, and observer twilight rather than labeling all targets above an elevation threshold as optically visible.[[Skyfield satellite documentation](https://rhodesmill.org/skyfield/earth-satellites.html)]

## Controls and display

The display is rendered to an off-screen Pillow RGB image and then presented in a single physical-screen update. The radar is north-up; elevation maps from the outer rim at 0° to the center at 90°. Plane, ISS, horizon-visible satellite, and optically visible satellite markers use distinct colors. Long target names are ellipsized to remain within the 240×320 layout.

| Physical action | Result |
|---|---|
| Encoder clockwise | Select next target |
| Encoder counter-clockwise | Select previous target |
| Encoder switch | Toggle PLANES and SATELLITES |
| Button 1 | Select previous target |
| Button 2 | Select next target |
| Encoder switch long hold | Opens diagnostics only when enabled in configuration |

The alert halo is dim blue for live plane data, dim cyan for satellite mode without a visible selected target, green for an optically visible selected satellite, amber during the configured ISS pre-pass window, and red for a hardware or data error. Each ISS pass can generate at most one tone sequence per process lifetime, and muting disables only tones.

## Diagnostics

Diagnostics are deliberate and bounded. They never start automatically, and the ADS-B check does not request OpenSky. Run a selected subset first after installation and before enabling the service.

```sh
cd /opt/orbitz
sudo /opt/orbitz-venv/bin/python -m orbitz_firmware.main --diagnostics display led buzzer
sudo /opt/orbitz-venv/bin/python -m orbitz_firmware.main --diagnostics input
sudo /opt/orbitz-venv/bin/python -m orbitz_firmware.main --diagnostics gps adsb orbit-cache
```

The display check draws a color-and-text screen. The LED check uses capped brightness and ends with LEDs off. The buzzer check plays a short sequence and returns inactive. The input check waits up to ten seconds and reports received events. The GPS, ADS-B, and orbit checks report source and status without entering the normal UI loop.

## Troubleshooting

| Symptom | Likely cause | Resolution |
|---|---|---|
| Display remains blank | SPI is disabled, display rotation is wrong, or power is incorrect | Run the display diagnostic, check `ls -l /dev/spidev*`, then verify the PCB connection and 3.3 V display supply |
| Encoder moves in reverse | Encoder phase wiring direction differs | Set `encoder_inverted = true` and restart the service |
| Inputs do not register | Pull mode does not match the PCB or a GPIO conflict exists | Keep `external_pull_up = true` for the supplied active-low inputs and run the input diagnostic |
| LEDs do not light | PWM audio conflicts or insufficient 5 V LED power | Reboot after installation, confirm the audio blacklist file, verify the PCB level shifter and LED supply, then run the LED diagnostic |
| No GPS fix | GPSD is not receiving receiver data | Inspect `cgps -s`, then inspect `systemctl status gpsd` and the ORBITZ journal |
| No planes but local receiver is running | The receiver reports zero aircraft or records are stale/grounded | Check the local endpoint with `curl`; ORBITZ intentionally reports a valid zero-aircraft local snapshot |
| OpenSky is never used | Local endpoint is reachable or fallback is disabled | Confirm `opensky_enabled = true`; fallback starts only when the local endpoint is unavailable and the request interval permits it |
| Orbital data is stale | Network failure or CelesTrak refresh backoff | Verify network access, retain the older valid cache, and inspect the journal for the next attempted refresh |

## Development verification

The hardware-independent suite covers configuration validation, target ordering and deduplication, ADS-B parsing, aircraft geometry, OMM cache validation, optical visibility, command routing, and ISS alert deduplication. It does not import GPIO or display hardware modules.

```sh
python3 -m pip install -r requirements-dev.txt
python3 -m compileall -q orbitz_firmware
pytest -q
python3 -c 'from orbitz_firmware.config import load_config; print(load_config())'
```

Physical display, encoder, LED, buzzer, GPS, RTL-SDR, and installed service validation must be performed on the target Pi after deployment. The development environment cannot truthfully substitute for hardware verification.
