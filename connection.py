"""
TN3270 Connection Handler
Manages the TCP/TLS connection, the telnet layer and TN3270E negotiation (RFC 854/855/885/1091/2355).

The telnet layer is a byte-level state machine (as in x3270's telnet.c): IAC IAC is un-escaped inside records,
telnet commands are recognised anywhere (an IAC NOP keepalive no longer corrupts the next record), IAC EOR ends a
record, and every outbound record has its 0xFF bytes doubled. TN3270E negotiation follows RFC 2355 the way x3270
does: DEVICE-TYPE REJECT backs off with WONT TN3270E, a host's FUNCTIONS REQUEST counter-proposal is answered,
and the BIND-IMAGE / SSCP-LU-DATA / UNBIND / NVT-DATA data types are told apart. With the RESPONSES function the
host's ALWAYS-RESPONSE requests are acknowledged (see respond()) - without that a z/OS host waits forever.

This module has no Qt dependency. Callbacks run on the receive thread; a GUI must hand them to its own thread.

Copyright (C) 2026 Garland Glessner <gglessner@gmail.com>
License: GPL-3.0 (see LICENSE)
"""

import socket
import ssl
import threading
import logging
from dataclasses import dataclass
from typing import Callable, Optional, List

try:
    from .orders import TELNET, TELNET_OPTIONS, TN3270E, PDS
except ImportError:
    from orders import TELNET, TELNET_OPTIONS, TN3270E, PDS

# Set up logging
logger = logging.getLogger(__name__)

SGA = 0x03          # suppress go-ahead: accepted from a host, harmless

# telnet receive states
_DATA, _IAC, _WILL, _WONT, _DO, _DONT, _SB, _SB_IAC = range(8)


@dataclass
class TN3270Record:
    """One inbound record. Plain TN3270: data_type = 3270-DATA, flags/seq 0, header b''."""
    data_type: int
    request_flag: int
    response_flag: int
    seq: int
    payload: bytes
    header: bytes = b''


