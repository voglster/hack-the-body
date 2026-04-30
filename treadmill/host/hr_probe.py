#!/usr/bin/env python3
"""Poll every plausible HR command and dump raw bytes so we can
identify which one actually tracks the live chest-strap reading.

Walk for a minute while watching this — the row whose hex bytes
move with your effort is the real HR getter.
"""
from __future__ import annotations

import socket
import sys
import time

from csafe import encode, decode, START, END

HOST, PORT = "10.0.6.180", 8023

# Standard + Precor-extension candidates that might carry HR / pulse.
CANDIDATES = [
    (0xA6, "GETPACE"),
    (0xA7, "GETCADENCE"),
    (0xB0, "GETHRCUR"),
    (0xB4, "(was HRMax?)"),
    (0xB5, "GETHRT"),
    (0xB6, "?"),
    (0xB7, "GETHR"),
    (0xC0, "?"),
    (0xC1, "?"),
    (0xC2, "?"),
]


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


def drain(s):
    s.settimeout(0.02)
    try:
        while s.recv(256):
            pass
    except (socket.timeout, BlockingIOError):
        pass


def query(s, cmd):
    drain(s)
    s.sendall(encode(bytes([cmd])))
    raw = read_frame(s)
    if not raw:
        return b""
    try:
        return decode(raw)
    except ValueError:
        return raw


def main() -> int:
    sock = socket.create_connection((HOST, PORT), timeout=3)
    sock.settimeout(0.15)
    print(f"Polling HR candidates on {HOST}:{PORT}. Ctrl-C to quit.\n")
    print(f"{'cmd':<6} {'name':<14} payload (hex)            interpretations")
    print("-" * 90)
    try:
        while True:
            sys.stdout.write("\x1b[H\x1b[J")  # clear
            print(f"Polling HR candidates on {HOST}:{PORT}.   "
                  f"{time.strftime('%H:%M:%S')}\n")
            print(f"{'cmd':<6} {'name':<14} {'payload (hex)':<28} "
                  f"interpretations")
            print("-" * 90)
            for cmd, name in CANDIDATES:
                p = query(sock, cmd)
                hexs = p.hex(" ") if p else "(no response)"
                # If wrapped: status, cmd, len, data...
                interp = ""
                if len(p) >= 3 and p[1] == cmd:
                    n = p[2]
                    data = p[3:3 + n]
                    if len(data) >= 1:
                        interp = (
                            f"data={data.hex(' ')}  "
                            f"d[0]={data[0]} d[-1]={data[-1]}"
                        )
                        if len(data) >= 2:
                            interp += (
                                f"  le16={int.from_bytes(data[:2], 'little')}"
                            )
                print(f"0x{cmd:02x}   {name:<14} {hexs:<28} {interp}")
                time.sleep(0.05)
            time.sleep(0.4)
    except KeyboardInterrupt:
        return 0
    finally:
        sock.close()


if __name__ == "__main__":
    sys.exit(main())
