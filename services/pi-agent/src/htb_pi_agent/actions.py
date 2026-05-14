"""Side-effect actions on the Pi: monitor power, brightness, browser controls, reboot.

Each function is sync and quick (<1s) except `navigate`/`type_text` which may block on CDP.
The MQTT loop calls them from its callback thread; we keep them simple and exception-tolerant
because partial failure (e.g. ddcutil fails) should not kill the agent.
"""
import io
import logging
import os
import re
import subprocess
from typing import Optional

import httpx
from PIL import Image

from .config import Settings

log = logging.getLogger(__name__)


def _x_env(s: Settings) -> dict[str, str]:
    env = os.environ.copy()
    env["DISPLAY"] = s.display
    env["XAUTHORITY"] = s.xauthority
    return env


def _run(cmd: list[str], *, env: dict | None = None, timeout: float = 10) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        log.warning("timeout running %s", cmd)
        return 124, "", "timeout"
    except FileNotFoundError as e:
        log.warning("missing binary: %s", e)
        return 127, "", str(e)


# --- Monitor power ---------------------------------------------------------

def init_display(s: Settings) -> None:
    """Enable DPMS with zero timeouts so power state is readable but never auto-blanks."""
    env = _x_env(s)
    _run(["xset", "+dpms"], env=env)
    _run(["xset", "s", "off"], env=env)
    _run(["xset", "s", "0", "0"], env=env)
    _run(["xset", "dpms", "0", "0", "0"], env=env)


def set_power(s: Settings, on: bool) -> None:
    cmd = ["xset", "dpms", "force", "on" if on else "off"]
    _run(cmd, env=_x_env(s))


def get_power(s: Settings) -> Optional[bool]:
    """Returns True if monitor is on, False if off/standby/suspend, None if unknown."""
    rc, out, _ = _run(["xset", "q"], env=_x_env(s))
    if rc != 0:
        return None
    m = re.search(r"Monitor is\s+(\S+)", out)
    if not m:
        return None
    return m.group(1).strip().lower() == "on"


# --- Brightness (DDC/CI) ---------------------------------------------------

def set_brightness(_s: Settings, value: int) -> None:
    value = max(0, min(100, int(value)))
    _run(["ddcutil", "--sleep-multiplier=2", "setvcp", "10", str(value)], timeout=15)


def get_brightness(_s: Settings) -> Optional[int]:
    rc, out, _ = _run(["ddcutil", "--sleep-multiplier=2", "getvcp", "10"], timeout=15)
    if rc != 0:
        return None
    m = re.search(r"current value =\s*(\d+)", out)
    return int(m.group(1)) if m else None


# --- Browser controls via xdotool / Chrome DevTools Protocol ---------------

def _chromium_window_id(s: Settings) -> Optional[str]:
    rc, out, _ = _run(["xdotool", "search", "--name", "Chromium"], env=_x_env(s))
    if rc != 0 or not out.strip():
        rc, out, _ = _run(["xdotool", "search", "--class", "chromium"], env=_x_env(s))
        if rc != 0 or not out.strip():
            return None
    return out.strip().splitlines()[-1]


def reload_browser(s: Settings) -> None:
    """Reload via CDP by re-navigating to the current URL."""
    current = get_url(s)
    if current:
        navigate(s, current)
        return
    wid = _chromium_window_id(s)
    if wid:
        _run(["xdotool", "key", "--window", wid, "F5"], env=_x_env(s))


def type_text(s: Settings, text: str) -> None:
    if not text:
        return
    wid = _chromium_window_id(s)
    args = ["xdotool", "type", "--delay", "40"]
    if wid:
        args += ["--window", wid]
    args.append(text)
    _run(args, env=_x_env(s), timeout=30)


def navigate(s: Settings, url: str) -> bool:
    """Use Chrome DevTools Protocol to navigate. Returns True on success."""
    if not url:
        return False
    try:
        tabs = httpx.get(f"http://127.0.0.1:{s.chromium_cdp_port}/json", timeout=2).json()
    except Exception as e:
        log.warning("CDP unreachable, falling back to xdotool: %s", e)
        return _navigate_xdotool(s, url)
    page = next((t for t in tabs if t.get("type") == "page"), None)
    if not page:
        return _navigate_xdotool(s, url)
    try:
        httpx.put(
            f"http://127.0.0.1:{s.chromium_cdp_port}/json/new?{url}", timeout=2,
        )
        # Close old tabs so the new one is the only kiosk view
        for t in tabs:
            if t.get("type") == "page":
                httpx.get(f"http://127.0.0.1:{s.chromium_cdp_port}/json/close/{t['id']}", timeout=2)
        return True
    except Exception as e:
        log.warning("CDP navigate failed: %s", e)
        return _navigate_xdotool(s, url)


def _navigate_xdotool(s: Settings, url: str) -> bool:
    wid = _chromium_window_id(s)
    if not wid:
        return False
    _run(["xdotool", "key", "--window", wid, "ctrl+l"], env=_x_env(s))
    _run(["xdotool", "type", "--window", wid, "--delay", "20", url], env=_x_env(s))
    _run(["xdotool", "key", "--window", wid, "Return"], env=_x_env(s))
    return True


def get_url(s: Settings) -> Optional[str]:
    """Best-effort current page URL via CDP."""
    try:
        tabs = httpx.get(f"http://127.0.0.1:{s.chromium_cdp_port}/json", timeout=2).json()
    except Exception:
        return None
    page = next((t for t in tabs if t.get("type") == "page"), None)
    return page.get("url") if page else None


# --- Reboot ----------------------------------------------------------------

def reboot(_s: Settings) -> None:
    subprocess.Popen(["sudo", "reboot"])


# --- Screenshot ------------------------------------------------------------

def screenshot_jpeg(s: Settings) -> Optional[bytes]:
    """Capture screen, downscale, return JPEG bytes. None on failure."""
    rc, _out, err = _run(
        ["scrot", "-o", "-q", "90", "/tmp/htb-screen.png"], env=_x_env(s), timeout=10
    )
    if rc != 0:
        log.debug("scrot failed: %s", err)
        return None
    try:
        with Image.open("/tmp/htb-screen.png") as im:
            im = im.convert("RGB")
            w, h = im.size
            if w > s.preview_max_width:
                ratio = s.preview_max_width / w
                im = im.resize((s.preview_max_width, int(h * ratio)))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=s.preview_jpeg_quality, optimize=True)
            return buf.getvalue()
    except Exception as e:
        log.warning("screenshot encode failed: %s", e)
        return None
