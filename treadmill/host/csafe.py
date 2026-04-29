"""CSAFE framing helpers.

Standard CSAFE frame (Precor / Concept2 / etc.):

    0xF1 <payload> <checksum> 0xF2

Inside the payload, the bytes 0xF1, 0xF2, 0xF3 are escaped as
0xF3 followed by (byte XOR 0x80). The checksum is the XOR of all
unescaped payload bytes (and is itself escaped on the wire if it
collides with a control byte).
"""

from __future__ import annotations

START = 0xF1
END = 0xF2
ESC = 0xF3
_CONTROL = {START, END, ESC}


def _escape(buf: bytearray, b: int) -> None:
    if b in _CONTROL:
        buf.append(ESC)
        buf.append(b ^ 0x80)
    else:
        buf.append(b)


def encode(cmd: bytes) -> bytes:
    body = bytearray()
    cs = 0
    for b in cmd:
        cs ^= b
        _escape(body, b)
    _escape(body, cs)
    return bytes([START]) + bytes(body) + bytes([END])


def decode(frame: bytes) -> bytes:
    if len(frame) < 3 or frame[0] != START or frame[-1] != END:
        raise ValueError(f"bad framing: {frame.hex(' ')}")
    out = bytearray()
    i = 1
    while i < len(frame) - 1:
        b = frame[i]
        if b == ESC:
            i += 1
            out.append(frame[i] ^ 0x80)
        else:
            out.append(b)
        i += 1
    if not out:
        raise ValueError("empty payload")
    payload, cs = bytes(out[:-1]), out[-1]
    calc = 0
    for b in payload:
        calc ^= b
    if calc != cs:
        raise ValueError(f"bad checksum: got {cs:#04x}, calc {calc:#04x}")
    return payload
