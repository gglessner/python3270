"""Tests run headless (no Qt): the package's modules are imported flat, as python3270.py does."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class FakeSocket:
    """Captures what the connection sends."""

    def __init__(self):
        self.sent = bytearray()

    def sendall(self, data):
        self.sent += data

    def take(self) -> bytes:
        out, self.sent = bytes(self.sent), bytearray()
        return out

    def shutdown(self, *_):
        pass

    def close(self):
        pass


def make_connection():
    """A TN3270Connection wired to a FakeSocket (no network, no receive thread)."""
    from connection import TN3270Connection
    c = TN3270Connection()
    c.socket = FakeSocket()
    c.connected = True
    return c


def enter_3270_mode(c):
    """Plain TN3270: BINARY and EOR both ways (what a host does before sending 3270 records)."""
    c.feed(bytes([0xFF, 0xFD, 0x00, 0xFF, 0xFD, 0x19, 0xFF, 0xFB, 0x00, 0xFF, 0xFB, 0x19]))
    c.socket.take()
    assert c.in_3270
