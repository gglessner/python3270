"""The telnet layer: framing, escaping, commands anywhere, option answers."""
from conftest import make_connection, enter_3270_mode

IAC, EOR, NOP, DO, DONT, WILL, WONT, SB, SE = 0xFF, 0xEF, 0xF1, 0xFD, 0xFE, 0xFB, 0xFC, 0xFA, 0xF0
TM, BINARY = 0x06, 0x00


def records_of(conn, data: bytes):
    enter_3270_mode(conn)
    got = []
    conn.on_record = got.append
    conn.feed(data)
    return got


def test_iac_iac_inside_a_record_is_one_ff():
    c = make_connection()
    (r,) = records_of(c, bytes([0xF1, 0xC3, IAC, IAC, 0x40, IAC, EOR]))
    assert r.payload == bytes([0xF1, 0xC3, 0xFF, 0x40])


def test_an_escaped_ff_followed_by_ef_does_not_end_the_record():
    """Data bytes FF EF go out as FF FF EF: the old scanner found 'FF EF' and cut the record there."""
    c = make_connection()
    got = records_of(c, bytes([0xF1, 0xC3, IAC, IAC, 0xEF, 0xC1, IAC, EOR]))
    assert len(got) == 1 and got[0].payload == bytes([0xF1, 0xC3, 0xFF, 0xEF, 0xC1])


def test_a_two_byte_telnet_command_does_not_corrupt_the_next_record():
    """IAC NOP (a keepalive) before a record used to be glued onto it."""
    c = make_connection()
    (r,) = records_of(c, bytes([IAC, NOP, 0xF5, 0xC3, IAC, EOR]))
    assert r.payload == bytes([0xF5, 0xC3])


def test_a_command_in_the_middle_of_a_record_is_handled_and_removed():
    c = make_connection()
    (r,) = records_of(c, bytes([0xF5, 0xC3, IAC, DO, TM, 0xC1, IAC, EOR]))
    assert r.payload == bytes([0xF5, 0xC3, 0xC1])
    assert c.socket.take() == bytes([IAC, WILL, TM])          # the z/OS TIMEMARK keepalive is answered


def test_records_split_across_reads_reassemble():
    c = make_connection()
    enter_3270_mode(c)
    got = []
    c.on_record = got.append
    for b in bytes([0xF5, 0xC3, IAC]) , bytes([IAC, 0x40, IAC]), bytes([EOR]):
        c.feed(b)
    assert len(got) == 1 and got[0].payload == bytes([0xF5, 0xC3, 0xFF, 0x40])


def test_a_banner_before_3270_mode_is_not_glued_onto_the_first_record():
    """A server or proxy that prints text before negotiating used to garble the logon screen."""
    c = make_connection()
    got = []
    c.on_record = got.append
    c.feed(b'\r\nWelcome to the gateway\r\n')
    enter_3270_mode(c)
    c.feed(bytes([0xF5, 0xC3, 0xC8, 0xC9, IAC, EOR]))
    assert [r.payload for r in got] == [bytes([0xF5, 0xC3, 0xC8, 0xC9])]


def test_plain_tn3270_asks_for_an_lu_as_type_at_lu():
    c = make_connection()
    c.lu_name = 'LU01'
    c.feed(bytes([IAC, SB, 0x18, 0x01, IAC, SE]))
    assert c.socket.take() == bytes([IAC, SB, 0x18, 0x00]) + b'IBM-3278-2-E@LU01' + bytes([IAC, SE])


def test_options_are_answered_once_no_loops():
    c = make_connection()
    c.feed(bytes([IAC, DO, BINARY, IAC, DO, BINARY]))
    assert c.socket.take() == bytes([IAC, WILL, BINARY])
    c.feed(bytes([IAC, WILL, BINARY, IAC, WILL, BINARY]))
    assert c.socket.take() == bytes([IAC, DO, BINARY])
    c.feed(bytes([IAC, DONT, 0x2A]))                           # never enabled: nothing to say
    assert c.socket.take() == b''


def test_unsupported_options_are_refused():
    c = make_connection()
    c.feed(bytes([IAC, DO, 0x01, IAC, WILL, 0x01]))            # ECHO
    assert c.socket.take() == bytes([IAC, WONT, 0x01, IAC, DONT, 0x01])


def test_outbound_records_double_every_ff():
    c = make_connection()
    c.send_record(bytes([0x88, 0xFF, 0x01]))
    assert c.socket.take() == bytes([0x88, 0xFF, 0xFF, 0x01, IAC, EOR])


def test_terminal_type_subnegotiation():
    c = make_connection()
    c.feed(bytes([IAC, SB, 0x18, 0x01, IAC, SE]))
    assert c.socket.take() == bytes([IAC, SB, 0x18, 0x00]) + b'IBM-3278-2-E' + bytes([IAC, SE])
