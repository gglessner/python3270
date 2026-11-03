"""End to end over a real socket: a scripted TN3270E host that behaves like a z/OS TN3270 server, against the
real TN3270Connection (receive thread) + TN3270Session + ScreenBuffer. No Qt."""
import socket
import threading
import time

from connection import TN3270Connection
from screen import ScreenBuffer
from session import TN3270Session
from query import parse_structured_fields, SUPPORTED
from orders import encode_buffer_address
from ebcdic import ascii_to_ebcdic

IAC, EOR, DO, WILL, SB, SE = 0xFF, 0xEF, 0xFD, 0xFB, 0xFA, 0xF0
OPT, TM = 0x28, 0x06


def sb(*body):
    return bytes([IAC, SB, OPT, *body, IAC, SE])


def rec(header, payload):
    return (bytes(header) + payload).replace(b'\xff', b'\xff\xff') + bytes([IAC, EOR])


class Host:
    """The server side: send, and read until an expected byte string shows up."""

    def __init__(self):
        self.lsock = socket.socket()
        self.lsock.bind(('127.0.0.1', 0))
        self.lsock.listen(1)
        self.port = self.lsock.getsockname()[1]
        self.sock = None
        self.buf = bytearray()

    def accept(self):
        self.sock, _ = self.lsock.accept()
        self.sock.settimeout(5)

    def send(self, data):
        self.sock.sendall(data)

    def expect(self, want: bytes, timeout=5.0) -> bytes:
        end = time.time() + timeout
        while want not in self.buf:
            if time.time() > end:
                raise AssertionError(f"timed out waiting for {want.hex()}; got {bytes(self.buf).hex()}")
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                raise AssertionError("client closed")
            self.buf += chunk
        i = self.buf.index(want) + len(want)
        out, self.buf = bytes(self.buf[:i]), self.buf[i:]
        return out

    def next_record(self, timeout=5.0) -> bytes:
        raw = self.expect(bytes([IAC, EOR]), timeout)
        return raw[:-2].replace(b'\xff\xff', b'\xff')

    def close(self):
        for s in (self.sock, self.lsock):
            try:
                s.close()
            except OSError:
                pass


def wait_for(pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


def test_a_zos_style_tn3270e_session_from_logon_to_application():
    host = Host()
    conn, screen = TN3270Connection(), ScreenBuffer()
    session = TN3270Session(conn, screen)
    lock = threading.Lock()

    def on_record(r):
        with lock:
            session.handle_record(r)
    conn.on_record = on_record

    t = threading.Thread(target=host.accept, daemon=True)
    t.start()
    assert conn.connect('127.0.0.1', host.port)
    t.join(5)
    try:
        # --- negotiation, with a counter-proposal (no SYSREQ) ---
        host.send(bytes([IAC, DO, OPT]))
        host.expect(bytes([IAC, WILL, OPT]))
        host.send(sb(0x08, 0x02))                                            # SEND DEVICE-TYPE
        host.expect(sb(0x02, 0x07, *b'IBM-3278-2-E'))
        host.send(sb(0x02, 0x04, *b'IBM-3278-2-E', 0x01, *b'TCP00001'))      # IS ... CONNECT TCP00001
        host.expect(sb(0x03, 0x07, 0x00, 0x02, 0x04))                        # FUNCTIONS REQUEST
        host.send(sb(0x03, 0x07, 0x00, 0x02))                                # counter: BIND-IMAGE, RESPONSES
        host.expect(sb(0x03, 0x04, 0x00, 0x02))                              # FUNCTIONS IS, as received
        assert wait_for(lambda: conn.negotiation_complete)
        assert conn.connected_lu == 'TCP00001'

        # --- the VTAM USS screen (SSCP-LU-DATA), and logon typed there ---
        host.send(rec([0x07, 0, 0, 0, 0], ascii_to_ebcdic('Z/OS 3.1') + b'\x15' + ascii_to_ebcdic('LOGON ===> ')))
        assert wait_for(lambda: ''.join(c.char for c in screen.cells[80:91]) == 'LOGON ===> ')
        with lock:
            for ch in 'TSO':
                screen.type_char(screen.cursor_pos, ch)
                screen.cursor_pos += 1
            session.send_aid('ENTER')
        assert host.next_record() == bytes([0x07, 0, 0, 0, 0]) + ascii_to_ebcdic('TSO')

        # --- BIND, then the host's Query with ALWAYS-RESPONSE ---
        host.send(rec([0x03, 0, 0, 0, 0], bytes([0x31, 0x01, 0x03, 0x03])))
        query = bytes([0xF3, 0x00, 0x05, 0x01, 0xFF, 0x02])
        host.send(rec([0x00, 0, 0x02, 0x00, 0x01], query))
        assert host.next_record() == bytes([0x02, 0x00, 0x00, 0x00, 0x01, 0x00])   # positive response, seq 1
        qr = host.next_record()
        # outbound seq: the logon text was 0, so the query reply is 1 (one counter, as in x3270)
        assert qr[:5] == bytes([0x00, 0x00, 0x00, 0x00, 0x01]) and qr[5] == 0x88
        assert [f[3] for _, f in parse_structured_fields(qr[6:])] == list(SUPPORTED)

        # --- the application's first screen, ALWAYS-RESPONSE ---
        ew = (bytes([0xF5, 0xC3, 0x11]) + encode_buffer_address(0) + bytes([0x1D, 0x60])
              + ascii_to_ebcdic('USERID ===>') + bytes([0x1D, 0x40, 0x13]) + bytes([0x11])
              + encode_buffer_address(30) + bytes([0x1D, 0x60]))
        host.send(rec([0x00, 0, 0x02, 0x00, 0x02], ew))
        assert host.next_record() == bytes([0x02, 0x00, 0x00, 0x00, 0x02, 0x00])
        assert wait_for(lambda: screen.cursor_pos == 13)

        # --- the user types a userid and presses Enter ---
        with lock:
            for i, ch in enumerate('IBMUSER'):
                assert screen.type_char(13 + i, ch)
            screen.cursor_pos = 20
            session.send_aid('ENTER')
        got = host.next_record()
        assert got == (bytes([0x00, 0x00, 0x00, 0x00, 0x02, 0x7D]) + encode_buffer_address(20)
                       + bytes([0x11]) + encode_buffer_address(13) + ascii_to_ebcdic('IBMUSER'))

        # --- the z/OS TIMEMARK keepalive is answered ---
        host.send(bytes([IAC, DO, TM]))
        host.expect(bytes([IAC, WILL, TM]))
    finally:
        conn.disconnect()
        host.close()
