"""TN3270E (RFC 2355): negotiation, record types, responses, SSCP-LU mode, SYSREQ."""
from conftest import make_connection, enter_3270_mode

from orders import TN3270E
from screen import ScreenBuffer
from session import TN3270Session
from ebcdic import ascii_to_ebcdic, ebcdic_bytes_to_ascii

IAC, EOR, DO, WILL, WONT, SB, SE, AO = 0xFF, 0xEF, 0xFD, 0xFB, 0xFC, 0xFA, 0xF0, 0xF5
OPT = 0x28
DEVICE_TYPE, FUNCTIONS, IS, REJECT, REQUEST, SEND, CONNECT, REASON = 2, 3, 4, 6, 7, 8, 1, 5


def sb(*body) -> bytes:
    return bytes([IAC, SB, OPT, *body, IAC, SE])


def negotiate(c, functions=(0, 2, 4), lu=b'LU00001'):
    c.feed(bytes([IAC, DO, OPT]))
    c.feed(sb(SEND, DEVICE_TYPE))
    c.feed(sb(DEVICE_TYPE, IS, *b'IBM-3278-2-E', CONNECT, *lu))
    c.feed(sb(FUNCTIONS, IS, *functions))
    c.socket.take()


def rec(header, payload: bytes) -> bytes:
    return (bytes(header) + payload).replace(b'\xff', b'\xff\xff') + bytes([IAC, EOR])


def hdr(dt, rsp=0, seq=1, req=0):
    return [dt, req, rsp, seq >> 8, seq & 0xFF]


def wired():
    c = make_connection()
    s = ScreenBuffer()
    sess = TN3270Session(c, s)
    c.on_record = sess.handle_record
    return c, s, sess


# ----- negotiation -------------------------------------------------------------------------------------------------

def test_the_rfc_2355_handshake():
    c = make_connection()
    c.feed(bytes([IAC, DO, OPT]))
    assert c.socket.take() == bytes([IAC, WILL, OPT])
    c.feed(sb(SEND, DEVICE_TYPE))
    assert c.socket.take() == sb(DEVICE_TYPE, REQUEST, *b'IBM-3278-2-E')
    c.feed(sb(DEVICE_TYPE, IS, *b'IBM-3278-2-E', CONNECT, *b'TCP00042'))
    assert c.socket.take() == sb(FUNCTIONS, REQUEST, 0, 2, 4)
    assert c.connected_lu == 'TCP00042'
    c.feed(sb(FUNCTIONS, IS, 0, 2, 4))
    assert c.negotiation_complete and c.negotiated_functions == [0, 2, 4] and c.submode == 'unbound'


def test_an_lu_name_is_requested_with_connect():
    c = make_connection()
    c.lu_name = 'TSOLU01'
    c.feed(bytes([IAC, DO, OPT]))
    c.socket.take()
    c.feed(sb(SEND, DEVICE_TYPE))
    assert c.socket.take() == sb(DEVICE_TYPE, REQUEST, *b'IBM-3278-2-E', CONNECT, *b'TSOLU01')


def test_a_host_counter_proposal_is_accepted_with_functions_is():
    """The old code ignored a host FUNCTIONS REQUEST and hung in negotiation."""
    c = make_connection()
    c.feed(bytes([IAC, DO, OPT]))
    c.feed(sb(SEND, DEVICE_TYPE))
    c.feed(sb(DEVICE_TYPE, IS, *b'IBM-3278-2-E'))
    c.socket.take()
    c.feed(sb(FUNCTIONS, REQUEST, 2))                          # host: RESPONSES only
    assert c.socket.take() == sb(FUNCTIONS, IS, 2)
    assert c.negotiation_complete and c.negotiated_functions == [2]
    assert c.submode == '3270'                                 # no BIND-IMAGE: straight to 3270 mode


