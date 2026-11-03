"""The 3270 data stream: addressing, writes, fields, reads, keyboard edits, code page."""
from screen import ScreenBuffer
from orders import PDS, decode_buffer_address, encode_buffer_address
from ebcdic import ascii_to_ebcdic, ebcdic_to_ascii

SBA, SF, IC, RA, EUA, GE, SFE, PT = 0x11, 0x1D, 0x13, 0x3C, 0x12, 0x08, 0x29, 0x05
UNPROT, PROT = 0x40, 0x60


def sba(pos):
    return bytes([SBA]) + encode_buffer_address(pos)


def text(s, start, n):
    return ''.join(c.char for c in s.cells[start:start + n])


# ----- addressing / code page ---------------------------------------------------------------------------------------

def test_buffer_addresses_decode_12_and_14_bit():
    assert decode_buffer_address(0x00, 0x50) == 80          # 14-bit
    assert decode_buffer_address(0x07, 0x7F) == 1919
    assert decode_buffer_address(0xC1, 0x50) == 80          # 12-bit form of 80
    assert decode_buffer_address(0x81, 0x10) == 80          # 12-bit with unusual graphic bits: low six bits


def test_cp037_brackets_caret_cent_and_not_sign():
    for ch, b in (('[', 0xBA), (']', 0xBB), ('^', 0xB0), ('¢', 0x4A), ('¬', 0x5F)):
        assert ascii_to_ebcdic(ch) == bytes([b])
        assert ebcdic_to_ascii(b) == ch


# ----- writes -----------------------------------------------------------------------------------------------------

def test_erase_write_with_fields_text_and_cursor():
    s = ScreenBuffer()
    ds = (bytes([0xF5, 0xC3]) + sba(0) + bytes([SF, PROT]) + ascii_to_ebcdic('USERID')
          + bytes([SF, UNPROT, IC]) + sba(20) + bytes([SF, PROT]))
    rv, _ = s.process_ds(ds)
    assert rv == PDS.OKAY_NO_OUTPUT
    assert text(s, 1, 6) == 'USERID' and s.cursor_pos == 8
    assert [f.start_pos for f in s.fields] == [0, 7, 20]
    assert s.cells[1].is_protected and not s.cells[8].is_protected


def test_a_plain_write_starts_at_the_cursor_address():
    s = ScreenBuffer()
    s.process_ds(bytes([0xF5, 0xC3]) + sba(100) + bytes([IC]))
    s.process_ds(bytes([0xF1, 0xC3]) + ascii_to_ebcdic('X'))
    assert s.cells[100].char == 'X'


def test_rewriting_a_field_does_not_leave_a_stale_duplicate():
    s = ScreenBuffer()
    s.process_ds(bytes([0xF5, 0xC3]) + sba(10) + bytes([SF, UNPROT]))
    s.process_ds(bytes([0xF1, 0xC3]) + sba(10) + bytes([SF, PROT]))
    s.process_ds(bytes([0xF1, 0xC3]) + sba(10) + bytes([SF, UNPROT]))
    assert [(f.start_pos, f.is_protected) for f in s.fields] == [(10, False)]


def test_writing_a_character_over_an_attribute_removes_the_field():
    s = ScreenBuffer()
    s.process_ds(bytes([0xF5, 0xC3]) + sba(10) + bytes([SF, UNPROT]))
    s.process_ds(bytes([0xF1, 0xC3]) + sba(10) + ascii_to_ebcdic('Z'))
    assert s.fields == [] and s.cells[10].char == 'Z'


def test_repeat_to_the_same_address_fills_the_whole_buffer():
    s = ScreenBuffer()
    s.process_ds(bytes([0xF5, 0xC3]) + sba(5) + bytes([RA]) + encode_buffer_address(5) + ascii_to_ebcdic('*'))
    assert all(c.char == '*' for c in s.cells)


def test_repeat_with_a_graphic_escape_character():
    s = ScreenBuffer()
    s.process_ds(bytes([0xF5, 0xC3, RA]) + encode_buffer_address(3) + bytes([GE, 0xC5]) + ascii_to_ebcdic('Q'))
    assert all(s.cells[i].ge and s.cells[i].ebc == 0xC5 for i in range(3))
    assert s.cells[3].char == 'Q'                              # the GE byte was not taken as the next char


