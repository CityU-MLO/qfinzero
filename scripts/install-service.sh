#!/usr/bin/env bash
# Install QFinZero as a durable systemd *user* service so the unified hub stays
# up: it auto-restarts on crash/reboot, and systemd's cgroup management tears
# down every child (the 193xx services) cleanly on stop — no orphaned
# multi-port strays. This replaces the ad-hoc `nohup serve.sh` approach.
#
#   ./scripts/install-service.sh           # install, enable at boot, start now
#   ./scripts/install-service.sh uninstall # stop, disable, remove the unit
#
# After install, manage it with either:
#   systemctl --user {status|restart|stop|start} qfinzero-hub
#   ./scripts/restart.sh {restart|stop|start|status}   # auto-delegates to it
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
UNIT="qfinzero-hub.service"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_PATH="$UNIT_DIR/$UNIT"

if ! systemctl --user is-system-running >/dev/null 2>&1; then
  echo "systemd --user is not available here. Falling back is fine: use"
  echo "  ./scripts/restart.sh   (ad-hoc nohup supervisor)"
  exit 1
fi

if [ "${1:-install}" = "uninstall" ]; then
  systemctl --user disable --now "$UNIT" 2>/dev/null
  rm -f "$UNIT_PATH"
  systemctl --user daemon-reload
  echo "Removed $UNIT."
  exit 0
fi

# Stop any ad-hoc hub / old strays first so the service starts on clean ports.
if [ -x "$ROOT_DIR/scripts/restart.sh" ]; then
  QFZ_SKIP_SYSTEMD=1 "$ROOT_DIR/scripts/restart.sh" stop || true
fi

mkdir -p "$UNIT_DIR"
cat >"$UNIT_PATH" <<UNIT
[Unit]
Description=QFinZero unified hub (web UI + REST + MCP + supervised 193xx services)
After=network-online.target
Wants=network-online.target
# Don't give up if it flaps a few times on boot.
StartLimitIntervalSec=120
StartLimitBurst=10

[Service]
Type=simple
WorkingDirectory=$ROOT_DIR
ExecStart=$ROOT_DIR/scripts/serve.sh
Restart=always
RestartSec=3
TimeoutStopSec=25
Environment=PYTHONUNBUFFERED=1
# Default KillMode=control-group tears down the hub AND every child service on
# stop/restart, so no 193xx port is ever left orphaned.

[Install]
WantedBy=default.target
UNIT

echo "Wrote $UNIT_PATH"
systemctl --user daemon-reload

# Survive logout / reboot (best-effort; may need polkit/root on some hosts).
if loginctl enable-linger "$(id -un)" 2>/dev/null; then
  echo "Enabled linger (service runs across logout/reboot)."
else
  echo "NOTE: could not enable linger automatically. To survive reboot without an"
  echo "      active login, run once:  sudo loginctl enable-linger $(id -un)"
fi

systemctl --user enable --now "$UNIT"

echo "Waiting for the hub to become healthy…"
for i in $(seq 1 60); do
  sleep 2
  if curl -s -m3 "http://127.0.0.1:${QFZ_SERVER_PORT:-19777}/health" >/dev/null 2>&1; then
    echo "Hub healthy after ~$((i * 2))s:"
    curl -s -m4 "http://127.0.0.1:${QFZ_SERVER_PORT:-19777}/health"; echo
    echo
    echo "Managed by systemd. Useful commands:"
    echo "  systemctl --user status qfinzero-hub"
    echo "  journalctl --user -u qfinzero-hub -f"
    echo "  ./scripts/restart.sh restart"
    exit 0
  fi
done
echo "Hub not healthy yet — check: journalctl --user -u qfinzero-hub -n 40"
exit 1
