"""
3270 Screen Buffer Model + host data stream processing

The buffer works the way a real 3270 (and x3270, Common/ctlr.c) does: a field attribute lives IN the buffer at
its position, so a field is the run from one attribute to the next. (The old model appended a Field object per
SF and never removed them, so a re-written screen kept stale fields, and a modified field could be sent twice.)
Each cell keeps its EBCDIC byte, so reads send what the host wrote - nulls suppressed - not a lossy
ASCII round trip.

Commands: W / EW / EWA / EAU / WSF and the reads the host can ask for (RB / RM / RMA / NOP), with
WCC handling (reset MDT, keyboard restore), x3270's order semantics (SBA range checks, RA with a full wrap
and GE, EUA, PT, MF, SFE, SA, GE), SSCP-LU writes, and the Read Partition / Erase-Reset / Set Reply Mode /
Outbound 3270DS structured fields.

Copyright (C) 2026 Garland Glessner <gglessner@gmail.com>
License: GPL-3.0 (see LICENSE)
"""

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)
try:
    from .ebcdic import ebcdic_to_ascii, char_to_ebcdic, ge_to_char
    from .orders import (
        ORDERS, COMMANDS, WCC, SF, PDS, AID_NO, AID_QREPLY, AIDS, ATTR_TYPES, COLORS, HIGHLIGHTS,
        FORMAT_CONTROLS, ADDR_TABLE, decode_buffer_address, encode_buffer_address, get_default_field_color,
    )
    from .query import build_query_reply
except ImportError:
    from ebcdic import ebcdic_to_ascii, char_to_ebcdic, ge_to_char
    from orders import (
        ORDERS, COMMANDS, WCC, SF, PDS, AID_NO, AID_QREPLY, AIDS, ATTR_TYPES, COLORS, HIGHLIGHTS,
        FORMAT_CONTROLS, ADDR_TABLE, decode_buffer_address, encode_buffer_address, get_default_field_color,
    )
    from query import build_query_reply

FA_PROTECTED = 0x20
FA_NUMERIC = 0x10
FA_DISPLAY = 0x0C
FA_INTENSIFY = 0x08
FA_HIDDEN = 0x0C
FA_MDT = 0x01
FA_MASK = 0x3F

AID_SYSREQ = 0xF0
_SHORT_READ_AIDS = frozenset([AIDS['PA1'], AIDS['PA2'], AIDS['PA3'], AIDS['CLEAR']])


class _Abort(Exception):
    """A host write error: stop the write here (x3270 ABORT_WRITE); the caller answers PDS_BAD_ADDR."""


@dataclass
class Cell:
    """Single screen cell. `ebc`/`is_field_start`/`fa`/`fg`/`bg`/`gr`/`ge` are the 3270 state; the rest are
    derived for display by ScreenBuffer._refresh()."""
    char: str = ' '
    ebc: int = 0x00                  # EBCDIC byte (0x00 = null)
    is_field_start: bool = False
    fa: int = 0                      # field attribute (field-start cells), bit 0x01 = MDT
    ge: bool = False                 # graphic-escape character
    fg: int = 0                      # host colour code (0 = default): SFE colour on an attribute, SA on a char
    bg: int = 0
    gr: int = 0                      # host highlight code (0 = default)
    is_protected: bool = False
    is_numeric: bool = False
    is_hidden: bool = False
    is_intensified: bool = False
    is_modified: bool = False
    color: str = 'green'
    highlight: str = 'normal'
    background: str = 'default'


@dataclass
class Field:
    """A field, derived from the buffer (see ScreenBuffer.fields)."""
    start_pos: int
    attr_byte: int
    is_protected: bool = False
    is_numeric: bool = False
    is_hidden: bool = False
    is_intensified: bool = False
    is_modified: bool = False
    color: str = 'green'
    highlight: str = 'normal'