def test_an_out_of_range_address_is_a_write_error_not_a_crash():
    """Address 2000 on a 1920-cell buffer used to IndexError in the receive thread and drop the session."""
    s = ScreenBuffer()
    rv, _ = s.process_ds(bytes([0xF5, 0xC3]) + ascii_to_ebcdic('OK') + bytes([SBA, 0x07, 0xD0]) + ascii_to_ebcdic('X'))
    assert rv == PDS.BAD_ADDR and text(s, 0, 2) == 'OK'


def test_erase_unprotected_to_address():
    s = ScreenBuffer()
    s.process_ds(bytes([0xF5, 0xC3, SF, PROT]) + ascii_to_ebcdic('AA') + bytes([SF, UNPROT]) + ascii_to_ebcdic('BB'))
    s.process_ds(bytes([0xF1, 0xC3]) + sba(0) + bytes([EUA]) + encode_buffer_address(6))
    assert text(s, 1, 2) == 'AA' and text(s, 4, 2) == '  ' and s.cells[4].ebc == 0


def test_wcc_reset_mdt_clears_modified_tags():
    s = ScreenBuffer()
    s.process_ds(bytes([0xF5, 0xC3, SF, UNPROT | 0x01]))         # premodified field
    assert s.fields[0].is_modified
    s.process_ds(bytes([0xF1, 0xC3 | 0x01]))
    assert not s.fields[0].is_modified


def test_sfe_colour_and_highlight():
    s = ScreenBuffer()
    s.process_ds(bytes([0xF5, 0xC3, SFE, 3, 0xC0, PROT, 0x42, 0xF2, 0x41, 0xF2]) + ascii_to_ebcdic('ERR'))
    assert s.cells[1].color == 'red' and s.cells[1].highlight == 'reverse'


def test_outbound_3270ds_structured_field_writes_the_screen():
    s = ScreenBuffer()
    inner = bytes([0xF5, 0xC3]) + ascii_to_ebcdic('HELLO')
    sf = bytes([0x00, 4 + len(inner), 0x40, 0x00]) + inner
    rv, _ = s.process_ds(bytes([0xF3]) + sf)
    assert rv == PDS.OKAY_NO_OUTPUT and text(s, 0, 5) == 'HELLO'


def test_erase_all_unprotected():
    s = ScreenBuffer()
    s.process_ds(bytes([0xF5, 0xC3, SF, PROT]) + ascii_to_ebcdic('P') + bytes([SF, UNPROT | 0x01])
                 + ascii_to_ebcdic('DATA'))
    rv, _ = s.process_ds(bytes([0x6F]))
    assert text(s, 1, 1) == 'P' and text(s, 3, 4) == '    ' and not s.fields[1].is_modified
    assert s.cursor_pos == 3


# ----- reads --------------------------------------------------------------------------------------------------------

def screen_with_two_inputs():
    s = ScreenBuffer()
    s.process_ds(bytes([0xF5, 0xC3]) + sba(0) + bytes([SF, PROT]) + ascii_to_ebcdic('USER')
                 + bytes([SF, UNPROT]) + sba(20) + bytes([SF, PROT]) + sba(80) + bytes([SF, UNPROT])
                 + sba(100) + bytes([SF, PROT]))
    return s


def test_enter_sends_aid_cursor_and_modified_fields_with_nulls_suppressed():
    s = screen_with_two_inputs()
    for i, ch in enumerate('IBMUSER'):
        assert s.type_char(6 + i, ch)
    s.cursor_pos = 13
    out = s.read_modified(0x7D)
    assert out == bytes([0x7D]) + encode_buffer_address(13) + sba(6) + ascii_to_ebcdic('IBMUSER')


def test_mdt_survives_a_read_until_the_host_resets_it():
    """A real 3270 keeps the MDT after Enter; CICS re-reads previously typed fields. The old GUI cleared it."""
    s = screen_with_two_inputs()
    s.type_char(6, 'A')
    first = s.read_modified(0x7D)
    assert s.read_modified(0x7D) == first


def test_a_field_emptied_by_the_user_is_still_sent():
    s = screen_with_two_inputs()
    s.process_ds(bytes([0xF1, 0xC3]) + sba(6) + ascii_to_ebcdic('OLD'))
    s.delete_char(6)
    s.delete_char(6)
    s.delete_char(6)
    out = s.read_modified(0x7D)
    assert out.endswith(sba(6))                                # SBA with no data: "this field is now empty"


