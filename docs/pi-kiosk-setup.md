# Pi Kiosk Setup

Turn an older Raspberry Pi + office monitor into a live Hack the Body dashboard.

## Requirements

- Raspberry Pi (3B+ or newer) with HDMI to the monitor
- Raspberry Pi OS (32- or 64-bit) Lite or Desktop
- Network access to the server running `docker compose up` (replace `<SERVER>` below)

## Steps

1. **Install Chromium and matchbox-window-manager (if Lite):**

   ```bash
   sudo apt update
   sudo apt install -y --no-install-recommends \
     xserver-xorg x11-xserver-utils xinit chromium-browser \
     matchbox-window-manager unclutter
   ```

2. **Disable screen blanking + set display in `~/.xsessionrc`:**

   ```bash
   cat > ~/.xsessionrc <<'EOF'
   xset s off
   xset -dpms
   xset s noblank

   # Force native resolution + rotation. Without an explicit --mode, X
   # falls back to its 320x200 minimum after a cold boot and chromium
   # renders into a postage-stamp window. Adjust the mode to match the
   # monitor (xrandr lists supported modes). Drop --rotate if landscape.
   xrandr --output HDMI-1 --mode 2560x1440 --rotate left 2>/dev/null \
     || xrandr --output HDMI-A-1 --mode 2560x1440 --rotate left 2>/dev/null \
     || true

   unclutter -idle 0 &
   matchbox-window-manager -use_titlebar no &
   chromium --kiosk --remote-debugging-port=9222 --remote-allow-origins=* \
     --noerrdialogs --disable-infobars \
     --disable-session-crashed-bubble \
     http://<SERVER>:8080/kiosk
   EOF
   ```

   Notes:
   - `chromium` (not `chromium-browser`) on Debian 13 / Pi OS Trixie.
   - No `--incognito`: persists the API-key in localStorage so the
     AuthGate password only needs to be entered once. The API now
     sends `Cache-Control: no-store` on `index.html`, so deploys still
     pick up new bundles on reload.
   - `--remote-debugging-port=9222` lets the pi-agent (and humans on
     the LAN) drive Chromium via CDP — used by the brightness /
     refresh MQTT controls.

3. **Autostart X on boot:** edit `~/.bash_profile`:

   ```bash
   if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
     startx
   fi
   ```

4. **Enable auto-login to tty1:** `sudo raspi-config` → System Options → Boot / Auto Login → Console Autologin.

5. **Reboot:** `sudo reboot`. The Pi should boot directly into the kiosk page.

## Updating

When the web service redeploys, just refresh (or power-cycle the Pi). No update steps on the Pi itself.

## Troubleshooting

- **Blank screen:** check `~/.xsession-errors`.
- **Chromium shows "connection refused":** confirm the server is reachable from the Pi (`curl http://<SERVER>:8080`).
- **Cursor stays on screen:** confirm `unclutter` installed; increase `-idle` if it flickers.
