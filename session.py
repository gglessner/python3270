"""
TN3270 Session - glue between the connection (telnet / TN3270E) and the screen (3270 data stream)

Runs on whichever thread owns the screen (the GUI thread in python3270): handle_record() processes a host record,
answers it as RFC 2355 requires (positive / negative response), and sends any reply the host asked for (Read
Buffer, Read Modified, query reply). send_aid() builds the inbound record for a key the way a 3270 does:
AID + cursor + modified fields in 3270 mode, plain text in SSCP-LU mode, the TN3270E SYSREQ key as IAC AO.
No Qt here, so the whole path is testable.

Copyright (C) 2026 Garland Glessner <gglessner@gmail.com>
License: GPL-3.0 (see LICENSE)
"""
import logging
from typing import Callable, Optional, Union

try:
    from .connection import TN3270Connection, TN3270Record
    from .orders import AIDS, PDS, TN3270E
    from .ebcdic import ascii_to_ebcdic
    from .screen import ScreenBuffer
except ImportError:
    from connection import TN3270Connection, TN3270Record
    from orders import AIDS, PDS, TN3270E
    from ebcdic import ascii_to_ebcdic
    from screen import ScreenBuffer

logger = logging.getLogger(__name__)

AID_ENTER = AIDS['ENTER']
AID_CLEAR = AIDS['CLEAR']
AID_SYSREQ = AIDS['SYSREQ']


class TN3270Session:
    def __init__(self, connection: TN3270Connection, screen: ScreenBuffer):
        self.conn = connection
        self.screen = screen
        self.on_screen_changed: Optional[Callable[[], None]] = None

    # ----- host -> terminal ------------------------------------------------------------------------------------------

    def handle_record(self, rec: TN3270Record):
        """Process one host record and answer it."""
        dt = rec.data_type
        self.screen.sscp_mode = (dt == TN3270E.DT_SSCP_LU_DATA) or (
            self.screen.sscp_mode and dt not in (TN3270E.DT_3270_DATA, TN3270E.DT_UNBIND, TN3270E.DT_BIND_IMAGE))
        if dt == TN3270E.DT_3270_DATA:
            pds, replies = self.screen.process_ds(rec.payload)
            if replies:
                # A read produced output: acknowledge first, then the data (x3270 net_output)
                if rec.response_flag == TN3270E.RSF_ALWAYS_RESPONSE:
                    self.conn.respond(rec, PDS.OKAY_NO_OUTPUT)
                for reply in replies:
                    self.conn.send_record(reply, TN3270E.DT_3270_DATA if self.conn.tn3270e_mode else None)
            else:
                self.conn.respond(rec, pds)
            if (rec.request_flag & TN3270E.RQF_KEYBOARD_RESTORE
                    and TN3270E.FUNC_DATA_STREAM_CTL in self.conn.negotiated_functions):
                self.screen.keyboard_locked = False
        elif dt == TN3270E.DT_SSCP_LU_DATA:
            self.screen.write_sscp_lu(rec.payload)
        elif dt == TN3270E.DT_UNBIND:
            self.screen.clear()
            self.screen.keyboard_locked = False
            self.screen._refresh()
        elif dt == TN3270E.DT_BIND_IMAGE:
            pass                                    # the session is bound; the host's first Write follows
        elif dt == TN3270E.DT_NVT_DATA:
            text = rec.payload.decode('ascii', 'replace').replace('\r\n', '\n').replace('\r', '\n')
            self.screen.write_sscp_lu(ascii_to_ebcdic(text).replace(ascii_to_ebcdic('\n'), b'\x15'))
            self.conn.respond(rec, PDS.OKAY_NO_OUTPUT)
        if self.on_screen_changed:
            self.on_screen_changed()

    # ----- terminal -> host ------------------------------------------------------------------------------------------

    def send_aid(self, aid: Union[str, int]) -> bool:
        """Send an AID key (name like 'ENTER'/'PF3' or the AID byte). Returns True if something was sent."""
        if isinstance(aid, str):
            aid_byte = AIDS.get(aid.upper())
            if aid_byte is None:
                return False
        else:
            aid_byte = aid
        if not self.conn.connected:
            return False

        if aid_byte == AID_SYSREQ:
            # TN3270E: IAC AO with the SYSREQ function (also how you toggle back from the SSCP session), else
            # nothing. Plain TN3270: the 3270 test request. (x3270 SysReq_action)
            if self.conn.tn3270e_mode:
                return self.conn.send_sysreq()
            if self.screen.keyboard_locked:
                return False
            self.screen.aid = aid_byte
            self.screen.keyboard_locked = True
            return self.conn.send_record(self.screen.read_modified(aid_byte))

        if self.conn.tn3270e_mode and self.conn.submode == 'sscp':
            return self._send_sscp(aid_byte)

        if (self.conn.tn3270e_mode and TN3270E.FUNC_BIND_IMAGE in self.conn.negotiated_functions
                and self.conn.submode == 'unbound'):
            return False                            # no session yet: nothing to send to (x3270 kybd_in3270)

        if self.screen.keyboard_locked:
            return False                            # waiting for the host: no second AID (Reset unlocks)

        record = self.screen.read_modified(aid_byte)
        self.screen.aid = aid_byte
        self.screen.keyboard_locked = True
        ok = self.conn.send_record(record)
        if aid_byte == AID_CLEAR:
            self.screen.clear()                     # CLEAR erases the buffer locally (unformatted, cursor home)
            self.screen._refresh()
        if self.on_screen_changed:
            self.on_screen_changed()
        return ok

    def reset(self):
        """The RESET key: unlock the keyboard (local only)."""
        self.screen.keyboard_locked = False
        if self.on_screen_changed:
            self.on_screen_changed()

    def send_attn(self) -> bool:
        """The ATTN key (x3270 Attn_action): TN3270E -> IAC IP once the session is bound; plain TN3270 ->
        PA1 then IAC BREAK (what PCOMM does). ATTN is a telnet signal, not an AID byte."""
        if not self.conn.connected:
            return False
        if self.conn.tn3270e_mode:
            if self.conn.bound or TN3270E.FUNC_BIND_IMAGE not in self.conn.negotiated_functions:
                return self.conn.send(bytes([0xFF, 0xF4]))          # IAC IP
            return False
        self.screen.aid = AIDS['PA1']
        self.conn.send_record(self.screen.read_modified(AIDS['PA1']))
        return self.conn.send(bytes([0xFF, 0xF3]))                  # IAC BREAK

    def _send_sscp(self, aid_byte: int) -> bool:
        """SSCP-LU mode (x3270 key_AID): ENTER sends the typed text and moves to the next line; CLEAR is local;
        everything else is invalid there."""
        s = self.screen
        if aid_byte == AID_CLEAR:
            s.clear()
            s.sscp_start = 0
            s._refresh()
            if self.on_screen_changed:
                self.on_screen_changed()
            return False
        if aid_byte != AID_ENTER:
            return False
        last_row = s.cursor_pos // s.COLS == s.ROWS - 1
        text = s.read_modified(aid_byte, sscp=True)
        s.aid = aid_byte
        ok = self.conn.send_record(text, TN3270E.DT_SSCP_LU_DATA)
        if last_row:
            s._scroll_up()
            s.cursor_pos = (s.ROWS - 1) * s.COLS
        else:
            s.cursor_pos = ((s.cursor_pos + s.COLS) // s.COLS) * s.COLS
        s.buffer_addr = s.cursor_pos
        s._refresh()
        if self.on_screen_changed:
            self.on_screen_changed()
        return ok
