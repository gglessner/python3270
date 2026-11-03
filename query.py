"""
3270 Query Reply (the answer to a WSF Read Partition Query / Query List)

Built the way x3270 builds it (Common/sf.c): every structured field's length is COMPUTED, and the Summary lists
exactly the replies that are sent. The hand-assembled reply this replaces was malformed - Usable Area was 24
bytes under a 23-byte length, Color 40 under 38, the Summary promised DDM and RPQ Names replies that were never
sent, and the Implicit Partition claimed a 32x80 alternate screen the 1920-cell buffer can't hold - so a real
host parsing it field by field misread everything after Usable Area.

Copyright (C) 2026 Garland Glessner <gglessner@gmail.com>
License: GPL-3.0 (see LICENSE)
"""
from typing import Iterable, Optional

try:
    from .orders import AID_SF, SF
except ImportError:
    from orders import AID_SF, SF

SFID_QREPLY = 0x81

QR_SUMMARY = 0x80
QR_USABLE_AREA = 0x81
QR_ALPHA_PART = 0x84
QR_CHARSETS = 0x85
QR_COLOR = 0x86
QR_HIGHLIGHTING = 0x87
QR_REPLY_MODES = 0x88
QR_IMP_PART = 0xA6
QR_NULL = 0xFF

# 3279-2 physical constants (x3270 sf.c: Xr_3279_2 / Yr_3279_2 / SW_3279_2 / SH_3279_2)
XR_3279_2 = 0x000A02E5
YR_3279_2 = 0x0002006F
SW_3279_2 = 0x09
SH_3279_2 = 0x0C

# CGCSGID for character set 697, code page 037 (x3270's default for cp037)
CGCSGID_037 = 0x02B90025


def _u16(v: int) -> bytes:
    return bytes([(v >> 8) & 0xFF, v & 0xFF])


def _u32(v: int) -> bytes:
    return bytes([(v >> 24) & 0xFF, (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF])


def _usable_area(rows: int, cols: int) -> bytes:
    return (bytes([0x01, 0x00])             # 12/14-bit addressing; no special character features
            + _u16(cols) + _u16(rows)       # usable width, height
            + bytes([0x01])                 # units: millimetres
            + _u32(XR_3279_2) + _u32(YR_3279_2)
            + bytes([SW_3279_2, SH_3279_2])
            + _u16(rows * cols))            # buffer size


def _alpha_part(rows: int, cols: int) -> bytes:
    return bytes([0x00]) + _u16(rows * cols) + bytes([0x00])


def _charsets() -> bytes:
    return (bytes([0x82, 0x00,                 # flags: GE, CGCSGID present
                   SW_3279_2, SH_3279_2,       # default character cell width/height
                   0x00, 0x00, 0x00, 0x00,     # no load PS
                   0x07,                       # descriptor length
                   0x00, 0x10, 0x00])          # set 0: non-loadable, single-plane, single-byte; LCID 0
            + _u32(CGCSGID_037)
            + bytes([0x01, 0x00, 0xF1,         # set 1 (APL / line drawing): LCID 0xF1
                     0x03, 0xC3, 0x01, 0x36])) # CGCSGID: 3179-style APL2


def _color() -> bytes:
    out = bytearray([0x00, 16, 0x00, 0xF4])    # no options; 16 pairs; default -> green
    for c in range(0xF1, 0xF1 + 15):           # F1..FF each maps to itself
        out += bytes([c, c])
    return bytes(out)


def _highlighting() -> bytes:
    return bytes([5, 0x00, 0xF0, 0xF1, 0xF1, 0xF2, 0xF2, 0xF4, 0xF4, 0xF8, 0xF8])


def _reply_modes() -> bytes:
    # Field and extended-field reply modes only: character mode (SA orders inserted into reads) is not
    # implemented, so it is not advertised.
    return bytes([SF.SRM_FIELD, SF.SRM_XFIELD])


def _imp_part(rows: int, cols: int) -> bytes:
    # default size AND alternate size are the real buffer: a model 2 has no bigger alternate screen
    return bytes([0x00, 0x00, 0x0B, 0x01, 0x00]) + _u16(cols) + _u16(rows) + _u16(cols) + _u16(rows)


# The replies we support, in the order x3270 sends them (Summary first).
SUPPORTED = (QR_SUMMARY, QR_USABLE_AREA, QR_ALPHA_PART, QR_CHARSETS, QR_COLOR, QR_HIGHLIGHTING,
             QR_REPLY_MODES, QR_IMP_PART)


def _body(code: int, rows: int, cols: int) -> bytes:
    if code == QR_SUMMARY:
        return bytes(SUPPORTED)
    if code == QR_USABLE_AREA:
        return _usable_area(rows, cols)
    if code == QR_ALPHA_PART:
        return _alpha_part(rows, cols)
    if code == QR_CHARSETS:
        return _charsets()
    if code == QR_COLOR:
        return _color()
    if code == QR_HIGHLIGHTING:
        return _highlighting()
    if code == QR_REPLY_MODES:
        return _reply_modes()
    if code == QR_IMP_PART:
        return _imp_part(rows, cols)
    return b''                                  # QR_NULL


def query_reply_sf(code: int, rows: int = 24, cols: int = 80) -> bytes:
    """One Query Reply structured field: LL LL 0x81 <code> <body>, LL = its own total length."""
    body = _body(code, rows, cols)
    return _u16(4 + len(body)) + bytes([SFID_QREPLY, code]) + body


def build_query_reply(codes: Optional[Iterable[int]] = None, rows: int = 24, cols: int = 80) -> bytes:
    """The inbound record (no telnet framing): AID 0x88 then the structured fields. `codes` = the replies a
    Query List asked for (only supported ones are sent; none -> a Null reply); None = all of them (Query)."""
    if codes is None:
        wanted = list(SUPPORTED)
    else:
        asked = set(codes)
        wanted = [c for c in SUPPORTED if c in asked]
        if not wanted:
            wanted = [QR_NULL]
    return bytes([AID_SF]) + b''.join(query_reply_sf(c, rows, cols) for c in wanted)


def parse_structured_fields(data: bytes) -> list:
    """Split a run of structured fields into (id, field-bytes) pairs; raises ValueError on a bad length.
    (Used to check our own replies, and by the WSF handler.)"""
    out, i = [], 0
    while i < len(data):
        if len(data) - i < 3:
            raise ValueError("structured field too short")
        ln = (data[i] << 8) | data[i + 1]
        if ln == 0:
            ln = len(data) - i
        if ln < 3 or i + ln > len(data):
            raise ValueError(f"structured field length {ln} invalid at offset {i}")
        out.append((data[i + 2], data[i:i + ln]))
        i += ln
    return out
