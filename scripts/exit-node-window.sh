#!/usr/bin/env bash
# Open a 5-minute window where this machine egresses through a Tailscale exit
# node, then revert no matter what — even on Ctrl-C, error, or unexpected exit.
#
# Run in its own terminal:
#   sudo ./scripts/exit-node-window.sh jims-pixel-9-pro
#
# Optional second arg overrides duration in seconds:
#   sudo ./scripts/exit-node-window.sh jims-pixel-9-pro 600

set -u

EXIT_NODE="${1:-jims-pixel-9-pro}"
DURATION="${2:-300}"

revert() {
  echo
  echo "[$(date +%H:%M:%S)] reverting: tailscale set --exit-node="
  /usr/bin/tailscale set --exit-node= 2>&1 || true
  echo "[$(date +%H:%M:%S)] reverted. WAN IP now:"
  /usr/bin/curl -sS --max-time 5 https://api.ipify.org || echo "(could not reach ipify; check connectivity)"
  echo
}

# Always revert on any exit path: normal end, error, signal.
trap revert EXIT INT TERM HUP

if [[ $EUID -ne 0 ]]; then
  echo "Must run with sudo (tailscale set requires root)." >&2
  exit 1
fi

echo "[$(date +%H:%M:%S)] BEFORE: WAN IP is"
/usr/bin/curl -sS --max-time 5 https://api.ipify.org || true
echo

echo "[$(date +%H:%M:%S)] engaging exit node: $EXIT_NODE  (duration: ${DURATION}s)"
/usr/bin/tailscale set --exit-node="$EXIT_NODE"

# Give Tailscale a moment to switch routes.
sleep 3

echo "[$(date +%H:%M:%S)] DURING: WAN IP is"
/usr/bin/curl -sS --max-time 5 https://api.ipify.org || echo "(could not reach ipify yet)"
echo

echo "[$(date +%H:%M:%S)] window open. Will revert in ${DURATION}s."
echo "       (Ctrl-C anytime to revert immediately.)"
sleep "$DURATION"
