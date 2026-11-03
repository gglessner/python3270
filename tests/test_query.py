"""The query reply must be well-formed: real hosts parse it field by field."""
from query import build_query_reply, parse_structured_fields, query_reply_sf, SUPPORTED, QR_NULL
from screen import ScreenBuffer
from orders import PDS


def fields_of(reply: bytes):
    assert reply[0] == 0x88                                    # AID: structured field
    return parse_structured_fields(reply[1:])


def test_every_field_length_matches_its_contents_and_the_summary_is_honest():
    sfs = fields_of(build_query_reply())
    codes = [f[3] for _, f in sfs]
    assert all(sfid == 0x81 for sfid, _ in sfs)
    assert codes == list(SUPPORTED)
    summary = sfs[0][1]
    assert list(summary[4:]) == codes                          # lists exactly what is sent (no DDM, no RPQ)


def test_usable_area_is_24x80_with_a_1920_cell_buffer():
    ua = query_reply_sf(0x81)
    assert len(ua) == 23 and ua[:2] == b'\x00\x17'
    assert ua[6:8] == b'\x00\x50' and ua[8:10] == b'\x00\x18' and ua[21:23] == b'\x07\x80'


def test_color_reply_matches_x3270_byte_for_byte():
    body = bytes([0x00, 16, 0x00, 0xF4]) + b''.join(bytes([c, c]) for c in range(0xF1, 0x100))
    assert query_reply_sf(0x86) == bytes([0x00, 4 + len(body), 0x81, 0x86]) + body
    assert len(body) == 34


def test_implicit_partition_alternate_is_the_real_buffer_not_32_rows():
    ip = query_reply_sf(0xA6)
    assert ip[-8:] == b'\x00\x50\x00\x18\x00\x50\x00\x18'


def test_query_list_sends_only_what_was_asked_or_a_null_reply():
    assert [f[3] for _, f in fields_of(build_query_reply([0x86, 0x81]))] == [0x81, 0x86]
    assert [f[3] for _, f in fields_of(build_query_reply([0x99]))] == [QR_NULL]


def test_read_partition_query_from_the_host_is_answered():
    s = ScreenBuffer()
    wsf = bytes([0xF3, 0x00, 0x05, 0x01, 0xFF, 0x02])           # WSF: Read Partition (FF) Query
    rv, replies = s.process_ds(wsf)
    assert rv == PDS.OKAY_OUTPUT and replies == [build_query_reply()]


def test_read_partition_query_list():
    s = ScreenBuffer()
    wsf = bytes([0xF3, 0x00, 0x07, 0x01, 0xFF, 0x03, 0x00, 0x86])
    rv, replies = s.process_ds(wsf)
    assert [f[3] for _, f in fields_of(replies[0])] == [0x86]


def test_read_partition_read_modified_is_a_read_not_a_query():
    s = ScreenBuffer()
    wsf = bytes([0xF3, 0x00, 0x05, 0x01, 0x00, 0xF6])
    rv, replies = s.process_ds(wsf)
    assert replies[0][0] == 0x61                               # AID_QREPLY, then the cursor address
