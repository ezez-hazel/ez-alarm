#!/bin/sh
set -eu

PREFIX=${PREFIX:-/usr/bin}
CONFIG_DIR=${CONFIG_DIR:-/etc/ez-alarm}
SERVICE_DIR=/etc/systemd/system
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if [ "$(id -u)" -ne 0 ]; then
	echo "This installer must be run as root (use sudo)." >&2
	exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
	echo "systemctl is required." >&2
	exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
	echo "python3 is required." >&2
	exit 1
fi

install -d "$PREFIX" "$CONFIG_DIR"

install -o root -g root -m 0755 "$SCRIPT_DIR/ez_alarm.py" "$PREFIX/ez_alarm.py"
ln -sfn ez_alarm.py "$PREFIX/ez-alarm"

install -o root -g root -m 0644 "$SCRIPT_DIR/ez-alarm.service" "$SERVICE_DIR/ez-alarm.service"
install -o root -g root -m 0644 "$SCRIPT_DIR/ez-alarm.timer" "$SERVICE_DIR/ez-alarm.timer"

if [ ! -e "$CONFIG_DIR/ez-alarm.env" ]; then
	install -o root -g root -m 0600 "$SCRIPT_DIR/ez-alarm.env.example" "$CONFIG_DIR/ez-alarm.env"
	echo "Created $CONFIG_DIR/ez-alarm.env; edit it before starting the timer." >&2
else
	chmod 0600 "$CONFIG_DIR/ez-alarm.env"
fi

systemctl daemon-reload

if grep -q '^CLOUDFLARE_API_TOKEN=your-cloudflare-api-token$' "$CONFIG_DIR/ez-alarm.env"; then
	echo "Configuration is incomplete; timer was not enabled." >&2
	echo "Edit $CONFIG_DIR/ez-alarm.env, then run:" >&2
	echo "  systemctl enable --now ez-alarm.timer" >&2
	exit 0
fi

systemctl enable --now ez-alarm.timer
echo "ez-alarm installed and timer started."
