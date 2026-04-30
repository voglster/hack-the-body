#!/usr/bin/env python3
"""Live treadmill dashboard — polls CSAFE getters and renders a
one-screen view that refreshes a few times a second.

Usage: live.py [--host H] [--port P] [--rate HZ]
"""
from __future__ import annotations

import argparse
import socket
import sys
import time
from dataclasses import dataclass

from csafe import encode, decode, START, END

DEFAULT_HOST = "10.0.6.180"
DEFAULT_PORT = 8023

# Commands we poll. Names are best-guess from the spec; the layout
# below interprets the response bytes per Precor's observed shape.
GETSTATUS      = 0x80
GETID          = 0x91
GETSERVICECODE = 0x99
GETTWORK       = 0xA0
GETHORIZONTAL  = 0xA1
GETCALORIES    = 0xA3
GETSPEED       = 0xA5
GETGRADE       = 0xA8
GETPOWER       = 0xB3
GETHR_PRECOR   = 0xB0   # GETHRCUR — live HR from chest strap

POLL_CMDS = [
    GETSTATUS, GETSPEED, GETGRADE, GETHORIZONTAL,
    GETCALORIES, GETPOWER, GETHR_PRECOR, GETTWORK, GETSERVICECODE,
]

STATE_NAMES = {
    0x00: "Error", 0x01: "Ready", 0x02: "Idle", 0x03: "HaveID",
    0x05: "InUse", 0x06: "Pause", 0x07: "Finished", 0x08: "Manual",
    0x09: "Manual/Local",
}


@dataclass
class Sample:
    state: int = 0
    speed_mph: float = 0.0     # mph
    grade_pct: float = 0.0     # %
    distance: int = 0          # raw counter
    calories: int = 0
    power: int = 0             # watts
    hr: int = 0                # bpm
    twork: int = 0             # total work seconds
    service: int = 0
    raw: dict[int, bytes] = None
    err: str | None = None


def read_frame(s: socket.socket, timeout: float = 0.6) -> bytes:
    deadline = time.time() + timeout
    buf = bytearray()
    started = False
    s.settimeout(0.15)
    while time.time() < deadline:
        try:
            chunk = s.recv(256)
        except socket.timeout:
            if started and END in buf:
                break
            continue
        if not chunk:
            break
        buf += chunk
        if not started and START in buf:
            buf = buf[buf.index(START):]
            started = True
        if started and END in buf[1:]:
            return bytes(buf[: buf.index(END, 1) + 1])
    return bytes(buf)


def _drain(s: socket.socket) -> None:
    """Discard any buffered bytes from prior frames."""
    s.settimeout(0.02)
    try:
        while True:
            if not s.recv(256):
                return
    except (socket.timeout, BlockingIOError):
        return


def query(s: socket.socket, cmd: int) -> bytes:
    """Send a single short command on an existing socket, return decoded
    payload (or b'')."""
    _drain(s)
    s.sendall(encode(bytes([cmd])))
    raw = read_frame(s)
    if not raw:
        return b""
    try:
        return decode(raw)
    except ValueError:
        return b""


def _data_after_header(payload: bytes, cmd: int) -> bytes:
    """Strip the leading <status><cmd><len> header. Returns the
    inner data bytes (or empty on shape mismatch)."""
    if len(payload) >= 3 and payload[1] == cmd:
        n = payload[2]
        return payload[3:3 + n]
    return b""


def collect(sock: socket.socket) -> Sample:
    s = Sample(raw={})
    try:
        for cmd in POLL_CMDS:
            p = query(sock, cmd)
            s.raw[cmd] = p
            if cmd == GETSTATUS:
                # Bottom nibble holds the state code; upper bits are
                # frame number / version flags that toggle between polls.
                s.state = (p[0] & 0x0F) if p else 0
                continue
            data = _data_after_header(p, cmd)
            if not data:
                continue
            if cmd == GETSPEED and len(data) >= 2:
                # 0.1 mph resolution, little-endian
                s.speed_mph = int.from_bytes(data[:2], "little") / 10.0
            elif cmd == GETGRADE and len(data) >= 2:
                # Precor reports grade with 0.01 % resolution
                s.grade_pct = int.from_bytes(data[:2], "little") / 100.0
            elif cmd == GETHORIZONTAL and len(data) >= 2:
                s.distance = int.from_bytes(data[:2], "little")
            elif cmd == GETCALORIES and len(data) >= 2:
                s.calories = int.from_bytes(data[:2], "little")
            elif cmd == GETPOWER and len(data) >= 2:
                s.power = int.from_bytes(data[:2], "little")
            elif cmd == GETHR_PRECOR and len(data) >= 1:
                # observed last byte of 3-byte payload is bpm
                s.hr = data[-1]
            elif cmd == GETTWORK and len(data) >= 2:
                s.twork = int.from_bytes(data[:2], "little")
            elif cmd == GETSERVICECODE and len(data) >= 2:
                s.service = int.from_bytes(data[:2], "little")
    except OSError as e:
        s.err = str(e)
    return s


