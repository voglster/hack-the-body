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

2. **Disable screen blanking in `~/.xsessionrc`:**

   ```bash
   cat > ~/.xsessionrc <<'EOF'
   xset s off
   xset -dpms
   xset s noblank
   unclutter -idle 0 &
   matchbox-window-manager -use_titlebar no &
   chromium-browser --kiosk --incognito \
     --noerrdialogs --disable-infobars \
     --disable-session-crashed-bubble \
     http://<SERVER>:8080/kiosk
   EOF
   ```

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