class ScreenBuffer:
    """24x80 3270 screen buffer"""

    ROWS = 24
    COLS = 80
    SIZE = ROWS * COLS  # 1920

    def __init__(self):
        self.cells: List[Cell] = [Cell() for _ in range(self.SIZE)]
        self.cursor_pos: int = 0
        self.buffer_addr: int = 0          # where the next SSCP-LU write lands
        self.sscp_start: int = 0           # where SSCP-LU input starts (x3270 sscp_start)
        self.aid: int = AID_NO             # the last AID sent; the reply AID for a host Read
        self.reply_mode: int = SF.SRM_FIELD
        self.keyboard_locked: bool = False     # set when an AID is sent; the host's WCC restore clears it
        self.sscp_mode: bool = False           # TN3270E SSCP-LU (set by the session)
        self.alarm: bool = False
        self.tn3270e: bool = False         # kept for compatibility
        self.current_color: str = 'green'
        self.current_highlight: str = 'normal'
        self.current_background: str = 'default'

    # ----- basics ------------------------------------------------------------------------------------------------

    def clear(self):
        """Clear the screen (erase): nulls everywhere, no fields, cursor home."""
        self.cells = [Cell() for _ in range(self.SIZE)]
        self.cursor_pos = 0
        self.buffer_addr = 0
        self.sscp_start = 0
        self.current_color = 'green'
        self.current_highlight = 'normal'
        self.current_background = 'default'

    def get_row_col(self, pos: int) -> tuple:
        """Convert position to row, col (0-based)"""
        return pos // self.COLS, pos % self.COLS

    def get_pos(self, row: int, col: int) -> int:
        """Convert row, col to position"""
        return row * self.COLS + col

    @property
    def formatted(self) -> bool:
        return any(c.is_field_start for c in self.cells)

    def is_unformatted(self) -> bool:
        """Check if screen is unformatted (no fields)"""
        return not self.formatted

    def field_attr_addr(self, pos: int) -> Optional[int]:
        """The address of the field attribute governing `pos` (searching backwards, wrapping), or None."""
        p = pos
        for _ in range(self.SIZE):
            if self.cells[p].is_field_start:
                return p
            p = (p - 1) % self.SIZE
        return None

    def _fa_of(self, pos: int) -> int:
        a = self.field_attr_addr(pos)
        return self.cells[a].fa if a is not None else 0

    def is_protected_at(self, pos: int) -> bool:
        """Can't type at `pos`: a field attribute position, or inside a protected field."""
        cell = self.cells[pos]
        if cell.is_field_start:
            return True
        return bool(self._fa_of(pos) & FA_PROTECTED) if self.formatted else False

    # ----- field derivation / display ----------------------------------------------------------------------------

    @property
    def fields(self) -> List[Field]:
        """The fields on the screen, in buffer order (derived from the attributes in the buffer)."""
        out = []
        for i, c in enumerate(self.cells):
            if c.is_field_start:
                out.append(self._field_from(i))
        return out

    def _field_from(self, i: int) -> Field:
        c = self.cells[i]
        fa = c.fa
        return Field(start_pos=i, attr_byte=fa, is_protected=bool(fa & FA_PROTECTED),
                     is_numeric=bool(fa & FA_NUMERIC), is_hidden=(fa & FA_DISPLAY) == FA_HIDDEN,
                     is_intensified=(fa & FA_DISPLAY) == FA_INTENSIFY, is_modified=bool(fa & FA_MDT),
                     color=self._field_color(c), highlight=HIGHLIGHTS.get(c.gr, 'normal'))

    @staticmethod
    def _field_color(fa_cell: Cell) -> str:
        if fa_cell.fg and fa_cell.fg in COLORS and COLORS[fa_cell.fg] != 'default':
            return COLORS[fa_cell.fg]
        return get_default_field_color(fa_cell.fa)

    def _refresh(self):
        """Recompute the display properties of every cell from the buffer."""
        formatted = self.formatted
        if not formatted:
            for c in self.cells:
                c.is_protected = c.is_numeric = c.is_hidden = c.is_intensified = c.is_modified = False
                c.char = ge_to_char(c.ebc) if c.ge else ebcdic_to_ascii(c.ebc)
                c.color = COLORS.get(c.fg, 'green') if c.fg else 'green'
                if c.color == 'default':
                    c.color = 'green'
                c.highlight = HIGHLIGHTS.get(c.gr, 'normal') if c.gr else 'normal'
                c.background = COLORS.get(c.bg, 'default') if c.bg else 'default'
            return
        # start from the attribute that governs position 0
        start = self.field_attr_addr(self.SIZE - 1)
        fa_cell = self.cells[start]
        p = start
        for _ in range(self.SIZE):
            c = self.cells[p]
            if c.is_field_start:
                fa_cell = c
                c.char = ' '
            else:
                c.char = ge_to_char(c.ebc) if c.ge else ebcdic_to_ascii(c.ebc)
            fa = fa_cell.fa
            c.is_protected = bool(fa & FA_PROTECTED)
            c.is_numeric = bool(fa & FA_NUMERIC)
            c.is_hidden = (fa & FA_DISPLAY) == FA_HIDDEN
            c.is_intensified = (fa & FA_DISPLAY) == FA_INTENSIFY
            c.is_modified = bool(fa & FA_MDT)
            ch_color = COLORS.get(c.fg) if (c.fg and not c.is_field_start) else None
            c.color = ch_color if ch_color and ch_color != 'default' else self._field_color(fa_cell)
            gr = c.gr if (c.gr and not c.is_field_start) else fa_cell.gr
            c.highlight = HIGHLIGHTS.get(gr, 'normal') if gr else 'normal'
            bg = c.bg if (c.bg and not c.is_field_start) else fa_cell.bg
            c.background = COLORS.get(bg, 'default') if bg else 'default'
            p = (p + 1) % self.SIZE

    # ----- buffer primitives (x3270 ctlr_add / ctlr_add_fa) -------------------------------------------------------

    def _put(self, pos: int, ebc: int, ge: bool = False, fg: int = 0, bg: int = 0, gr: int = 0):
        """Store a character; writing over a field attribute removes that field."""
        c = self.cells[pos]
        c.ebc, c.ge, c.fg, c.bg, c.gr = ebc, ge, fg, bg, gr
        c.is_field_start, c.fa = False, 0

    def _put_fa(self, pos: int, fa: int, fg: int = 0, bg: int = 0, gr: int = 0):
        c = self.cells[pos]
        c.ebc, c.ge = 0x00, False
        c.is_field_start, c.fa = True, fa & FA_MASK
        c.fg, c.bg, c.gr = fg, bg, gr

    def _inc(self, pos: int) -> int:
        return (pos + 1) % self.SIZE

    # ----- host data stream ----------------------------------------------------------------------------------------

    def process_data(self, data: bytes, tn3270e_mode: bool = None):
        """Compatibility entry point: `data` is one record, optionally with a 5-byte TN3270E header
        (tn3270e_mode=True) and a trailing IAC EOR. Returns (pds, [replies]) like process_ds()."""
        if len(data) >= 2 and data[-2] == 0xFF and data[-1] == 0xEF:
            data = data[:-2]
        data = data.replace(b'\xff\xff', b'\xff')
        if tn3270e_mode:
            data = data[5:]
        return self.process_ds(data)

    def process_ds(self, buf: bytes) -> Tuple[int, List[bytes]]:
        """Process one host 3270 data stream record (no telnet framing, no TN3270E header) -> (pds, replies).
        `replies` are inbound records (AID-first) the host asked for - a Read or a query reply - for the caller
        to send, in order."""
        if not buf:
            return PDS.OKAY_NO_OUTPUT, []
        cmd = buf[0]
        replies: List[bytes] = []
        if cmd in COMMANDS.EAU:
            self.erase_all_unprotected()
            rv = PDS.OKAY_NO_OUTPUT
        elif cmd in COMMANDS.EWA or cmd in COMMANDS.EW:
            self.clear()
            rv = self._write(buf, erase=True)
        elif cmd in COMMANDS.W:
            rv = self._write(buf, erase=False)
        elif cmd in COMMANDS.RB:
            replies.append(self.read_buffer(self.aid))
            rv = PDS.OKAY_OUTPUT
        elif cmd in COMMANDS.RM:
            replies.append(self.read_modified(self.aid, read_all=False))
            rv = PDS.OKAY_OUTPUT
        elif cmd in COMMANDS.RMA:
            replies.append(self.read_modified(self.aid, read_all=True))
            rv = PDS.OKAY_OUTPUT
        elif cmd in COMMANDS.WSF:
            rv = self._write_structured_field(buf, replies)
        elif cmd in COMMANDS.NOP:
            rv = PDS.OKAY_NO_OUTPUT
        else:
            logger.warning(f"Unknown 3270 command {cmd:#04x}")
            rv = PDS.BAD_CMD
        self._refresh()
        return rv, replies

    def _write(self, buf: bytes, erase: bool) -> int:
        """W / EW / EWA (x3270 ctlr_write, single-byte character sets)."""
        if len(buf) < 2:
            return PDS.BAD_ADDR
        wcc = buf[1]
        if erase and (wcc & WCC.RESET):
            self.reply_mode = SF.SRM_FIELD
        if wcc & WCC.RESET_MDT:
            for c in self.cells:
                if c.is_field_start:
                    c.fa &= ~FA_MDT
        ba = self.cursor_pos
        d_fg = d_bg = d_gr = 0
        insert_cursor = None
        last_cmd, last_zpt = True, False
        rv = PDS.OKAY_NO_OUTPUT
        i, n = 2, len(buf)

        def need(k: int):
            if i + k >= n:
                raise _Abort("record too short")

        def addr_at(j: int) -> int:
            a = decode_buffer_address(buf[j], buf[j + 1])
            if a >= self.SIZE:
                raise _Abort(f"buffer address {a} > maximum {self.SIZE - 1}")
            return a

        try:
            while i < n:
                c = buf[i]
                if c == ORDERS.SF:
                    need(1)
                    self._put_fa(ba, buf[i + 1])
                    ba = self._inc(ba)
                    i += 2
                    last_cmd, last_zpt = True, False
                elif c == ORDERS.SBA:
                    need(2)
                    ba = addr_at(i + 1)
                    i += 3
                    last_cmd, last_zpt = True, False
                elif c == ORDERS.IC:
                    insert_cursor = ba
                    i += 1
                    last_cmd, last_zpt = True, False
                elif c == ORDERS.PT:
                    i += 1
                    cell = self.cells[ba]
                    if cell.is_field_start and not (cell.fa & FA_PROTECTED):
                        ba = self._inc(ba)
                        last_cmd, last_zpt = True, False
                        continue
                    nxt = self._next_unprotected(ba)
                    if nxt < ba:
                        nxt = 0
                    if not last_cmd or last_zpt:
                        while ba != nxt and not self.cells[ba].is_field_start:
                            self._put(ba, 0x00)
                            ba = self._inc(ba)
                        last_zpt = (nxt == 0)
                    else:
                        last_zpt = False
                    ba = nxt
                    last_cmd = True
                elif c == ORDERS.RA:
                    need(3)
                    end = addr_at(i + 1)
                    ch = buf[i + 3]
                    ge = False
                    i += 4
                    if ch == ORDERS.GE:
                        if i >= n:
                            raise _Abort("missing RA GE character")
                        ch, ge = buf[i], True
                        i += 1
                    while True:              # do/while: equal addresses fill the whole buffer
                        self._put(ba, ch, ge, d_fg, d_bg, d_gr)
                        ba = self._inc(ba)
                        if ba == end:
                            break
                    last_cmd, last_zpt = True, False
                elif c == ORDERS.EUA:
                    need(2)
                    end = addr_at(i + 1)
                    i += 3
                    cur_fa = self._fa_of(ba)
                    while True:
                        cell = self.cells[ba]
                        if cell.is_field_start:
                            cur_fa = cell.fa
                        elif not (cur_fa & FA_PROTECTED):
                            self._put(ba, 0x00)
                        ba = self._inc(ba)
                        if ba == end:
                            break
                    last_cmd, last_zpt = True, False
                elif c == ORDERS.GE:
                    need(1)
                    self._put(ba, buf[i + 1], True, d_fg, d_bg, d_gr)
                    ba = self._inc(ba)
                    i += 2
                    last_cmd, last_zpt = False, False
                elif c == ORDERS.MF:
                    need(1)
                    na = buf[i + 1]
                    pairs = buf[i + 2:i + 2 + 2 * na]
                    if len(pairs) < 2 * na:
                        raise _Abort("missing MF attribute")
                    i += 2 + 2 * na
                    cell = self.cells[ba]
                    if cell.is_field_start:
                        for k in range(0, len(pairs), 2):
                            t, v = pairs[k], pairs[k + 1]
                            if t == ATTR_TYPES.T3270:
                                cell.fa = v & FA_MASK
                            elif t == ATTR_TYPES.FOREGROUND_COLOR:
                                cell.fg = v
                            elif t == ATTR_TYPES.BACKGROUND_COLOR:
                                cell.bg = v
                            elif t == ATTR_TYPES.HIGHLIGHTING:
                                cell.gr = v
                        ba = self._inc(ba)
                    last_cmd, last_zpt = True, False
                elif c == ORDERS.SFE:
                    need(1)
                    na = buf[i + 1]
                    pairs = buf[i + 2:i + 2 + 2 * na]
                    if len(pairs) < 2 * na:
                        raise _Abort("missing SFE attribute")
                    i += 2 + 2 * na
                    fa, fg, bg, gr = 0, 0, 0, 0
                    for k in range(0, len(pairs), 2):
                        t, v = pairs[k], pairs[k + 1]
                        if t == ATTR_TYPES.T3270:
                            fa = v
                        elif t == ATTR_TYPES.FOREGROUND_COLOR:
                            fg = v
                        elif t == ATTR_TYPES.BACKGROUND_COLOR:
                            bg = v
                        elif t == ATTR_TYPES.HIGHLIGHTING:
                            gr = v
                    self._put_fa(ba, fa, fg, bg, gr)
                    ba = self._inc(ba)
                    last_cmd, last_zpt = True, False
                elif c == ORDERS.SA:
                    need(2)
                    t, v = buf[i + 1], buf[i + 2]
                    if t == ATTR_TYPES.FOREGROUND_COLOR:
                        d_fg = v
                    elif t == ATTR_TYPES.BACKGROUND_COLOR:
                        d_bg = v
                    elif t == ATTR_TYPES.HIGHLIGHTING:
                        d_gr = v
                    elif t == ATTR_TYPES.ALL:
                        d_fg = d_bg = d_gr = 0
                    i += 3
                    last_cmd, last_zpt = True, False
                elif c in FORMAT_CONTROLS or c in (0x0E, 0x0F):
                    self._put(ba, c, False, d_fg, d_bg, d_gr)
                    ba = self._inc(ba)
                    i += 1
                    last_cmd, last_zpt = (c != 0x00), False
                elif c <= 0x3F:
                    i += 1                      # unsupported order: skipped, not displayed (x3270)
                    last_cmd, last_zpt = True, False
                else:
                    self._put(ba, c, False, d_fg, d_bg, d_gr)
                    ba = self._inc(ba)
                    i += 1
                    last_cmd, last_zpt = False, False
        except _Abort as e:
            logger.warning(f"Host write error: {e}")
            rv = PDS.BAD_ADDR
        self.buffer_addr = ba
        if insert_cursor is not None:
            self.cursor_pos = insert_cursor
        if wcc & WCC.KEYBOARD_RESTORE:
            self.aid = AID_NO
            self.keyboard_locked = False
        if wcc & WCC.SOUND_ALARM:
            self.alarm = True
        return rv

    def erase_all_unprotected(self):
        """EAU (x3270 ctlr_erase_all_unprotected): null every unprotected field, reset its MDT, cursor to the
        first unprotected position, unlock."""
        if self.formatted:
            # walk the fields from the first attribute, as x3270 does; the cursor lands on the first position
            # after the first unprotected attribute met in that order
            start = next(i for i, c in enumerate(self.cells) if c.is_field_start)
            p, cursor = start, None
            while True:
                fa_cell = self.cells[p]
                unprot = not (fa_cell.fa & FA_PROTECTED)
                if unprot:
                    fa_cell.fa &= ~FA_MDT
                p = self._inc(p)
                if unprot and cursor is None:
                    cursor = p
                while not self.cells[p].is_field_start:
                    if unprot:
                        self._put(p, 0x00)
                    p = self._inc(p)
                if p == start:
                    break
            self.cursor_pos = cursor if cursor is not None else 0
        else:
            self.clear()
        self.aid = AID_NO
        self.keyboard_locked = False
        self._refresh()

    def _erase_unprotected(self):
        """Compatibility alias."""
        self.erase_all_unprotected()

    # ----- structured fields ---------------------------------------------------------------------------------------

    def _write_structured_field(self, buf: bytes, replies: List[bytes]) -> int:
        """WSF (x3270 write_structured_field): each field is dispatched on its ID, in order; a malformed length
        stops the run but keeps what the earlier fields did (their output has already been produced)."""
        data, i = buf[1:], 0
        rv, bad = PDS.OKAY_NO_OUTPUT, False
        while i < len(data):
            if len(data) - i < 2:
                bad = True
                break
            ln = (data[i] << 8) | data[i + 1]
            if ln == 0:
                ln = len(data) - i
            if ln < 3 or i + ln > len(data):
                logger.warning(f"WSF: structured field length {ln} invalid at offset {i}")
                bad = True
                break
            sf = data[i:i + ln]
            sfid = sf[2]
            i += ln
            if sfid == SF.READ_PART:
                r = self._sf_read_part(sf, replies)
            elif sfid == SF.ERASE_RESET:
                r = PDS.BAD_CMD
                if len(sf) == 4 and sf[3] in (SF.ER_DEFAULT, SF.ER_ALT):
                    self.clear()
                    r = PDS.OKAY_NO_OUTPUT
            elif sfid == SF.SET_REPLY_MODE:
                r = PDS.BAD_CMD
                if len(sf) >= 5 and sf[3] == 0x00 and sf[4] in (SF.SRM_FIELD, SF.SRM_XFIELD, SF.SRM_CHAR):
                    self.reply_mode = sf[4]
                    r = PDS.OKAY_NO_OUTPUT
            elif sfid == SF.OUTBOUND_DS:
                r = self._sf_outbound_ds(sf)
            else:
                logger.info(f"WSF: unsupported structured field {sfid:#04x}")
                r = PDS.BAD_CMD
            if r < 0:
                bad = True
            else:
                rv |= r
        return PDS.BAD_CMD if (bad and not rv) else rv

    def _sf_read_part(self, sf: bytes, replies: List[bytes]) -> int:
        if len(sf) < 5:
            return PDS.BAD_CMD
        partition, rtype = sf[3], sf[4]
        if rtype == SF.RP_QUERY:
            if partition != 0xFF:
                return PDS.BAD_CMD
            replies.append(build_query_reply(None, self.ROWS, self.COLS))
        elif rtype == SF.RP_QLIST:
            if partition != 0xFF or len(sf) < 6:
                return PDS.BAD_CMD
            if sf[5] == SF.RPQ_LIST:
                replies.append(build_query_reply(sf[6:], self.ROWS, self.COLS))
            elif sf[5] in (SF.RPQ_EQUIV, SF.RPQ_ALL):
                replies.append(build_query_reply(None, self.ROWS, self.COLS))
            else:
                return PDS.BAD_CMD
        elif rtype in (0x6E, 0xF2, 0xF6):          # SNA RMA / RB / RM
            if partition != 0x00:
                return PDS.BAD_CMD
            if rtype == 0xF2:
                replies.append(self.read_buffer(AID_QREPLY))
            else:
                replies.append(self.read_modified(AID_QREPLY, read_all=(rtype == 0x6E)))
        else:
            return PDS.BAD_CMD
        return PDS.OKAY_OUTPUT

    def _sf_outbound_ds(self, sf: bytes) -> int:
        if len(sf) < 5 or sf[3] != 0x00:
            return PDS.BAD_CMD
        cmd = sf[4]
        if cmd == 0xF1:
            return self._write(sf[4:], erase=False) if len(sf) > 5 else PDS.OKAY_NO_OUTPUT
        if cmd in (0xF5, 0x7E):
            self.clear()
            return self._write(sf[4:], erase=True) if len(sf) > 5 else PDS.OKAY_NO_OUTPUT
        if cmd == 0x6F:
            self.erase_all_unprotected()
            return PDS.OKAY_NO_OUTPUT
        return PDS.BAD_CMD

    # ----- SSCP-LU mode --------------------------------------------------------------------------------------------

    def write_sscp_lu(self, buf: bytes):
        """SSCP-LU data (the VTAM USS / logon screen in TN3270E with BIND-IMAGE): unformatted text with NL,
        written where the last one stopped (x3270 ctlr_write_sscp_lu). SF/SBA/IC from badly-behaved hosts are
        filtered; the cursor ends after the text, which is where input will start."""
        ba = self.buffer_addr
        i, n = 0, len(buf)

        def scroll_if_wrapped(addr: int) -> int:
            if addr == 0:
                self._scroll_up()
                return (self.ROWS - 1) * self.COLS
            return addr

        while i < n:
            c = buf[i]
            if c == 0x15:                           # NL: nulls to end of line, then the next line
                row = ba // self.COLS
                while ba // self.COLS == row:
                    self._put(ba, 0x00)
                    ba = (ba + 1) % self.SIZE
                    if ba == 0:
                        break
                ba = scroll_if_wrapped(ba)
                i += 1
            elif c == ORDERS.SF:
                self._put(ba, 0x40)
                ba = scroll_if_wrapped(self._inc(ba))
                i += 2
            elif c == ORDERS.IC:
                i += 1
            elif c == ORDERS.SBA:
                i += 3
            elif c == ORDERS.GE:
                if i + 1 < n:
                    ch = buf[i + 1] if buf[i + 1] > 0x40 else 0x40
                    self._put(ba, ch, True)
                    ba = scroll_if_wrapped(self._inc(ba))
                i += 2
            else:
                self._put(ba, c)
                ba = scroll_if_wrapped(self._inc(ba))
                i += 1
        self.buffer_addr = ba
        self.cursor_pos = ba
        self.sscp_start = ba
        self.aid = AID_NO
        self.keyboard_locked = False
        self._refresh()

    def _scroll_up(self):
        self.cells = self.cells[self.COLS:] + [Cell() for _ in range(self.COLS)]
        self.cursor_pos = max(0, self.cursor_pos - self.COLS)

    # ----- reads (inbound) -----------------------------------------------------------------------------------------

    def read_modified(self, aid: int, read_all: bool = False, sscp: bool = False) -> bytes:
        """The inbound record for an AID or a host Read Modified (x3270 ctlr_read_modified): AID + cursor, then
        SBA + data of every field whose MDT is set (nulls suppressed; an emptied field still gets its SBA).
        Short-read AIDs (PA1-3, CLEAR) send only the AID. SSCP-LU input is the bare text from where the host left
        the cursor - no AID, no cursor address, at most 255 bytes."""
        if sscp and aid != AIDS['ENTER']:
            return b''
        out = bytearray()
        send_data, short_read = True, False
        if aid == AID_SYSREQ:
            out += bytes([0x01, 0x6C, 0x61, 0x02])  # SOH % / STX: the test request
        else:
            if aid in _SHORT_READ_AIDS and not read_all:
                short_read, send_data = True, False
            if not sscp:
                out.append(aid)
                if short_read:
                    return bytes(out)
                out += encode_buffer_address(self.cursor_pos)
        if self.formatted and not sscp:
            first = next(i for i, c in enumerate(self.cells) if c.is_field_start)
            p = first
            while True:
                cell = self.cells[p]
                if cell.fa & FA_MDT:
                    p = self._inc(p)
                    out.append(ORDERS.SBA)
                    out += encode_buffer_address(p)
                    while not self.cells[p].is_field_start:
                        c = self.cells[p]
                        if send_data and c.ebc:
                            if c.ge:
                                out.append(ORDERS.GE)
                            out.append(c.ebc)
                        p = self._inc(p)
                else:
                    p = self._inc(p)
                    while not self.cells[p].is_field_start:
                        p = self._inc(p)
                if p == first:
                    break
        else:
            p = self.sscp_start if sscp else 0
            nbytes = 0
            while True:
                c = self.cells[p]
                if c.ebc and not c.is_field_start:
                    if c.ge:
                        out.append(ORDERS.GE)
                    out.append(c.ebc)
                    nbytes += 1
                p = self._inc(p)
                if sscp and (nbytes >= 255 or p == 0):
                    break
                if p == 0:
                    break
        return bytes(out)

    def read_buffer(self, aid: int) -> bytes:
        """The inbound record for a host Read Buffer (x3270 ctlr_read_buffer): AID, cursor, then every position -
        an attribute as SF (field reply mode) or SFE (extended), a character as itself, nulls included."""
        out = bytearray([aid])
        out += encode_buffer_address(self.cursor_pos)
        for c in self.cells:
            if c.is_field_start:
                code = ADDR_TABLE[c.fa & FA_MASK]
                if self.reply_mode == SF.SRM_FIELD:
                    out += bytes([ORDERS.SF, code])
                else:
                    pairs = [(ATTR_TYPES.T3270, code)]
                    if c.fg:
                        pairs.append((ATTR_TYPES.FOREGROUND_COLOR, c.fg))
                    if c.bg:
                        pairs.append((ATTR_TYPES.BACKGROUND_COLOR, c.bg))
                    if c.gr:
                        pairs.append((ATTR_TYPES.HIGHLIGHTING, c.gr | 0xF0))
                    out += bytes([ORDERS.SFE, len(pairs)])
                    for t, v in pairs:
                        out += bytes([t, v])
            else:
                if c.ge:
                    out.append(ORDERS.GE)
                out.append(c.ebc)
        return bytes(out)

    # ----- keyboard (local edits) ----------------------------------------------------------------------------------

    def type_char(self, pos: int, ch: str) -> bool:
        """Type one character at `pos`: refused on a protected position; otherwise stored as EBCDIC and the
        field's MDT is set. (Numeric fields are not enforced - x3270's default, numeric lock off.)"""
        if self.is_protected_at(pos):
            return False
        c = self.cells[pos]
        c.ebc, c.ge = char_to_ebcdic(ch), False
        c.fg = c.bg = c.gr = 0
        self.mark_field_modified(pos)
        self._refresh()
        return True

    def erase_char(self, pos: int) -> bool:
        """Null one position (Backspace/Delete): refused on protected positions; sets the MDT."""
        if self.is_protected_at(pos):
            return False
        c = self.cells[pos]
        c.ebc, c.ge = 0x00, False
        self.mark_field_modified(pos)
        self._refresh()
        return True

    def _field_end(self, pos: int) -> int:
        """The last position of the field containing `pos` (the one before the next attribute)."""
        p = pos
        for _ in range(self.SIZE):
            nxt = self._inc(p)
            if self.cells[nxt].is_field_start or nxt == pos:
                return p
            p = nxt
        return p

    def delete_char(self, pos: int) -> bool:
        """3270 Delete: remove the character at `pos`, shifting the rest of the field left; a null fills the end.
        Refused on protected positions; sets the MDT."""
        if self.is_protected_at(pos):
            return False
        end = self._field_end(pos) if self.formatted else self.SIZE - 1
        p = pos
        while p != end:
            nxt = self._inc(p)
            src = self.cells[nxt]
            dst = self.cells[p]
            dst.ebc, dst.ge, dst.fg, dst.bg, dst.gr = src.ebc, src.ge, src.fg, src.bg, src.gr
            p = nxt
        last = self.cells[end]
        last.ebc, last.ge, last.fg, last.bg, last.gr = 0x00, False, 0, 0, 0
        self.mark_field_modified(pos)
        self._refresh()
        return True

    def erase_eof(self, pos: int) -> bool:
        """Erase EOF: null from `pos` to the end of its field. Refused on protected positions; sets the MDT."""
        if self.is_protected_at(pos):
            return False
        end = self._field_end(pos) if self.formatted else self.SIZE - 1
        p = pos
        while True:
            self._put(p, 0x00)
            if p == end:
                break
            p = self._inc(p)
        self.mark_field_modified(pos)
        self._refresh()
        return True

    def mark_field_modified(self, pos: int):
        """Mark the field at position as modified (sets the MDT bit in its attribute)."""
        a = self.field_attr_addr(pos)
        if a is not None:
            self.cells[a].fa |= FA_MDT

    # ----- navigation ----------------------------------------------------------------------------------------------

    def _next_unprotected(self, pos: int) -> int:
        """The first position of the next unprotected field after `pos`, or 0 if there is none
        (x3270 next_unprotected - PT, Tab and Home all rely on the 0)."""
        p = self._inc(pos)
        for _ in range(self.SIZE):
            c = self.cells[p]
            if c.is_field_start and not (c.fa & FA_PROTECTED):
                nxt = self._inc(p)
                if not self.cells[nxt].is_field_start:
                    return nxt
            p = self._inc(p)
        return 0

    def _get_next_unprotected(self, pos: int) -> int:
        return self._next_unprotected(pos)

    def get_next_input_field(self, pos: int) -> int:
        """Get next input (unprotected) field position"""
        return self._next_unprotected(pos) if self.formatted else 0

    def get_prev_input_field(self, pos: int) -> int:
        """Get the start of the previous input field (or of the current one if pos is past its start)."""
        if not self.formatted:
            return 0
        p = (pos - 1) % self.SIZE
        for _ in range(self.SIZE):
            c = self.cells[p]
            if c.is_field_start and not (c.fa & FA_PROTECTED):
                start = self._inc(p)
                if start != pos and not self.cells[start].is_field_start:
                    return start
            p = (p - 1) % self.SIZE
        return pos

    def get_first_input_field(self) -> int:
        """Home (x3270 Home_action): the next unprotected field after the last position - so a field that
        wraps the end of the buffer counts from address 0; 0 if none (or the screen is unformatted)."""
        return self._next_unprotected(self.SIZE - 1) if self.formatted else 0

    def get_field_at(self, pos: int) -> Optional[Field]:
        """Get field containing position"""
        a = self.field_attr_addr(pos)
        return self._field_from(a) if a is not None else None

    # ----- compatibility helpers -----------------------------------------------------------------------------------

    def get_modified_fields(self) -> List[dict]:
        """Modified unprotected fields: [{'start_pos', 'data'}] (data = display text, nulls dropped)."""
        result = []
        for f in self.fields:
            if f.is_modified and not f.is_protected:
                start = self._inc(f.start_pos)
                p, chars = start, []
                while not self.cells[p].is_field_start:
                    if self.cells[p].ebc:
                        chars.append(ebcdic_to_ascii(self.cells[p].ebc))
                    p = self._inc(p)
                    if p == start:
                        break
                result.append({'start_pos': start, 'data': ''.join(chars)})
        return result

    def clear_modified_flags(self):
        """Reset every MDT. (A real 3270 never does this on its own after a read - the host resets MDTs with
        the WCC; this is kept only for callers that want it.)"""
        for c in self.cells:
            if c.is_field_start:
                c.fa &= ~FA_MDT
        self._refresh()

    def get_unformatted_data(self) -> str:
        """Get all screen data for unformatted screen"""
        return ''.join(ebcdic_to_ascii(c.ebc) for c in self.cells if c.ebc).rstrip()
