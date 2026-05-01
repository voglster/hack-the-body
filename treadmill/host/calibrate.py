#!/usr/bin/env python3
"""Calibrate the CSAFE GETHORIZONTAL counter against the Precor's
on-deck distance display.

Procedure:
  1. Run this. It reads and prints the current raw counter.
  2. Press Enter to mark START. Note the deck's mileage display.
  3. Walk until the deck shows +0.25 mi (or any known delta).
  4. Press Enter again to mark END. Tell it the miles you actually
     walked. It prints counts-per-mile and counts-per-km, and
     reports whether the spec's 0.001 km/count holds.
"""
from __future__ import annotations

import socket
import sys
import time

from csafe import encode, decode, START, END

HOST, PORT = "10.0.6.180", 8023
GETHORIZONTAL = 0xA1


def read_frame(s, timeout=0.6):
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


def read_horizontal(sock) -> int:
    drain(sock)
    sock.sendall(encode(bytes([GETHORIZONTAL])))
    raw = read_frame(sock)
    if not raw:
        raise RuntimeError("no response (treadmill off?)")
    p = decode(raw)
    if len(p) >= 3 and p[1] == GETHORIZONTAL:
        n = p[2]
        data = p[3:3 + n]
        if len(data) >= 2:
            return int.from_bytes(data[:2], "little")
    raise RuntimeError(f"bad payload: {p.hex(' ')}")


def main() -> int:
    sock = socket.create_connection((HOST, PORT), timeout=3)
    try:
        cur = read_horizontal(sock)
        print(f"Current raw counter: {cur}")
        print()
        input("Step on, get the belt running, then press Enter "
              "to mark START... ")
        start = read_horizontal(sock)
        t_start = time.time()
        print(f"START counter: {start}")
        print(f"Walk a known distance, then press Enter to mark END.")
        input()
        end = read_horizontal(sock)
        t_end = time.time()
        delta = end - start
        if delta < 0:
            delta += 65536  # u16 wrap
        print(f"END counter:   {end}   (delta {delta} over "
              f"{t_end - t_start:.0f}s)")
        miles_str = input("How many miles did the deck show "
                          "(e.g. 0.25): ").strip()
        miles = float(miles_str)
        km = miles * 1.609344
        cpm = delta / miles if miles > 0 else 0
        cpkm = delta / km if km > 0 else 0
        print()
        print(f"  Δcounts:        {delta}")
        print(f"  Distance:       {miles:.3f} mi   ({km:.3f} km)")
        print(f"  counts/mile:    {cpm:.1f}")
        print(f"  counts/km:      {cpkm:.1f}")
        print(f"  km/count:       {1/cpkm:.6f}")
        print()
        # CSAFE 1.5 spec: GETHORIZONTAL is 0.001 km per count
        spec_km_per_count = 0.001
        observed_km_per_count = 1 / cpkm
        ratio = observed_km_per_count / spec_km_per_count
        print(f"  spec says:      0.001 km/count")
        print(f"  observed/spec:  {ratio:.3f}x")
        if 0.95 <= ratio <= 1.05:
            print("  -> Precor follows the spec. Use km_per_count = 0.001.")
        else:
            print(f"  -> Precor deviates. Use km_per_count = "
                  f"{observed_km_per_count:.6f} (or "
                  f"mi_per_count = {1/cpm:.6f}).")
        return 0
    finally:
        sock.close()


if __name__ == "__main__":
    sys.exit(main())