CLEAR = "\x1b[2J\x1b[H"
DIM = "\x1b[2m"
BOLD = "\x1b[1m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
RED = "\x1b[31m"
CYAN = "\x1b[36m"
RESET = "\x1b[0m"


def bar(value: float, lo: float, hi: float, width: int = 24, color: str = CYAN) -> str:
    frac = 0.0 if hi <= lo else max(0.0, min(1.0, (value - lo) / (hi - lo)))
    fill = int(round(frac * width))
    return f"{color}{'█' * fill}{DIM}{'·' * (width - fill)}{RESET}"


def fmt_secs(n: int) -> str:
    h, rem = divmod(n, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


def render(s: Sample, host: str, hz: float, started_at: float, peak: dict[str, float]) -> str:
    state_name = STATE_NAMES.get(s.state, f"0x{s.state:02x}")
    state_color = GREEN if s.state in (0x01, 0x05) else YELLOW

    lines = []
    lines.append(f"{CLEAR}{BOLD}🏃  Hack-the-Body Treadmill Live{RESET}   "
                 f"{DIM}{host} · {hz:.1f} Hz · "
                 f"uptime {fmt_secs(int(time.time()-started_at))}{RESET}")
    lines.append("")

    lines.append(f"  {BOLD}State{RESET}      {state_color}{state_name}{RESET}  "
                 f"{DIM}(0x{s.state:02x}){RESET}")
    lines.append("")

    # Speed gauge: 0–8 mph
    lines.append(f"  {BOLD}Speed{RESET}      {GREEN}{s.speed_mph:5.1f} mph{RESET}  "
                 f"{bar(s.speed_mph, 0, 8, color=GREEN)}  "
                 f"{DIM}peak {peak['speed']:.1f}{RESET}")

    # Grade gauge: 0–15%
    lines.append(f"  {BOLD}Grade{RESET}      {YELLOW}{s.grade_pct:5.1f} %{RESET}    "
                 f"{bar(s.grade_pct, 0, 15, color=YELLOW)}  "
                 f"{DIM}peak {peak['grade']:.1f}{RESET}")

    # HR gauge: 50–190 bpm
    hr_color = RED if s.hr >= 150 else (YELLOW if s.hr >= 120 else GREEN)
    lines.append(f"  {BOLD}HR{RESET}         {hr_color}{s.hr:5d} bpm{RESET}  "
                 f"{bar(s.hr, 50, 190, color=hr_color)}  "
                 f"{DIM}peak {int(peak['hr'])}{RESET}")
    lines.append("")

    # Counters
    lines.append(f"  {BOLD}Distance{RESET}   {s.distance:6d}        "
                 f"{BOLD}Calories{RESET}  {s.calories:6d}        "
                 f"{BOLD}Power{RESET}  {s.power:4d} W")
    lines.append(f"  {BOLD}T-Work{RESET}     {fmt_secs(s.twork):>6}        "
                 f"{BOLD}Service#{RESET}  0x{s.service:04x}")
    lines.append("")

    if s.err:
        lines.append(f"  {RED}error: {s.err}{RESET}")
    else:
        lines.append(f"  {DIM}Ctrl-C to exit{RESET}")

    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default=DEFAULT_HOST)
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--rate", type=float, default=2.0,
                   help="poll rate in Hz (default 2)")
    args = p.parse_args()

    period = 1.0 / args.rate
    started = time.time()
    peak = {"speed": 0.0, "grade": 0.0, "hr": 0.0}

    sock = socket.create_connection((args.host, args.port), timeout=3)
    sock.settimeout(0.15)
    try:
        while True:
            t0 = time.time()
            s = collect(sock)
            peak["speed"] = max(peak["speed"], s.speed_mph)
            peak["grade"] = max(peak["grade"], s.grade_pct)
            peak["hr"] = max(peak["hr"], s.hr)
            sys.stdout.write(render(s, args.host, args.rate, started, peak))
            sys.stdout.flush()
            elapsed = time.time() - t0
            if elapsed < period:
                time.sleep(period - elapsed)
    except KeyboardInterrupt:
        sys.stdout.write("\n")
        return 0
    finally:
        try:
            sock.close()
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