def test_a_counter_proposal_adding_functions_gets_the_overlap():
    c = make_connection()
    c.feed(bytes([IAC, DO, OPT]))
    c.feed(sb(SEND, DEVICE_TYPE))
    c.feed(sb(DEVICE_TYPE, IS, *b'IBM-3278-2-E'))
    c.socket.take()
    c.feed(sb(FUNCTIONS, REQUEST, 1, 2))                       # DATA-STREAM-CTL we never asked for
    assert c.socket.take() == sb(FUNCTIONS, REQUEST, 2)
    assert not c.negotiation_complete


def test_device_type_reject_backs_off_to_tn3270():
    """REJECT sits at the 2nd byte after the option (the old code looked one byte early) and needs WONT."""
    c = make_connection()
    c.feed(bytes([IAC, DO, OPT]))
    c.feed(sb(SEND, DEVICE_TYPE))
    c.socket.take()
    c.feed(sb(DEVICE_TYPE, REJECT, REASON, 0x07))
    assert c.socket.take() == bytes([IAC, WONT, OPT])
    assert not c.tn3270e_mode


def test_a_host_adding_functions_in_is_is_refused():
    c = make_connection()
    c.feed(bytes([IAC, DO, OPT]))
    c.feed(sb(SEND, DEVICE_TYPE))
    c.feed(sb(DEVICE_TYPE, IS, *b'IBM-3278-2-E'))
    c.socket.take()
    c.feed(sb(FUNCTIONS, IS, 0, 1, 2))
    assert c.socket.take() == bytes([IAC, WONT, OPT]) and not c.tn3270e_mode


# ----- responses -----------------------------------------------------------------------------------------------------

def test_always_response_gets_a_positive_response_with_the_hosts_sequence_number():
    """The core reason a z/OS session hung: RESPONSES was negotiated but never sent."""
    c, s, _ = wired()
    negotiate(c)
    c.feed(rec(hdr(TN3270E.DT_BIND_IMAGE), bytes([0x31])))
    write = bytes([0xF5, 0xC3, 0x11, 0x40, 0x40]) + ascii_to_ebcdic('READY')
    c.feed(rec(hdr(TN3270E.DT_3270_DATA, rsp=TN3270E.RSF_ALWAYS_RESPONSE, seq=0x01FF), write))
    assert c.socket.take() == bytes([0x02, 0x00, 0x00, 0x01, 0xFF, 0xFF, 0x00, IAC, EOR])   # seq FF doubled
    assert ebcdic_bytes_to_ascii(bytes(cl.ebc for cl in s.cells[:5])) == 'READY'


def test_no_response_and_error_response_on_success_send_nothing():
    c, _, _ = wired()
    negotiate(c, functions=(2,))
    for flag in (TN3270E.RSF_NO_RESPONSE, TN3270E.RSF_ERROR_RESPONSE):
        c.feed(rec(hdr(TN3270E.DT_3270_DATA, rsp=flag), bytes([0xF1, 0xC3])))
    assert c.socket.take() == b''


def test_a_bad_command_gets_a_negative_response():
    c, _, _ = wired()
    negotiate(c, functions=(2,))
    c.feed(rec(hdr(TN3270E.DT_3270_DATA, rsp=TN3270E.RSF_ERROR_RESPONSE, seq=7), bytes([0x99])))
    assert c.socket.take() == bytes([0x02, 0x00, 0x01, 0x00, 0x07, 0x00, IAC, EOR])         # COMMAND-REJECT


def test_a_bad_buffer_address_gets_operation_check():
    c, _, _ = wired()
    negotiate(c, functions=(2,))
    bad_sba = bytes([0xF1, 0xC3, 0x11, 0x3F, 0xFF])                                  # 14-bit address 16383
    c.feed(rec(hdr(TN3270E.DT_3270_DATA, rsp=TN3270E.RSF_ALWAYS_RESPONSE, seq=9), bad_sba))
    assert c.socket.take() == bytes([0x02, 0x00, 0x01, 0x00, 0x09, 0x02, IAC, EOR])