def test_short_read_aids_send_only_the_aid():
    s = screen_with_two_inputs()
    s.type_char(6, 'A')
    assert s.read_modified(0x6C) == bytes([0x6C])              # PA1


def test_host_read_buffer_and_read_modified_are_answered():
    """The old code had no RB/RM/RMA commands: the host waited forever."""
    s = screen_with_two_inputs()
    rv, replies = s.process_ds(bytes([0xF2]))                  # Read Buffer
    assert rv == PDS.OKAY_OUTPUT and replies[0][0] == 0x60 and len(replies[0]) > 1920
    assert replies[0][3:5] == bytes([SF, 0x60])                # first position: SF + protected attribute
    rv, replies = s.process_ds(bytes([0xF6]))                  # Read Modified
    assert rv == PDS.OKAY_OUTPUT and replies[0] == bytes([0x60]) + encode_buffer_address(0)


def test_unformatted_screen_sends_its_text():
    s = ScreenBuffer()
    s.process_ds(bytes([0xF5, 0xC3]))
    for i, ch in enumerate('LOGON'):
        s.type_char(i, ch)
    s.cursor_pos = 5
    assert s.read_modified(0x7D) == bytes([0x7D]) + encode_buffer_address(5) + ascii_to_ebcdic('LOGON')


# ----- keyboard -----------------------------------------------------------------------------------------------------

def test_typing_is_refused_on_protected_positions_and_attributes():
    s = screen_with_two_inputs()
    assert not s.type_char(1, 'X') and not s.type_char(5, 'X') and s.type_char(6, 'X')


def test_delete_shifts_the_rest_of_the_field_left():
    s = screen_with_two_inputs()
    for i, ch in enumerate('ABCD'):
        s.type_char(6 + i, ch)
    s.delete_char(7)
    assert text(s, 6, 4) == 'ACD '


def test_erase_eof():
    s = screen_with_two_inputs()
    for i, ch in enumerate('ABCD'):
        s.type_char(6 + i, ch)
    s.erase_eof(7)
    assert text(s, 6, 4) == 'A   ' and s.cells[7].ebc == 0


def test_program_tab_with_no_unprotected_field_goes_to_0_and_nulls_the_rest():
    """x3270: next_unprotected() is 0 when there is none; after text, PT nulls to there."""
    s = ScreenBuffer()
    s.process_ds(bytes([0xF5, 0xC3]) + ascii_to_ebcdic('ABC') + bytes([PT]) + ascii_to_ebcdic('D'))
    assert text(s, 0, 3) == 'DBC' and all(c.ebc == 0 for c in s.cells[3:])


def test_a_bad_structured_field_keeps_the_good_ones_before_it():
    s = ScreenBuffer()
    good = bytes([0x00, 0x05, 0x01, 0xFF, 0x02])                         # Read Partition Query
    rv, replies = s.process_ds(bytes([0xF3]) + good + bytes([0x00, 0x09, 0x40]))   # then a bad length
    assert rv == PDS.OKAY_OUTPUT and len(replies) == 1


def test_eau_and_home_follow_x3270_when_a_field_wraps_the_buffer_end():
    s = ScreenBuffer()
    # one unprotected field from 1900 wrapping to a protected field at 20
    s.process_ds(bytes([0xF5, 0xC3]) + sba(20) + bytes([SF, PROT]) + sba(1900) + bytes([SF, UNPROT]))
    assert s.get_first_input_field() == 1901
    s.process_ds(bytes([0x6F]))
    assert s.cursor_pos == 1901


def test_graphic_escape_characters_display_from_the_apl_set():
    s = ScreenBuffer()
    s.process_ds(bytes([0xF5, 0xC3, GE, 0xAD, GE, 0xBD]))
    assert text(s, 0, 2) == '[]'


def test_reply_modes_offered_are_the_ones_implemented():
    from query import query_reply_sf
    assert query_reply_sf(0x88) == bytes([0x00, 0x06, 0x81, 0x88, 0x00, 0x01])


def test_clear_resets_the_sscp_start():
    s = ScreenBuffer()
    s.write_sscp_lu(ascii_to_ebcdic('LOGON'))
    s.clear()
    assert s.sscp_start == 0


def test_tab_and_backtab():
    s = screen_with_two_inputs()
    assert s.get_first_input_field() == 6
    assert s.get_next_input_field(6) == 81
    assert s.get_next_input_field(81) == 6
    assert s.get_prev_input_field(81) == 6
    assert s.get_prev_input_field(85) == 81
