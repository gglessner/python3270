"""The real MainWindow, offscreen: host records cross from the receive thread to the GUI thread through the signal
bridge, the screen updates, and an Enter key goes back. Skipped without PySide6."""
import os
import time

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
QtWidgets = pytest.importorskip('PySide6.QtWidgets')

from test_end_to_end import Host, rec, sb, IAC, DO, WILL, OPT     # noqa: E402
from ebcdic import ascii_to_ebcdic                                # noqa: E402
from orders import encode_buffer_address                          # noqa: E402


def pump(app, pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if pred():
            return True
        time.sleep(0.01)
    return False


def test_main_window_session_offscreen():
    import threading
    from main_window import MainWindow

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    win = MainWindow()
    host = Host()
    t = threading.Thread(target=host.accept, daemon=True)
    t.start()
    assert win.connection.connect('127.0.0.1', host.port)
    t.join(5)
    try:
        host.send(bytes([IAC, DO, OPT]))
        host.expect(bytes([IAC, WILL, OPT]))
        host.send(sb(0x08, 0x02))
        host.expect(sb(0x02, 0x07, *b'IBM-3278-2-E'))
        host.send(sb(0x02, 0x04, *b'IBM-3278-2-E'))
        host.expect(sb(0x03, 0x07, 0x00, 0x04, 0x05))
        host.send(sb(0x03, 0x04, 0x04))                                   # RESPONSES only: straight to 3270
        assert pump(app, lambda: win.connection.negotiation_complete)

        ew = (bytes([0xF5, 0xC3, 0x1D, 0x60]) + ascii_to_ebcdic('APPLID')
              + bytes([0x1D, 0x40, 0x13, 0x11]) + encode_buffer_address(20) + bytes([0x1D, 0x60]))
        host.send(rec([0x00, 0, 0x02, 0x00, 0x05], ew))
        # the record is handled on the GUI thread (this one) once Qt runs the queued signal
        assert pump(app, lambda: win.terminal.cursor_pos == 8)
        assert host.next_record() == bytes([0x02, 0x00, 0x00, 0x00, 0x05, 0x00])    # ack, sent from the GUI thread
        assert ''.join(c.char for c in win.screen.cells[1:7]) == 'APPLID'
        assert 'TN3270E' in win.status_bar.mode_label.text()

        win.screen.type_char(8, 'X')
        win._send_aid('ENTER')
        got = host.next_record()
        assert got[5] == 0x7D and got.endswith(bytes([0x11]) + encode_buffer_address(8) + ascii_to_ebcdic('X'))
        assert 'X SYSTEM' in win.status_bar.mode_label.text()               # locked until the host answers

        # Shift+Tab arrives from Qt as Key_Backtab: it must back-tab
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        win.screen.keyboard_locked = False
        win.terminal.set_cursor_pos(12)
        QTest.keyClick(win.terminal, Qt.Key_Backtab, Qt.ShiftModifier)
        assert win.terminal.cursor_pos == 8

        # SSCP-LU input typed past the last position scrolls instead of wrapping to the top
        win.screen.clear()
        win.screen.sscp_mode = True
        win.screen.sscp_start = 1890
        win.terminal.set_cursor_pos(1919)
        QTest.keyClick(win.terminal, Qt.Key_A)
        assert win.terminal.cursor_pos == 1840 and win.screen.cells[1839].char == 'a'   # (no Shift: 'a')
        assert win.screen.sscp_start == 1810
    finally:
        win.connection.disconnect()
        host.close()
        pump(app, lambda: False, 0.2)
        win.close()
