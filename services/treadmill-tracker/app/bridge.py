"""Sync TCP client for the ESP8266 CSAFE bridge.

Kept synchronous because the polling state machine is single-threaded
and blocking I/O with short timeouts is the simplest correct option.
"""
from __future__ import annotations

import socket
import time
from contextlib import suppress

from app.csafe import END, START, decode, encode

# CSAFE command bytes. Names from the 1.5 spec; semantics confirmed by
# bench against the actual Precor.
GETSTATUS = 0x80
GETSPEED = 0xA5
GETGRADE = 0xA8
GETHORIZONTAL = 0xA1
GETCALORIES = 0xA3
GETTWORK = 0xA0
GETHRCUR = 0xB0

ACTIVE_SWEEP = (GETSTATUS, GETSPEED, GETGRADE, GETHORIZONTAL,
                GETCALORIES, GETTWORK, GETHRCUR)


class BridgeError(Exception):
    pass


class Bridge:
    """One TCP connection + helpers. Reconnects on failure."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._sock: socket.socket | None = None

    def _connect(self) -> socket.socket:
        s = socket.create_connection((self.host, self.port), timeout=3)
        s.settimeout(0.15)
        return s

    def _ensure(self) -> socket.socket:
        if self._sock is None:
            self._sock = self._connect()
        return self._sock

    def close(self) -> None:
        if self._sock is not None:
            with suppress(OSError):
                self._sock.close()
            self._sock = None

    def _drain(self, s: socket.socket) -> None:
        s.settimeout(0.02)
        with suppress(socket.timeout, BlockingIOError):
            while s.recv(256):
                pass

    def _read_frame(self, s: socket.socket, timeout: float) -> bytes:
        deadline = time.monotonic() + timeout
        buf = bytearray()
        started = False
        s.settimeout(0.05)
        while time.monotonic() < deadline:
            try:
                chunk = s.recv(256)
            except TimeoutError:
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

    def query(self, cmd: int, *, timeout: float) -> bytes | None:
        """Send one CSAFE command, return decoded payload or None on miss."""
        try:
            s = self._ensure()
            self._drain(s)
            s.sendall(encode(bytes([cmd])))
            raw = self._read_frame(s, timeout=timeout)
        except OSError:
            self.close()
            return None
        if not raw or START not in raw or END not in raw:
            return None
        try:
            return decode(raw)
        except ValueError:
            return None
