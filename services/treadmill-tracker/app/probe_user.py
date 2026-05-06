"""One-off CSAFE probe for user-profile detection.

Sweeps a configurable list of CSAFE commands against the bridge and
prints the decoded payload (or "no response") for each. Use this to
discover whether the Precor's CSAFE responses actually distinguish
between user profiles.

Suggested experiment:
  1. Start treadmill, select profile A, step on so it's awake.
  2. Run this script; copy output.
  3. Stop, switch to profile B, repeat.
  4. Diff.

If any command's payload changes between profiles, that's the
discriminator. If everything is identical, this Precor doesn't expose
profile info via CSAFE and we need a different approach.

Usage:
  cd services/treadmill-tracker
  .venv/bin/python -m app.probe_user --host 10.0.6.180
  .venv/bin/python -m app.probe_user --host 10.0.6.180 --watch  # repeats
  .venv/bin/python -m app.probe_user --host 10.0.6.180 --cmds 0x1A,0x86,0x16
"""
from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime

from app.bridge import (
    ACTIVE_SWEEP,
    GETSTATUS,
    Bridge,
)

# Candidate CSAFE commands worth probing for user-profile signal.
# Names are from the CSAFE 1.5 spec; semantics on Precor are unknown
# until we bench-test.
PROBE_CMDS: dict[int, str] = {
    GETSTATUS: "GETSTATUS (baseline)",
    0x1A: "GETUSERINFO  — typically weight/age/gender for active user",
    0x86: "GETUSERCFG   — vendor user config",
    0x16: "GETPROGRAMID — current program/preset",
    0x10: "GETID        — hardware/serial ID (sanity check, should be stable)",
    0x11: "GETSERIAL    — serial number (sanity)",
    0x12: "GETVERSION   — firmware version (sanity)",
    0x6A: "GETCALCFG    — calibration / user weight",
    0x60: "GETUSERWEIGHT",
}


def _probe_once(bridge: Bridge, cmds: list[int]) -> None:
    ts = datetime.now(tz=UTC).astimezone().strftime("%H:%M:%S")
    print(f"\n=== probe @ {ts} ===")
    for cmd in cmds:
        label = PROBE_CMDS.get(cmd, f"0x{cmd:02X}")
        payload = bridge.query(cmd, timeout=0.5)
        if payload is None:
            print(f"  0x{cmd:02X} {label}\n      <no response>")
        else:
            hex_dump = payload.hex(" ")
            print(f"  0x{cmd:02X} {label}\n      {hex_dump}  ({len(payload)} bytes)")


def _parse_cmd_list(s: str) -> list[int]:
    out = []
    for raw in s.split(","):
        part = raw.strip()
        if not part:
            continue
        out.append(int(part, 16) if part.lower().startswith("0x") else int(part))
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="10.0.6.180", help="bridge IP")
    p.add_argument("--port", type=int, default=8023)
    p.add_argument("--cmds", default=None,
                   help="comma-separated CSAFE command bytes (hex or int). "
                        "default: PROBE_CMDS plus the active-sweep cmds")
    p.add_argument("--watch", action="store_true",
                   help="loop forever, probing every --interval seconds")
    p.add_argument("--interval", type=float, default=3.0)
    args = p.parse_args()

    if args.cmds:
        cmds = _parse_cmd_list(args.cmds)
    else:
        # Default: probe candidates plus the normal active sweep so we
        # can see the deck is awake while we're at it.
        cmds = list(dict.fromkeys([*PROBE_CMDS.keys(), *ACTIVE_SWEEP]))

    print(f"probing {args.host}:{args.port}")
    print(f"commands: {', '.join(f'0x{c:02X}' for c in cmds)}")
    bridge = Bridge(args.host, args.port)
    try:
        _probe_once(bridge, cmds)
        if args.watch:
            while True:
                time.sleep(args.interval)
                _probe_once(bridge, cmds)
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        bridge.close()


if __name__ == "__main__":
    main()
