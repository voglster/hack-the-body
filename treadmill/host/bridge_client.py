#!/usr/bin/env python3
"""Talk to the ESP8266 bridge.

Host argument is optional — if omitted, the bridge is auto-discovered
on the LAN via mDNS (`treadmill-bridge.local`, falling back to
avahi-browse for `_csafe-bridge._tcp`).

    bridge_client.py raw [host]
    bridge_client.py send <hex...> [--host H]
    bridge_client.py status [host]
    bridge_client.py find
"""

from __future__ import annotations

import argparse
import ipaddress
import shutil
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from csafe import encode, decode, START, END

DEFAULT_PORT = 8023
DEFAULT_HOSTNAME = "treadmill-bridge"


def _local_subnet() -> ipaddress.IPv4Network | None:
    """Best-effort guess of the host's primary /24."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.2)
            s.connect(("8.8.8.8", 53))
            ip = s.getsockname()[0]
        return ipaddress.IPv4Network(f"{ip}/24", strict=False)
    except OSError:
        return None


def _scan_subnet(port: int = DEFAULT_PORT, timeout: float = 0.3) -> str | None:
    """Scan the local /24 for an open TCP port. Returns first hit."""
    net = _local_subnet()
    if net is None:
        return None

    def probe(ip: str) -> str | None:
        try:
            with socket.create_connection((ip, port), timeout=timeout):
                return ip
        except OSError:
            return None

    with ThreadPoolExecutor(max_workers=64) as ex:
        futures = {ex.submit(probe, str(ip)): str(ip) for ip in net.hosts()}
        for fut in as_completed(futures):
            if (ip := fut.result()):
                return ip
    return None


def _resolve(hostname: str = DEFAULT_HOSTNAME,
             port: int = DEFAULT_PORT) -> str | None:
    """Return an IP for the bridge, or None. Order: mDNS .local,
    avahi-browse, TCP scan of the local /24."""
    try:
        infos = socket.getaddrinfo(f"{hostname}.local", None,
                                   type=socket.SOCK_STREAM)
        return infos[0][4][0]
    except socket.gaierror:
        pass

    if shutil.which("avahi-browse"):
        try:
            out = subprocess.check_output(
                ["avahi-browse", "-rtp", "_csafe-bridge._tcp"],
                text=True, timeout=5,
            )
            for line in out.splitlines():
                if line.startswith("="):
                    parts = line.split(";")
                    if len(parts) >= 8 and parts[7]:
                        return parts[7]
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass

    print("[no mDNS hit; scanning subnet for open :8023...]", file=sys.stderr)
    return _scan_subnet(port)


def _autohost(host: str | None) -> str:
    if host:
        return host
    print("[discovering bridge...]", file=sys.stderr)
    ip = _resolve()
    if not ip:
        print(
            "Could not auto-discover. Pass <host> explicitly, or check "
            "the serial log for the IP. (Linux may need `sudo apt install "
            "libnss-mdns avahi-utils`.)",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"[found bridge at {ip}]", file=sys.stderr)
    return ip


def _connect(host: str, port: int) -> socket.socket:
    s = socket.create_connection((host, port), timeout=5)
    s.settimeout(1.0)
    return s


def _read_frame(s: socket.socket, timeout: float = 2.0) -> bytes:
    deadline = time.time() + timeout
    buf = bytearray()
    started = False
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
            end_idx = buf.index(END, 1)
            return bytes(buf[: end_idx + 1])
    return bytes(buf)


def cmd_send(args: argparse.Namespace) -> int:
    host = _autohost(args.host)
    payload = bytes.fromhex(" ".join(args.hex))
    frame = encode(payload)
    print(f"-> {frame.hex(' ')}")
    with _connect(host, args.port) as s:
        s.sendall(frame)
        resp = _read_frame(s, timeout=args.timeout)
    if not resp:
        print("<- (no response)")
        return 1
    print(f"<- {resp.hex(' ')}")
    try:
        body = decode(resp)
        print(f"   payload: {body.hex(' ')}")
    except ValueError as e:
        print(f"   decode error: {e}")
        return 2
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    args.hex = ["80"]
    return cmd_send(args)


def cmd_find(args: argparse.Namespace) -> int:
    ip = _resolve(args.hostname)
    if ip:
        print(f"{args.hostname}.local -> {ip}:{args.port}")
        return 0
    print("Not found. Is the bridge powered and on WiFi?")
    return 1


def cmd_raw(args: argparse.Namespace) -> int:
    host = _autohost(args.host)
    s = _connect(host, args.port)
    s.settimeout(0.2)
    print(f"[connected to {host}:{args.port}; Ctrl-C to quit]")
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                data = s.recv(256)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data:
                break
            sys.stdout.write(data.hex(" ") + " ")
            sys.stdout.flush()

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                data = bytes.fromhex(line.replace(" ", ""))
            except ValueError:
                data = line.encode()
            s.sendall(data)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        s.close()
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("send", help="send hex bytes as a CSAFE frame")
    sp.add_argument("hex", nargs="+", help="hex bytes, e.g. 80 or 'a0 01'")
    sp.add_argument("--host", default=None)
    sp.add_argument("--port", type=int, default=DEFAULT_PORT)
    sp.add_argument("--timeout", type=float, default=2.0)
    sp.set_defaults(func=cmd_send)

    st = sub.add_parser("status", help="send CSAFE_GETSTATUS (0x80)")
    st.add_argument("host", nargs="?", default=None)
    st.add_argument("--port", type=int, default=DEFAULT_PORT)
    st.add_argument("--timeout", type=float, default=2.0)
    st.set_defaults(func=cmd_status)

    rw = sub.add_parser("raw", help="raw bidirectional console")
    rw.add_argument("host", nargs="?", default=None)
    rw.add_argument("--port", type=int, default=DEFAULT_PORT)
    rw.set_defaults(func=cmd_raw)

    fd = sub.add_parser("find", help="discover the bridge via mDNS")
    fd.add_argument("--hostname", default="treadmill-bridge")
    fd.add_argument("--port", type=int, default=DEFAULT_PORT)
    fd.set_defaults(func=cmd_find)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