def test_a_read_is_acknowledged_before_its_data():
    c, _, _ = wired()
    negotiate(c, functions=(2,))
    c.feed(rec(hdr(TN3270E.DT_3270_DATA, rsp=TN3270E.RSF_ALWAYS_RESPONSE, seq=3), bytes([0xF6])))  # Read Modified
    out = c.socket.take()
    ack = bytes([0x02, 0x00, 0x00, 0x00, 0x03, 0x00, IAC, EOR])
    assert out.startswith(ack)
    assert out[len(ack):len(ack) + 6] == bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x60])  # 3270-DATA, AID_NO


def test_outbound_sequence_numbers_count_and_wrap_at_32767():
    c = make_connection()
    negotiate(c, functions=(2,))
    c._sequence_number = 0x7FFF
    c.send_record(b'\x7d')
    c.send_record(b'\x7d')
    out = c.socket.take()
    # seq 0x7FFF: its 0xFF byte is IAC-doubled on the wire, like any other 0xFF
    assert out[:9] == bytes([0, 0, 0, 0x7F, 0xFF, 0xFF, 0x7D, IAC, EOR])
    assert out[9:14] == bytes([0, 0, 0, 0, 0])


# ----- BIND / SSCP-LU / UNBIND ----------------------------------------------------------------------------------------

def test_the_vtam_logon_screen_arrives_as_sscp_lu_data_and_is_shown():
    """With BIND-IMAGE agreed, the USS screen is SSCP-LU-DATA; the old code looked for a write command in it
    and dropped it - a blank screen on a real mainframe."""
    c, s, _ = wired()
    negotiate(c)
    uss = ascii_to_ebcdic('WELCOME TO Z/OS') + b'\x15' + ascii_to_ebcdic('ENTER LOGON:')
    c.feed(rec(hdr(TN3270E.DT_SSCP_LU_DATA, seq=0), uss))
    assert c.submode == 'sscp'
    row0 = ''.join(cl.char for cl in s.cells[:15])
    row1 = ''.join(cl.char for cl in s.cells[80:92])
    assert row0 == 'WELCOME TO Z/OS' and row1 == 'ENTER LOGON:'
    assert s.cursor_pos == 92


def test_logon_input_in_sscp_mode_is_plain_text_with_an_sscp_header():
    c, s, sess = wired()
    negotiate(c)
    c.feed(rec(hdr(TN3270E.DT_SSCP_LU_DATA, seq=0), ascii_to_ebcdic('LOGON:')))
    for ch in 'TSO':
        s.type_char(s.cursor_pos, ch)
        s.cursor_pos += 1
    sess.send_aid('ENTER')
    out = c.socket.take()
    assert out == bytes([0x07, 0x00, 0x00, 0x00, 0x00]) + ascii_to_ebcdic('TSO') + bytes([IAC, EOR])
    assert s.cursor_pos == 80                                   # next line, like a printer-style terminal


def test_3270_data_before_bind_is_ignored_and_after_bind_is_shown():
    c, s, _ = wired()
    negotiate(c)
    write = bytes([0xF5, 0xC3]) + ascii_to_ebcdic('HI')
    c.feed(rec(hdr(TN3270E.DT_3270_DATA), write))
    assert s.cells[0].char == ' '
    c.feed(rec(hdr(TN3270E.DT_BIND_IMAGE), bytes([0x31, 0x01])))
    c.feed(rec(hdr(TN3270E.DT_3270_DATA), write))
    assert c.bound and c.submode == '3270' and s.cells[0].char == 'H'


def test_unbind_clears_the_screen_and_returns_to_unbound():
    c, s, _ = wired()
    negotiate(c)
    c.feed(rec(hdr(TN3270E.DT_BIND_IMAGE), bytes([0x31])))
    c.feed(rec(hdr(TN3270E.DT_3270_DATA), bytes([0xF5, 0xC3]) + ascii_to_ebcdic('APP')))
    c.feed(rec(hdr(TN3270E.DT_UNBIND), bytes([0x01])))
    assert not c.bound and c.submode == 'unbound' and s.cells[0].char == ' '