class TN3270Connection:
    """TN3270 TCP connection with TN3270E protocol negotiation"""

    TERMINAL_TYPE = b'IBM-3278-2-E'
    BUFFER_SIZE = 65536
    CONNECT_TIMEOUT = 30

    # What we agree to do (host DO -> our WILL) and to let the host do (host WILL -> our DO)
    SUPPORTED_OPTIONS = frozenset([
        TELNET_OPTIONS.BINARY,
        TELNET_OPTIONS.EOR,
        TELNET_OPTIONS.TN3270E,
        TELNET_OPTIONS.TERMINAL_TYPE,
    ])
    ACCEPTED_HOST_OPTIONS = frozenset([TELNET_OPTIONS.BINARY, TELNET_OPTIONS.EOR, SGA])

    # The TN3270E functions we request - and implement (x3270's set)
    REQUESTED_FUNCTIONS = (TN3270E.FUNC_BIND_IMAGE, TN3270E.FUNC_RESPONSES, TN3270E.FUNC_SYSREQ)

    def __init__(self):
        self.socket: Optional[socket.socket] = None
        self.connected: bool = False
        self.lu_name: Optional[str] = None          # LU to ask for (TN3270E CONNECT); None = any
        self._reset_session_state()

        # Callbacks (run on the receive thread)
        self.on_record: Optional[Callable[[TN3270Record], None]] = None
        self.on_data: Optional[Callable[[bytes], None]] = None      # legacy: header + payload + IAC EOR
        self.on_connect: Optional[Callable[[], None]] = None
        self.on_disconnect: Optional[Callable[[], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        self.on_state: Optional[Callable[[], None]] = None          # negotiation / bind state changed

        # Internal state
        self._receive_thread: Optional[threading.Thread] = None
        self._running: bool = False
        self._lock = threading.Lock()

    def _reset_session_state(self):
        self.tn3270e_mode: bool = False             # TN3270E option is in effect (records carry a header)
        self.negotiation_complete: bool = False
        self.negotiated_functions: List[int] = []
        self.bound: bool = False                    # BIND-IMAGE received (SNA session up)
        self.submode: str = 'unbound'               # 'unbound' | 'sscp' | '3270' | 'nvt' (TN3270E)
        self.device_type: Optional[str] = None      # as confirmed by DEVICE-TYPE IS
        self.connected_lu: Optional[str] = None
        self._sequence_number: int = 0
        self._local_opts: set = set()               # options we have agreed to (WILL)
        self._remote_opts: set = set()              # options the host has agreed to (WILL)
        self._functions: list = list(self.REQUESTED_FUNCTIONS)
        self._state = _DATA
        self._record = bytearray()
        self._sb = bytearray()
        self.nvt_text = bytearray()

    # ----- connection --------------------------------------------------------------------------------------------

    def connect(self, host: str, port: int, use_tls: bool = False, lu_name: Optional[str] = None) -> bool:
        """
        Connect to TN3270 server.

        Args:
            host: Server hostname or IP address
            port: Server port number
            use_tls: Enable TLS encryption
            lu_name: optional LU (TN3270E CONNECT) to request

        Returns:
            True if connection initiated successfully
        """
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(self.CONNECT_TIMEOUT)

            if use_tls:
                context = ssl.create_default_context()
                # Allow self-signed certificates for mainframe connections
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                self.socket = context.wrap_socket(self.socket, server_hostname=host)

            logger.info(f"Connecting to {host}:{port} (TLS: {use_tls})")
            self.socket.connect((host, port))
            self.socket.settimeout(None)

            self.connected = True
            self._running = True
            self.lu_name = lu_name if lu_name is not None else self.lu_name
            self._reset_session_state()

            # Start receive thread
            self._receive_thread = threading.Thread(
                target=self._receive_loop,
                daemon=True,
                name="TN3270-Receiver"
            )
            self._receive_thread.start()

            if self.on_connect:
                self.on_connect()

            return True

        except socket.timeout:
            error_msg = f"Connection timed out: {host}:{port}"
            logger.error(error_msg)
            self._handle_error(error_msg)
            return False
        except socket.gaierror as e:
            error_msg = f"DNS resolution failed: {host} - {e}"
            logger.error(error_msg)
            self._handle_error(error_msg)
            return False
        except ConnectionRefusedError:
            error_msg = f"Connection refused: {host}:{port}"
            logger.error(error_msg)
            self._handle_error(error_msg)
            return False
        except Exception as e:
            error_msg = f"Connection failed: {e}"
            logger.error(error_msg)
            self._handle_error(error_msg)
            return False

    def disconnect(self):
        """Disconnect from server and clean up resources."""
        was_connected = self.connected or self.socket is not None
        logger.info("Disconnecting")

        self._running = False
        self.connected = False
        self._reset_session_state()

        if self.socket:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self.socket.close()
            except OSError:
                pass
            self.socket = None

        if was_connected and self.on_disconnect:
            self.on_disconnect()

    def send(self, data: bytes) -> bool:
        """
        Send raw bytes (already telnet-framed) to the server.

        Returns:
            True if sent successfully
        """
        with self._lock:
            if not self.socket or not self.connected:
                return False

            try:
                self.socket.sendall(data)
                logger.debug(f"Sent {len(data)} bytes: {data[:64].hex()}")
                return True
            except Exception as e:
                error_msg = f"Send failed: {e}"
                logger.error(error_msg)
        self._handle_error(error_msg)
        self.disconnect()
        return False

    # ----- outbound records --------------------------------------------------------------------------------------

    @staticmethod
    def frame(data: bytes) -> bytes:
        """Telnet-frame one record: double every 0xFF, append IAC EOR."""
        return data.replace(b'\xff', b'\xff\xff') + bytes([TELNET.IAC, TELNET.EOR])

    def build_tn3270e_header(self, data_type: int = TN3270E.DT_3270_DATA) -> bytes:
        """
        Build the TN3270E 5-byte header for an outbound record (and advance the sequence number).

        Args:
            data_type: 0x00 = 3270-DATA, 0x07 = SSCP-LU-DATA, ...
        """
        seq = self._sequence_number
        self._sequence_number = (self._sequence_number + 1) & TN3270E.SEQ_MASK
        return bytes([data_type, 0x00, TN3270E.RSF_NO_RESPONSE, (seq >> 8) & 0xFF, seq & 0xFF])

    def send_record(self, payload: bytes, data_type: Optional[int] = None) -> bool:
        """Send one inbound 3270 record (AID-first data, a query reply, SSCP-LU text, ...). In TN3270E mode the
        header is added: 3270-DATA, or SSCP-LU-DATA while the session is in SSCP-LU mode."""
        if self.tn3270e_mode:
            if data_type is None:
                data_type = TN3270E.DT_SSCP_LU_DATA if self.submode == 'sscp' else TN3270E.DT_3270_DATA
            payload = self.build_tn3270e_header(data_type) + payload
        return self.send(self.frame(payload))

    def respond(self, record: TN3270Record, pds: int) -> bool:
        """Answer a host record per its RESPONSE-FLAG (RFC 2355 section 10.4; x3270 tn3270e_ack/nak):
        ALWAYS-RESPONSE -> positive (DEVICE-END) on success; ERROR- or ALWAYS-RESPONSE -> negative on a bad
        command / address. Returns True if a response was sent."""
        if not self.tn3270e_mode or record.data_type not in (TN3270E.DT_3270_DATA, TN3270E.DT_NVT_DATA,
                                                              TN3270E.DT_SSCP_LU_DATA):
            return False
        flag = record.response_flag
        if pds < 0 and flag in (TN3270E.RSF_ERROR_RESPONSE, TN3270E.RSF_ALWAYS_RESPONSE):
            code = TN3270E.NEG_OPERATION_CHECK if pds == PDS.BAD_ADDR else TN3270E.NEG_COMMAND_REJECT
            rsp = bytes([TN3270E.DT_RESPONSE, 0x00, TN3270E.RSF_NEGATIVE_RESPONSE,
                         (record.seq >> 8) & 0xFF, record.seq & 0xFF, code])
        elif pds >= 0 and flag == TN3270E.RSF_ALWAYS_RESPONSE:
            rsp = bytes([TN3270E.DT_RESPONSE, 0x00, TN3270E.RSF_POSITIVE_RESPONSE,
                         (record.seq >> 8) & 0xFF, record.seq & 0xFF, TN3270E.POS_DEVICE_END])
        else:
            return False
        return self.send(self.frame(rsp))

    def send_sysreq(self) -> bool:
        """The SYSREQ key in TN3270E with the SYSREQ function: IAC AO (x3270 net_abort). False if not
        available (the caller then sends the 3270 test-request AID instead)."""
        if (self.tn3270e_mode and TN3270E.FUNC_SYSREQ in self.negotiated_functions
                and self.submode in ('sscp', '3270')):
            return self.send(bytes([TELNET.IAC, TELNET.AO]))
        return False

    # ----- receive -----------------------------------------------------------------------------------------------

    def _handle_error(self, error: str):
        """Handle and report errors."""
        self.connected = False
        if self.on_error:
            self.on_error(error)

    def _receive_loop(self):
        """Background thread to receive data from server."""
        logger.debug("Receive loop started")

        while self._running and self.socket:
            try:
                data = self.socket.recv(self.BUFFER_SIZE)
                if not data:
                    logger.info("Server closed connection")
                    self.disconnect()
                    break

                logger.debug(f"Received {len(data)} bytes")
                self.feed(data)

            except socket.timeout:
                continue
            except OSError as e:
                if self._running:
                    logger.error(f"Receive error: {e}")
                    self._handle_error(str(e))
                    self.disconnect()
                break
            except Exception as e:
                if self._running:
                    logger.exception(f"Unexpected receive error: {e}")
                    self._handle_error(str(e))
                    self.disconnect()
                break

        logger.debug("Receive loop ended")

    def feed(self, data: bytes):
        """Run received bytes through the telnet state machine."""
        for b in data:
            st = self._state
            if st == _DATA:
                if b == TELNET.IAC:
                    self._state = _IAC
                elif self.in_3270:
                    self._record.append(b)
                else:
                    self._nvt_byte(b)                       # text before 3270 mode (a banner): not a record
            elif st == _IAC:
                self._state = _DATA
                if b == TELNET.IAC:
                    if self.in_3270:
                        self._record.append(0xFF)           # escaped data byte
                    else:
                        self._nvt_byte(0xFF)
                elif b == TELNET.EOR:
                    rec, self._record = bytes(self._record), bytearray()
                    self._process_eor(rec)
                elif b == TELNET.WILL:
                    self._state = _WILL
                elif b == TELNET.WONT:
                    self._state = _WONT
                elif b == TELNET.DO:
                    self._state = _DO
                elif b == TELNET.DONT:
                    self._state = _DONT
                elif b == TELNET.SB:
                    self._sb = bytearray()
                    self._state = _SB
                else:
                    logger.debug(f"Telnet command {b:#04x} ignored")   # NOP, GA, DM, AYT, ...
            elif st in (_WILL, _WONT, _DO, _DONT):
                self._state = _DATA
                self._handle_option({_WILL: TELNET.WILL, _WONT: TELNET.WONT,
                                     _DO: TELNET.DO, _DONT: TELNET.DONT}[st], b)
            elif st == _SB:
                if b == TELNET.IAC:
                    self._state = _SB_IAC
                else:
                    self._sb.append(b)
            elif st == _SB_IAC:
                if b == TELNET.SE:
                    self._state = _DATA
                    self._handle_subnegotiation(bytes(self._sb))
                elif b == TELNET.IAC:
                    self._sb.append(0xFF)
                    self._state = _SB
                else:
                    logger.warning(f"Bad subnegotiation (IAC {b:#04x})")
                    self._state = _DATA

    @property
    def in_3270(self) -> bool:
        """3270 mode (x3270 IN_3270): TN3270E, or BINARY and EOR agreed in both directions. Until then incoming
        data is NVT text - e.g. a banner a server prints before negotiating - and must not become a record."""
        if self.tn3270e_mode:
            return True
        need = {TELNET_OPTIONS.BINARY, TELNET_OPTIONS.EOR}
        return need <= self._local_opts and need <= self._remote_opts

    def _nvt_byte(self, b: int):
        self.nvt_text.append(b)
        if b == 0x0A or len(self.nvt_text) >= 4096:
            logger.info(f"NVT text before 3270 mode: {bytes(self.nvt_text).decode('ascii', 'replace').rstrip()}")
            self.nvt_text.clear()

    # Compatibility: some callers fed buffers directly
    def _process_buffer(self):
        pass

    def _send_cmd(self, cmd: int, opt: int):
        self.send(bytes([TELNET.IAC, cmd, opt]))

    def _handle_option(self, cmd: int, opt: int):
        """DO/DONT/WILL/WONT, answering only state changes (no negotiation loops)."""
        logger.debug(f"Telnet command: {cmd:#04x} {TELNET_OPTIONS.get_name(opt)}")
        if cmd == TELNET.DO:
            if opt == TELNET_OPTIONS.TIMING_MARK:
                self._send_cmd(TELNET.WILL, opt)       # z/OS TIMEMARK keepalive (x3270 answers WILL)
            elif opt in self.SUPPORTED_OPTIONS:
                if opt not in self._local_opts:
                    self._local_opts.add(opt)
                    self._send_cmd(TELNET.WILL, opt)
                if opt == TELNET_OPTIONS.TN3270E:
                    self.tn3270e_mode = True
                    self.negotiation_complete = False
                    self.negotiated_functions = []
                    self._functions = list(self.REQUESTED_FUNCTIONS)
                    logger.info("TN3270E mode enabled")
                    self._state_changed()
            else:
                self._send_cmd(TELNET.WONT, opt)
        elif cmd == TELNET.DONT:
            if opt in self._local_opts:
                self._local_opts.discard(opt)
                self._send_cmd(TELNET.WONT, opt)
            if opt == TELNET_OPTIONS.TN3270E:
                self._tn3270e_off()
        elif cmd == TELNET.WILL:
            if opt in self.ACCEPTED_HOST_OPTIONS:
                if opt not in self._remote_opts:
                    self._remote_opts.add(opt)
                    self._send_cmd(TELNET.DO, opt)
            else:
                self._send_cmd(TELNET.DONT, opt)
        elif cmd == TELNET.WONT:
            if opt in self._remote_opts:
                self._remote_opts.discard(opt)
                self._send_cmd(TELNET.DONT, opt)

    def _handle_subnegotiation(self, sb: bytes):
        """Handle a subnegotiation (the bytes between IAC SB and IAC SE, un-escaped)."""
        if not sb:
            return
        opt = sb[0]
        if opt == TELNET_OPTIONS.TERMINAL_TYPE:
            if len(sb) > 1 and sb[1] == 0x01:  # SEND
                # plain TN3270 asks for an LU as "type@LU" (RFC 1646; x3270)
                ttype = self.TERMINAL_TYPE
                if self.lu_name:
                    ttype += b'@' + self.lu_name.encode('ascii', 'replace')
                logger.debug(f"Sending terminal type: {ttype.decode()}")
                self.send(bytes([TELNET.IAC, TELNET.SB, TELNET_OPTIONS.TERMINAL_TYPE, 0x00])
                          + ttype + bytes([TELNET.IAC, TELNET.SE]))
        elif opt == TELNET_OPTIONS.TN3270E:
            self._handle_tn3270e_subnegotiation(sb)

    def _send_device_type_request(self):
        body = bytes([TELNET.IAC, TELNET.SB, TELNET_OPTIONS.TN3270E, TN3270E.DEVICE_TYPE, TN3270E.REQUEST])
        body += self.TERMINAL_TYPE
        if self.lu_name:
            body += bytes([TN3270E.CONNECT]) + self.lu_name.encode('ascii', 'replace')
        self.send(body + bytes([TELNET.IAC, TELNET.SE]))

    def _send_functions(self, op: int, funcs) -> None:
        self.send(bytes([TELNET.IAC, TELNET.SB, TELNET_OPTIONS.TN3270E, TN3270E.FUNCTIONS, op])
                  + bytes(funcs) + bytes([TELNET.IAC, TELNET.SE]))

    def _complete(self, funcs) -> None:
        self.negotiated_functions = list(funcs)
        self.negotiation_complete = True
        if TN3270E.FUNC_BIND_IMAGE not in self.negotiated_functions:
            self.submode = '3270'                  # no BIND-IMAGE: straight to 3270 mode (x3270)
        logger.info(f"TN3270E negotiation complete, functions: {self.negotiated_functions}")
        self._state_changed()

    def _handle_tn3270e_subnegotiation(self, sb: bytes):
        """TN3270E subnegotiation (RFC 2355 section 7; x3270 tn3270e_negotiate). `sb` starts at the option."""
        if len(sb) < 3:
            return
        op = sb[1]

        if op == TN3270E.SEND:
            if sb[2] == TN3270E.DEVICE_TYPE:
                logger.debug("TN3270E: SEND DEVICE-TYPE")
                self._send_device_type_request()
            return

        if op == TN3270E.DEVICE_TYPE:
            if sb[2] == TN3270E.IS:
                rest = sb[3:]
                ttype, _, lu = rest.partition(bytes([TN3270E.CONNECT]))
                self.device_type = ttype.decode('ascii', 'replace') or None
                self.connected_lu = lu.decode('ascii', 'replace') or None
                logger.info(f"TN3270E: DEVICE-TYPE IS {self.device_type} CONNECT {self.connected_lu}")
                self._send_functions(TN3270E.REQUEST, self._functions)
                self._state_changed()
            elif sb[2] == TN3270E.REJECT:
                reason = sb[4] if len(sb) > 4 else None
                logger.warning(f"TN3270E: DEVICE-TYPE REJECT reason {reason}")
                self._backoff_tn3270e(f"device type rejected (reason {reason})")
            return

        if op == TN3270E.FUNCTIONS:
            received = list(sb[3:])
            if sb[2] == TN3270E.REQUEST:
                # The host's counter-proposal: accept it if it only removes functions, else ask for the overlap
                if set(received) <= set(self._functions):
                    self._functions = received
                    self._send_functions(TN3270E.IS, received)     # "exactly as it was received" (RFC 2355)
                    self._complete(received)
                else:
                    self._functions = [f for f in self._functions if f in received]
                    self._send_functions(TN3270E.REQUEST, self._functions)
            elif sb[2] == TN3270E.IS:
                if set(received) <= set(self._functions):
                    self._complete(received)
                else:
                    self._backoff_tn3270e("host added functions it was not asked for")
            return

    def _backoff_tn3270e(self, why: str):
        """Give up on TN3270E: tell the host WONT TN3270E so it falls back to plain TN3270 (x3270)."""
        logger.warning(f"Aborting TN3270E: {why}")
        self._local_opts.discard(TELNET_OPTIONS.TN3270E)
        self._send_cmd(TELNET.WONT, TELNET_OPTIONS.TN3270E)
        self._tn3270e_off()

    def _tn3270e_off(self):
        self.tn3270e_mode = False
        self.negotiation_complete = False
        self.negotiated_functions = []
        self.bound = False
        self.submode = 'unbound'
        self._state_changed()

    def _state_changed(self):
        if self.on_state:
            self.on_state()

    # ----- inbound records -----------------------------------------------------------------------------------------

    def _process_eor(self, rec: bytes):
        """A complete record arrived (IAC EOR): dispatch on the TN3270E data type."""
        if not rec:
            return
        if not self.tn3270e_mode:
            self._deliver(TN3270Record(TN3270E.DT_3270_DATA, 0, 0, 0, rec))
            return
        if len(rec) < TN3270E.HEADER_SIZE:
            logger.warning(f"TN3270E record shorter than its header: {rec.hex()}")
            return
        hdr, payload = rec[:TN3270E.HEADER_SIZE], rec[TN3270E.HEADER_SIZE:]
        r = TN3270Record(hdr[0], hdr[1], hdr[2], (hdr[3] << 8) | hdr[4], payload, hdr)
        funcs = self.negotiated_functions
        dt = r.data_type
        if dt == TN3270E.DT_3270_DATA:
            if TN3270E.FUNC_BIND_IMAGE in funcs and not self.bound:
                logger.warning("3270-DATA before BIND: ignored")
                return
            if self.submode != '3270':
                self.submode = '3270'
                self._state_changed()
            self._deliver(r)
        elif dt == TN3270E.DT_BIND_IMAGE:
            if TN3270E.FUNC_BIND_IMAGE in funcs:
                self.bound = True
                self._state_changed()
                self._deliver(r)
        elif dt == TN3270E.DT_UNBIND:
            if TN3270E.FUNC_BIND_IMAGE in funcs:
                self.bound = False
                self.submode = 'unbound'
                self._state_changed()
                self._deliver(r)
        elif dt == TN3270E.DT_SSCP_LU_DATA:
            if self.submode != 'sscp':
                self.submode = 'sscp'
                self._state_changed()
            self._deliver(r)
        elif dt == TN3270E.DT_NVT_DATA:
            if self.submode != 'nvt':
                self.submode = 'nvt'
                self._state_changed()
            self._deliver(r)
        else:
            logger.debug(f"TN3270E data type {dt:#04x} ignored")

    def _deliver(self, r: TN3270Record):
        if self.on_record:
            self.on_record(r)
        elif self.on_data:
            self.on_data(r.header + r.payload + bytes([TELNET.IAC, TELNET.EOR]))
