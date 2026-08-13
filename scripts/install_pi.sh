set -eu
root_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ "$(id -u)" -ne 0 ]; then
  printf '%s\n' "Run with sudo sh scripts/install_pi.sh" >&2
  exit 1
fi
apt-get update
apt-get install -y python3-venv python3-dev build-essential git gpsd gpsd-clients libgpiod2
raspi-config nonint do_spi 0
install -d -m 0755 /etc/orbitz /var/lib/orbitz /opt/orbitz
cp -a "$root_dir"/. /opt/orbitz/
if [ ! -f /etc/orbitz/config.toml ]; then
  install -m 0640 "$root_dir/config.example.toml" /etc/orbitz/config.toml
fi
python3 -m venv /opt/orbitz-venv
/opt/orbitz-venv/bin/pip install --upgrade pip
/opt/orbitz-venv/bin/pip install -r /opt/orbitz/orbitz_firmware/requirements.txt
install -m 0644 /opt/orbitz/systemd/orbitz.service /etc/systemd/system/orbitz.service
printf '%s\n' "blacklist snd_bcm2835" >/etc/modprobe.d/orbitz-ws281x.conf
systemctl daemon-reload
printf '%s\n' "Run: sudo systemctl enable --now orbitz.service"
printf '%s\n' "Inspect: sudo systemctl status orbitz.service"
printf '%s\n' "Logs: sudo journalctl -u orbitz.service -f"
