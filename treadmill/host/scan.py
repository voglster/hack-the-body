#!/usr/bin/env python3
"""Probe a CSAFE slave for which short commands it responds to.

Iterates one-byte command codes and prints the decoded response.
Skips state-changing commands (RESET/GOINUSE/etc.) — read-only sweep.
"""
from __future__ import annotations

import socket
import sys
import time

from csafe import encode, decode, START, END

HOST, PORT = "10.0.6.180", 8023

# Known CSAFE short command names (partial — Precor/Concept2 spec subset).
NAMES = {
    0x80: "GETSTATUS",
    0x89: "GETVERSION",
    0x91: "GETID",
    0x92: "GETUNITS",
    0x93: "GETSERIAL",
    0x94: "GETLIST",
    0x95: "GETUTILIZATION",
    0x96: "GETMOTORCURRENT",
    0x97: "GETODOMETER",
    0x98: "GETERRORCODE",
    0x99: "GETSERVICECODE",
    0x9A: "GETUSERCFG1",
    0x9B: "GETUSERCFG2",
    0xA0: "GETTWORK",
    0xA1: "GETHORIZONTAL",
    0xA2: "GETVERTICAL",
    0xA3: "GETCALORIES",
    0xA4: "GETPROGRAM",
    0xA5: "GETSPEED",
    0xA6: "GETPACE",
    0xA7: "GETCADENCE",
    0xA8: "GETGRADE",
    0xA9: "GETGEAR",
    0xAA: "GETUPLIST",
    0xAB: "GETUSERINFO",
    0xAC: "GETTORQUE",
    0xB0: "GETHRCUR",
    0xB1: "GETHRTZONE",
    0xB2: "GETMETS",
    0xB3: "GETPOWER",
    0xB4: "GETHRMAX",
    0xB5: "GETHRT",
    0xB7: "GETHR",
    0xBE: "GETUSERID",
    0xBF: "GETUSERWEIGHT",
}

# Don't poke these — they change machine state.
DANGEROUS = {0x81, 0x82, 0x83, 0x85, 0x86, 0x87, 0x88}


def read_frame(s: socket.socket, timeout: float = 0.7) -> bytes:
    deadline = time.time() + timeout
    buf = bytearray()
    started = False
    s.settimeout(0.2)
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


def probe(cmd: int) -> tuple[bytes, str]:
    with socket.create_connection((HOST, PORT), timeout=3) as s:
        s.sendall(encode(bytes([cmd])))
        raw = read_frame(s)
    if not raw:
        return b"", "(no response)"
    try:
        body = decode(raw)
        return body, body.hex(" ")
    except ValueError as e:
        return raw, f"raw={raw.hex(' ')} err={e}"


def main() -> int:
    codes = [c for c in range(0x80, 0x100) if c not in DANGEROUS]
    print(f"Scanning {len(codes)} short commands against {HOST}:{PORT}...\n")
    hits = []
    for c in codes:
        body, pretty = probe(c)
        name = NAMES.get(c, "")
        if body:
            tag = f"0x{c:02x} {name:<18}"
            print(f"  {tag} -> {pretty}")
            hits.append((c, name, pretty))
        time.sleep(0.05)
    print(f"\n{len(hits)} responding command(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