def test_sysreq_is_iac_ao_in_tn3270e():
    c, _, sess = wired()
    negotiate(c)
    c.feed(rec(hdr(TN3270E.DT_BIND_IMAGE), bytes([0x31])))
    c.feed(rec(hdr(TN3270E.DT_3270_DATA), bytes([0xF5, 0xC3])))
    c.socket.take()
    sess.send_aid('SYSREQ')
    assert c.socket.take() == bytes([IAC, AO])


def test_attn_is_iac_ip_once_bound():
    c, _, sess = wired()
    negotiate(c)
    c.feed(rec(hdr(TN3270E.DT_BIND_IMAGE), bytes([0x31])))
    c.socket.take()
    sess.send_attn()
    assert c.socket.take() == bytes([IAC, 0xF4])


# ----- plain TN3270 ------------------------------------------------------------------------------------------------

def test_plain_tn3270_records_have_no_header_even_when_byte_5_looks_like_a_command():
    """The old parser looked for a write command at offset 5 first: an EBCDIC '1' (0xF1) there turned the first
    five bytes into a fake TN3270E header and the screen came out wrong."""
    c, s, _ = wired()
    enter_3270_mode(c)
    write = bytes([0xF5, 0xC3, 0x11, 0x40, 0x40]) + ascii_to_ebcdic('1234')
    c.feed(rec([], write))
    assert ''.join(cl.char for cl in s.cells[:4]) == '1234'


def test_plain_tn3270_aid_has_no_header():
    c, s, sess = wired()
    enter_3270_mode(c)
    c.feed(rec([], bytes([0xF5, 0xC3])))
    sess.send_aid('ENTER')
    assert c.socket.take() == bytes([0x7D, 0x40, 0x40, IAC, EOR])


def test_plain_tn3270_sysreq_is_the_test_request():
    c, s, sess = wired()
    enter_3270_mode(c)
    c.feed(rec([], bytes([0xF5, 0xC3])))
    sess.send_aid('SYSREQ')
    assert c.socket.take() == bytes([0x01, 0x6C, 0x61, 0x02, IAC, EOR])


# ----- review fixes ------------------------------------------------------------------------------------------------

def test_sysreq_in_sscp_mode_toggles_back_with_iac_ao():
    """SYSREQ is how you return from the SSCP session to the application: it must work in SSCP-LU mode too."""
    c, _, sess = wired()
    negotiate(c)
    c.feed(rec(hdr(TN3270E.DT_SSCP_LU_DATA, seq=0), ascii_to_ebcdic('IKJ56700A')))
    c.socket.take()
    assert sess.send_aid('SYSREQ') and c.socket.take() == bytes([IAC, AO])


def test_sysreq_without_the_sysreq_function_sends_nothing_in_tn3270e():
    c, _, sess = wired()
    negotiate(c, functions=(2,))
    c.feed(rec(hdr(TN3270E.DT_3270_DATA), bytes([0xF5, 0xC3])))
    c.socket.take()
    assert not sess.send_aid('SYSREQ') and c.socket.take() == b''


def test_the_keyboard_locks_after_an_aid_until_the_host_restores_it():
    """Double Enter used to send two AIDs (a double submit on CICS)."""
    c, s, sess = wired()
    negotiate(c, functions=(2,))
    c.feed(rec(hdr(TN3270E.DT_3270_DATA), bytes([0xF5, 0xC3])))       # WCC C3: keyboard restore
    c.socket.take()
    assert sess.send_aid('ENTER') and s.keyboard_locked
    assert not sess.send_aid('ENTER')                                   # locked: refused
    c.feed(rec(hdr(TN3270E.DT_3270_DATA), bytes([0xF1, 0xC1])))       # WCC without restore: still locked
    assert s.keyboard_locked
    c.feed(rec(hdr(TN3270E.DT_3270_DATA), bytes([0xF1, 0xC2])))       # restore
    assert not s.keyboard_locked and sess.send_aid('ENTER')
    sess.reset()
    assert not s.keyboard_locked


def test_no_aid_is_sent_before_the_session_is_bound():
    c, _, sess = wired()
    negotiate(c)                                                        # BIND-IMAGE agreed, nothing bound yet
    assert not sess.send_aid('ENTER') and c.socket.take() == b''
