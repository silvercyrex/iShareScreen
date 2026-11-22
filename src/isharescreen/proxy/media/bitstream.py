# Modified by the HPG fork (https://github.com/silvercyrex/iShareScreen), 2026-11.
"""HEVC bitstream primitives — what the rest of the package needs.

A NAL unit's payload is RBSP — Raw Byte Sequence Payload — with 0x03
emulation-prevention bytes inserted whenever three zero bytes would
otherwise appear. Parsers strip those before reading bit-level fields.
Inside RBSP, the multi-bit fields we care about are exp-Golomb-coded
(`ue(v)`).
"""
from __future__ import annotations


def remove_emulation_prevention(data: bytes) -> bytes:
    """Strip the `00 00 03` → `00 00` emulation-prevention transform from RBSP."""
    # HPG fork: scan with bytes.find instead of a Python loop per byte (same
    # output; ~100x faster on a frame-sized buffer).
    data = bytes(data)
    i = data.find(b"\x00\x00\x03")
    if i < 0:
        return data
    out = bytearray()
    start = 0
    while i >= 0:
        out += data[start:i + 2]
        start = i + 3
        i = data.find(b"\x00\x00\x03", start)
    out += data[start:]
    return bytes(out)


class BitReader:
    """MSB-first bit reader over a bytes-like buffer."""

    __slots__ = ("_data", "_pos")

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    @property
    def pos(self) -> int:
        return self._pos

    def read1(self) -> int:
        byte = self._pos >> 3
        if byte >= len(self._data):
            return 0
        bit = 7 - (self._pos & 7)
        self._pos += 1
        return (self._data[byte] >> bit) & 1

    def read(self, n: int) -> int:
        """Read `n` bits unsigned MSB-first (HEVC `u(n)`)."""
        out = 0
        for _ in range(n):
            out = (out << 1) | self.read1()
        return out

    def read_ue(self) -> int:
        """Unsigned exp-Golomb code (HEVC `ue(v)`). Bounded loop so a
        malformed input can't spin us forever."""
        zeros = 0
        while self.read1() == 0 and zeros < 32:
            zeros += 1
        suffix = 0
        for i in range(zeros - 1, -1, -1):
            suffix |= self.read1() << i
        return (1 << zeros) - 1 + suffix

    def read_se(self) -> int:
        """Signed exp-Golomb (HEVC `se(v)`)."""
        code_num = self.read_ue()
        return (code_num + 1) // 2 if (code_num & 1) else -(code_num // 2)


__all__ = ["BitReader", "remove_emulation_prevention"]
