"""Round-trip + spec-fixture checks for csafe.encode/decode."""

import pytest

from csafe import encode, decode, START, END, ESC


def test_simple_roundtrip():
    cmd = bytes([0x80])
    frame = encode(cmd)
    assert frame[0] == START and frame[-1] == END
    assert decode(frame) == cmd


def test_escapes_control_bytes_in_payload():
    # 0xF1 in the payload must be encoded as 0xF3 0x71
    cmd = bytes([0xF1])
    frame = encode(cmd)
    assert ESC in frame
    assert decode(frame) == cmd


def test_multibyte_payload():
    cmd = bytes([0xA0, 0x01, 0x02])
    assert decode(encode(cmd)) == cmd


def test_bad_checksum_rejected():
    frame = bytearray(encode(bytes([0x80])))
    # Flip a bit in the checksum byte (second-to-last).
    frame[-2] ^= 0x01
    with pytest.raises(ValueError):
        decode(bytes(frame))


def test_bad_framing_rejected():
    with pytest.raises(ValueError):
        decode(b"\x00\x80\x80\xF2")
