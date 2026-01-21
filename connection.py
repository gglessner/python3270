"""
TN3270 Connection Handler
Manages TCP connection and TN3270E negotiation

Copyright (C) 2026 Garland Glessner <gglessner@gmail.com>
License: GPL-3.0 (see LICENSE)
"""

import socket
import ssl
import threading
import logging
from typing import Callable, Optional, List

try:
    from .orders import TELNET, TELNET_OPTIONS, TN3270E
except ImportError:
    from orders import TELNET, TELNET_OPTIONS, TN3270E

# Set up logging
logger = logging.getLogger(__name__)


class TN3270Connection:
    """TN3270 TCP connection with TN3270E protocol negotiation"""
    
    TERMINAL_TYPE = b'IBM-3278-2-E'
    BUFFER_SIZE = 65536
    CONNECT_TIMEOUT = 30
    
    # Supported Telnet options
    SUPPORTED_OPTIONS = frozenset([
        TELNET_OPTIONS.BINARY,
        TELNET_OPTIONS.EOR,
        TELNET_OPTIONS.TN3270E,
        TELNET_OPTIONS.TERMINAL_TYPE,
    ])
    
    def __init__(self):
        self.socket: Optional[socket.socket] = None
        self.connected: bool = False
        self.tn3270e_mode: bool = False
        self.negotiation_complete: bool = False
        self.negotiated_functions: List[int] = []
        
        # TN3270E sequence number for outbound data
        self._sequence_number: int = 0
        
        # Callbacks
        self.on_data: Optional[Callable[[bytes], None]] = None
        self.on_connect: Optional[Callable[[], None]] = None
        self.on_disconnect: Optional[Callable[[], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        
        # Internal state
        self._receive_thread: Optional[threading.Thread] = None
        self._buffer: bytes = b''
        self._running: bool = False
        self._lock = threading.Lock()
    
    def connect(self, host: str, port: int, use_tls: bool = False) -> bool:
        """
        Connect to TN3270 server.
        
        Args:
            host: Server hostname or IP address
            port: Server port number
            use_tls: Enable TLS encryption
            
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
            self._sequence_number = 0
            
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
        logger.info("Disconnecting")
        
        self._running = False
        self.connected = False
        self.tn3270e_mode = False
        self.negotiation_complete = False
        self.negotiated_functions = []
        self._sequence_number = 0
        self._buffer = b''
        
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
        
        if self.on_disconnect:
            self.on_disconnect()
    
    def send(self, data: bytes) -> bool:
        """
        Send data to server.
        
        Args:
            data: Raw bytes to send
            
        Returns:
            True if sent successfully
        """
        with self._lock:
            if not self.socket or not self.connected:
                return False
            
            try:
                self.socket.sendall(data)
                logger.debug(f"Sent {len(data)} bytes")
                return True
            except Exception as e:
                error_msg = f"Send failed: {e}"
                logger.error(error_msg)
                self._handle_error(error_msg)
                self.disconnect()
                return False
    
    def build_tn3270e_header(self, data_type: int = 0x00) -> bytes:
        """
        Build TN3270E 5-byte header for outbound data.
        
        Args:
            data_type: 0x00 = 3270-DATA, 0x01 = SCS-DATA, 0x02 = RESPONSE
            
        Returns:
            5-byte TN3270E header
        """
        # Increment and wrap sequence number
        seq = self._sequence_number
        self._sequence_number = (self._sequence_number + 1) & 0xFFFF
        
        return bytes([
            data_type,      # Data type
            0x00,           # Request flag
            0x00,           # Response flag
            (seq >> 8) & 0xFF,  # Sequence high byte
            seq & 0xFF,     # Sequence low byte
        ])
    
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
                self._buffer += data
                self._process_buffer()
                
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
                    logger.error(f"Unexpected receive error: {e}")
                    self._handle_error(str(e))
                    self.disconnect()
                break
        
        logger.debug("Receive loop ended")
    
    def _process_buffer(self):
        """Process received data buffer, handling Telnet commands and 3270 records."""
        while len(self._buffer) > 0:
            # Check for Telnet IAC command
            if self._buffer[0] == TELNET.IAC and len(self._buffer) >= 2:
                cmd = self._buffer[1]
                
                # Handle 3-byte commands: DO, DONT, WILL, WONT
                if cmd in (TELNET.DO, TELNET.DONT, TELNET.WILL, TELNET.WONT):
                    if len(self._buffer) >= 3:
                        self._handle_telnet_command(self._buffer[:3])
                        self._buffer = self._buffer[3:]
                        continue
                    else:
                        break  # Need more data
                
                # Handle subnegotiation: IAC SB ... IAC SE
                if cmd == TELNET.SB:
                    se_index = self._find_subneg_end()
                    if se_index != -1:
                        self._handle_subnegotiation(self._buffer[:se_index + 2])
                        self._buffer = self._buffer[se_index + 2:]
                        continue
                    else:
                        break  # Need more data
                
                # Handle standalone IAC EOR
                if cmd == TELNET.EOR:
                    self._buffer = self._buffer[2:]
                    continue
                
                # Handle IAC IAC (escaped 0xFF)
                if cmd == TELNET.IAC:
                    self._buffer = self._buffer[1:]  # Keep one IAC
                    continue
            
            # Look for 3270 data record (ending with IAC EOR)
            eor_index = self._find_eor()
            if eor_index != -1:
                record = self._buffer[:eor_index + 2]
                self._buffer = self._buffer[eor_index + 2:]
                
                # Check for Read Partition Query and respond automatically
                if self._is_query_request(record):
                    logger.debug("Responding to Read Partition Query")
                    self._send_query_reply()
                    continue
                
                # Deliver data to callback
                if self.on_data:
                    self.on_data(record)
            else:
                break  # Need more data
    
    def _find_subneg_end(self) -> int:
        """Find IAC SE sequence in buffer."""
        for i in range(2, len(self._buffer) - 1):
            if self._buffer[i] == TELNET.IAC and self._buffer[i + 1] == TELNET.SE:
                return i
        return -1
    
    def _find_eor(self) -> int:
        """Find IAC EOR sequence in buffer."""
        for i in range(len(self._buffer) - 1):
            if self._buffer[i] == TELNET.IAC and self._buffer[i + 1] == TELNET.EOR:
                return i
        return -1
    
    def _handle_telnet_command(self, packet: bytes):
        """Handle Telnet DO/DONT/WILL/WONT commands."""
        cmd = packet[1]
        opt = packet[2]
        
        opt_name = TELNET_OPTIONS.get_name(opt)
        logger.debug(f"Telnet command: {cmd:#04x} {opt_name}")
        
        # Respond to DO with WILL for supported options
        if cmd == TELNET.DO:
            if opt in self.SUPPORTED_OPTIONS:
                self.send(bytes([TELNET.IAC, TELNET.WILL, opt]))
                if opt == TELNET_OPTIONS.TN3270E:
                    self.tn3270e_mode = True
                    logger.info("TN3270E mode enabled")
            else:
                self.send(bytes([TELNET.IAC, TELNET.WONT, opt]))
        
        # Respond to WILL with DO for supported options
        elif cmd == TELNET.WILL:
            if opt in self.SUPPORTED_OPTIONS:
                self.send(bytes([TELNET.IAC, TELNET.DO, opt]))
            else:
                self.send(bytes([TELNET.IAC, TELNET.DONT, opt]))
        
        # Handle DONT/WONT
        elif cmd == TELNET.DONT:
            self.send(bytes([TELNET.IAC, TELNET.WONT, opt]))
            if opt == TELNET_OPTIONS.TN3270E:
                self.tn3270e_mode = False
        elif cmd == TELNET.WONT:
            self.send(bytes([TELNET.IAC, TELNET.DONT, opt]))
    
    def _handle_subnegotiation(self, packet: bytes):
        """Handle Telnet subnegotiation."""
        if len(packet) < 4:
            return
        
        opt = packet[2]
        
        # Terminal-Type subnegotiation
        if opt == TELNET_OPTIONS.TERMINAL_TYPE:
            if len(packet) > 3 and packet[3] == 0x01:  # SEND
                logger.debug(f"Sending terminal type: {self.TERMINAL_TYPE.decode()}")
                response = bytes([TELNET.IAC, TELNET.SB, TELNET_OPTIONS.TERMINAL_TYPE, 0x00])
                response += self.TERMINAL_TYPE
                response += bytes([TELNET.IAC, TELNET.SE])
                self.send(response)
            return
        
        # TN3270E subnegotiation
        if opt == TELNET_OPTIONS.TN3270E:
            self._handle_tn3270e_subnegotiation(packet)
    
    def _handle_tn3270e_subnegotiation(self, packet: bytes):
        """Handle TN3270E-specific subnegotiation."""
        if len(packet) < 5:
            return
        
        sub_cmd = packet[3]
        
        # SEND DEVICE-TYPE
        if sub_cmd == TN3270E.SEND and len(packet) > 4 and packet[4] == TN3270E.DEVICE_TYPE:
            logger.debug("TN3270E: Sending device type request")
            response = bytes([
                TELNET.IAC, TELNET.SB, TELNET_OPTIONS.TN3270E,
                TN3270E.DEVICE_TYPE, TN3270E.REQUEST
            ])
            response += self.TERMINAL_TYPE
            response += bytes([TELNET.IAC, TELNET.SE])
            self.send(response)
            return
        
        # DEVICE-TYPE IS (server accepted our device type)
        if sub_cmd == TN3270E.DEVICE_TYPE and len(packet) > 4 and packet[4] == TN3270E.IS:
            logger.debug("TN3270E: Device type accepted, sending functions request")
            response = bytes([
                TELNET.IAC, TELNET.SB, TELNET_OPTIONS.TN3270E,
                TN3270E.FUNCTIONS, TN3270E.REQUEST,
                TN3270E.FUNC_BIND_IMAGE,
                TN3270E.FUNC_RESPONSES,
                TN3270E.FUNC_SYSREQ,
                TELNET.IAC, TELNET.SE
            ])
            self.send(response)
            return
        
        # FUNCTIONS IS (server confirmed functions)
        if sub_cmd == TN3270E.FUNCTIONS and len(packet) > 4 and packet[4] == TN3270E.IS:
            self.negotiated_functions = list(packet[5:-2])
            self.negotiation_complete = True
            logger.info(f"TN3270E negotiation complete, functions: {self.negotiated_functions}")
            return
        
        # REJECT (server rejected TN3270E)
        if sub_cmd == TN3270E.REJECT:
            logger.warning("TN3270E: Server rejected TN3270E, falling back to TN3270")
            self.tn3270e_mode = False
            return
    
    def _is_query_request(self, record: bytes) -> bool:
        """
        Check if record is a Read Partition Query that needs automatic response.
        
        Args:
            record: 3270 data record (may include TN3270E header and IAC EOR)
            
        Returns:
            True if this is a Query request requiring automatic response
        """
        # Remove IAC EOR at end if present
        if len(record) >= 2 and record[-2] == TELNET.IAC and record[-1] == TELNET.EOR:
            data = record[:-2]
        else:
            data = record
        
        # Skip TN3270E header if present
        offset = 0
        if self.tn3270e_mode and len(data) >= 5 and data[0] == 0x00:
            offset = 5
        
        if offset >= len(data):
            return False
        
        # Check for Write Structured Field (0xF3)
        if data[offset] == 0xF3:
            offset += 1  # Skip WSF command
            if offset + 2 < len(data):
                # Get structured field ID (after 2-byte length)
                sf_id = data[offset + 2]
                # SF ID 0x01 = Read Partition Query
                if sf_id == 0x01:
                    return True
        
        return False
    
    def _send_query_reply(self):
        """Send Query Reply response for Read Partition Query."""
        parts = bytearray()
        
        # TN3270E header if needed
        if self.tn3270e_mode:
            parts.extend(self.build_tn3270e_header(0x00))  # 3270-DATA
        
        # AID for Structured Field
        parts.append(0x88)
        
        # Query Reply Summary (lists all supported query reply types)
        parts.extend([
            0x00, 0x0E,  # Length: 14 bytes
            0x81, 0x80,  # Query Reply Summary
            0x80,        # Summary
            0x81,        # Usable Area
            0x84,        # Alphanumeric Partitions
            0x85,        # Character Sets
            0x86,        # Color
            0x87,        # Highlighting
            0x88,        # Reply Modes
            0x95,        # DDM
            0xA1,        # RPQ Names
            0xA6,        # Implicit Partition
        ])
        
        # Query Reply Usable Area (24x80 display)
        parts.extend([
            0x00, 0x17,  # Length: 23 bytes
            0x81, 0x81,  # Usable Area
            0x01,        # 12/14 bit addressing
            0x00, 0x00, 0x50, 0x00,  # Width in cells (80)
            0x18,        # Height in cells (24)
            0x01, 0x00, 0x0A,  # Units, X units, Y units
            0x02, 0xE5, 0x00, 0x02, 0x00, 0x6F,  # X/Y size
            0x09, 0x0C, 0x0A, 0x00, 0x00  # Buffer size
        ])
        
        # Query Reply Alphanumeric Partitions
        parts.extend([
            0x00, 0x08,
            0x81, 0x84,
            0x00, 0x0A, 0x00, 0x00
        ])
        
        # Query Reply Character Sets
        parts.extend([
            0x00, 0x1B,
            0x81, 0x85,
            0x82, 0x00, 0x09, 0x0C, 0x00, 0x00, 0x00, 0x00,
            0x07, 0x00, 0x10, 0x00, 0x02, 0xB9, 0x00, 0x25,
            0x01, 0x00, 0xF1, 0x03, 0xC3, 0x01, 0x36
        ])
        
        # Query Reply Color (16 color support)
        parts.extend([
            0x00, 0x26,
            0x81, 0x86,
            0x00, 0x10, 0x00,  # Flags and color pairs
            0xF4, 0xF1, 0xF1, 0xF2, 0xF2, 0xF3, 0xF3, 0xF4, 0xF4,
            0xF5, 0xF5, 0xF6, 0xF6, 0xF7, 0xF7, 0xF8, 0xF8,
            0xF9, 0xF9, 0xFA, 0xFA, 0xFB, 0xFB, 0xFC, 0xFC,
            0xFD, 0xFD, 0xFE, 0xFE, 0xFF, 0xFF, 0xFF, 0xFF
        ])
        
        # Query Reply Highlighting
        parts.extend([
            0x00, 0x0F,
            0x81, 0x87,
            0x05,  # Number of pairs
            0x00, 0xF0,  # Default
            0xF1, 0xF1,  # Blink
            0xF2, 0xF2,  # Reverse
            0xF4, 0xF4,  # Underscore
            0xF8, 0xF8,  # Intensify
        ])
        
        # Query Reply Reply Modes
        parts.extend([
            0x00, 0x07,
            0x81, 0x88,
            0x00, 0x01, 0x02  # Field, Extended Field, Character modes
        ])
        
        # Query Reply Implicit Partition
        parts.extend([
            0x00, 0x11,
            0x81, 0xA6,
            0x00, 0x00, 0x0B, 0x01,
            0x00, 0x00, 0x50, 0x00,  # Width
            0x18,                     # Height
            0x00, 0x50, 0x00, 0x20    # Alt size
        ])
        
        # IAC EOR
        parts.extend([TELNET.IAC, TELNET.EOR])
        
        self.send(bytes(parts))
        logger.debug(f"Sent Query Reply: {len(parts)} bytes")
