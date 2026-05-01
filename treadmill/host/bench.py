#!/usr/bin/env python3
"""Benchmark CSAFE command latency to size B vs D polling strategies."""
from __future__ import annotations

import socket
import statistics
import sys
import time

from csafe import encode, decode, START, END

HOST, PORT = "10.0.6.180", 8023
N = 30

CMDS = {
    0x80: "GETSTATUS",
    0xA5: "GETSPEED",
    0xA8: "GETGRADE",
    0xA1: "GETHORIZONTAL",
    0xA3: "GETCALORIES",
    0xA0: "GETTWORK",
    0xB0: "GETHRCUR",
}

B_SET = list(CMDS.keys())            # 7 cmds, full sweep each tick
D_FAST = [0x80, 0xA5, 0xB0]          # state, speed, HR
D_SLOW = [0xA8, 0xA1, 0xA3, 0xA0]    # grade, dist, cal, twork


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


def time_cmd(s, cmd):
    drain(s)
    t0 = time.perf_counter()
    s.sendall(encode(bytes([cmd])))
    raw = read_frame(s)
    dt = time.perf_counter() - t0
    ok = bool(raw)
    try:
        decode(raw)
    except (ValueError, IndexError):
        pass
    return dt, ok


def stats(ms):
    return (
        statistics.mean(ms),
        statistics.median(ms),
        sorted(ms)[int(len(ms) * 0.95) - 1] if len(ms) >= 2 else ms[0],
        max(ms),
    )


def main() -> int:
    sock = socket.create_connection((HOST, PORT), timeout=3)
    sock.settimeout(0.15)
    print(f"Benchmarking {HOST}:{PORT}, {N} samples per command\n")

    per_cmd = {}
    for cmd, name in CMDS.items():
        # warm up
        time_cmd(sock, cmd)
        latencies = []
        misses = 0
        for _ in range(N):
            dt, ok = time_cmd(sock, cmd)
            if ok:
                latencies.append(dt * 1000.0)
            else:
                misses += 1
        if latencies:
            per_cmd[cmd] = (name, latencies, misses)

    print(f"{'cmd':<6} {'name':<16} {'mean':>7} {'p50':>7} {'p95':>7} {'max':>7}  miss")
    print("-" * 68)
    for cmd, (name, lats, misses) in per_cmd.items():
        m, p50, p95, mx = stats(lats)
        print(f"0x{cmd:02x}   {name:<16} {m:6.1f}ms {p50:6.1f}ms {p95:6.1f}ms {mx:6.1f}ms  {misses}")

    print()

    # Full sweep timing — N iterations
    sweep_lats = []
    for _ in range(N):
        t0 = time.perf_counter()
        for cmd in B_SET:
            time_cmd(sock, cmd)
        sweep_lats.append((time.perf_counter() - t0) * 1000.0)
    bm, bp50, bp95, bmx = stats(sweep_lats)
    print(f"Strategy B (full {len(B_SET)}-cmd sweep): "
          f"mean {bm:.0f}ms (p95 {bp95:.0f}ms) → "
          f"max {1000.0/bm:.2f} Hz sustainable")

    # Strategy D simulated: fast tick = D_FAST every cycle, D_SLOW round-robin
    fast_lats = []
    for _ in range(N):
        t0 = time.perf_counter()
        for cmd in D_FAST:
            time_cmd(sock, cmd)
        fast_lats.append((time.perf_counter() - t0) * 1000.0)
    fm, fp50, fp95, fmx = stats(fast_lats)
    print(f"Strategy D (fast tick = {len(D_FAST)} cmds): "
          f"mean {fm:.0f}ms (p95 {fp95:.0f}ms) → "
          f"max {1000.0/fm:.2f} Hz sustainable")
    print(f"  + slow ring of {len(D_SLOW)} cmds adds "
          f"~{sum(stats(per_cmd[c][1])[0] for c in D_SLOW):.0f}ms total, "
          f"distributed 1-per-fast-tick")

    sock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
