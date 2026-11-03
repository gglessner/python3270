"""
TN3270 Order bytes and constants

Copyright (C) 2026 Garland Glessner <gglessner@gmail.com>
License: GPL-3.0 (see LICENSE)
"""

# 3270 Orders
class ORDERS:
    SF = 0x1D   # Start Field
    SFE = 0x29  # Start Field Extended
    SBA = 0x11  # Set Buffer Address
    SA = 0x28   # Set Attribute
    MF = 0x2C   # Modify Field
    IC = 0x13   # Insert Cursor
    PT = 0x05   # Program Tab
    RA = 0x3C   # Repeat to Address
    EUA = 0x12  # Erase Unprotected to Address
    GE = 0x08   # Graphic Escape


# Write commands - SNA/LU2 format (most common)
class WRITE_COMMANDS:
    WRITE = 0xF1
    ERASE_WRITE = 0xF5
    ERASE_WRITE_ALTERNATE = 0x7E
    WRITE_STRUCTURED_FIELD = 0xF3
    ERASE_ALL_UNPROTECTED = 0x6F


# Write commands - CCW (Channel Command Word) format
# Some servers use these older command codes
class WRITE_COMMANDS_CCW:
    WRITE = 0x01
    ERASE_WRITE = 0x05
    ERASE_WRITE_ALTERNATE = 0x0D
    READ_BUFFER = 0x02
    READ_MODIFIED = 0x06
    ERASE_ALL_UNPROTECTED = 0x0F


# All valid write commands (both SNA and CCW formats)
ALL_WRITE_COMMANDS = {
    # SNA format
    0xF1: 'WRITE',
    0xF5: 'ERASE_WRITE',
    0x7E: 'ERASE_WRITE_ALTERNATE',
    0xF3: 'WRITE_STRUCTURED_FIELD',
    0x6F: 'ERASE_ALL_UNPROTECTED',
    # CCW format
    0x01: 'WRITE',
    0x05: 'ERASE_WRITE',
    0x0D: 'ERASE_WRITE_ALTERNATE',
    0x0F: 'ERASE_ALL_UNPROTECTED',
}

# Erase commands (clear screen before write)
ERASE_COMMANDS = {0xF5, 0x7E, 0x05, 0x0D}


# Every 3270 command a host can send, SNA and CCW codes (IBM GA23-0059; x3270 3270ds.h). The read commands
# (RB/RM/RMA) need an answer from us; ignoring them leaves the host waiting forever.
class COMMANDS:
    W = (0xF1, 0x01)                # write
    EW = (0xF5, 0x05)               # erase/write
    EWA = (0x7E, 0x0D)              # erase/write alternate
    EAU = (0x6F, 0x0F)              # erase all unprotected
    WSF = (0xF3, 0x11)              # write structured field
    RB = (0xF2, 0x02)               # read buffer
    RM = (0xF6, 0x06)               # read modified
    RMA = (0x6E, 0x0E)              # read modified all
    NOP = (0x03,)                   # no-op


# Write Control Character bits
class WCC:
    RESET = 0x40
    START_PRINTER = 0x08
    SOUND_ALARM = 0x04
    KEYBOARD_RESTORE = 0x02
    RESET_MDT = 0x01


# Format control orders: stored in the buffer like data (x3270 ctlr_write)
FORMAT_CONTROLS = frozenset([0x00, 0x0C, 0x0D, 0x15, 0x19, 0x1C, 0x1E, 0x25, 0x3F, 0xFF])


# Structured fields (outbound, host -> terminal)
class SF:
    READ_PART = 0x01
    ERASE_RESET = 0x03
    SET_REPLY_MODE = 0x09
    CREATE_PART = 0x0C
    OUTBOUND_DS = 0x40
    # Read Partition types
    RP_QUERY = 0x02
    RP_QLIST = 0x03
    # Query List request types
    RPQ_LIST = 0x00
    RPQ_EQUIV = 0x40
    RPQ_ALL = 0x80
    # Erase/Reset
    ER_DEFAULT = 0x00
    ER_ALT = 0x80
    # Reply modes
    SRM_FIELD = 0x00
    SRM_XFIELD = 0x01
    SRM_CHAR = 0x02


# Special AIDs
AID_NO = 0x60                       # no AID yet (the reply AID for a host Read before any key)
AID_QREPLY = 0x61                   # Read Partition RB/RM/RMA
AID_SF = 0x88                       # structured field (query reply)


# Result of processing one host data stream record (x3270 enum pds)
class PDS:
    OKAY_NO_OUTPUT = 0              # processed; nothing was sent
    OKAY_OUTPUT = 1                 # processed; a reply (read / query) was sent
    BAD_CMD = -1                    # unknown command / structured field
    BAD_ADDR = -2                   # buffer address out of range / record too short


# Attention Identifiers (AIDs)
AIDS = {
    'ENTER': 0x7D,
    'PF1': 0xF1, 'PF2': 0xF2, 'PF3': 0xF3, 'PF4': 0xF4,
    'PF5': 0xF5, 'PF6': 0xF6, 'PF7': 0xF7, 'PF8': 0xF8,
    'PF9': 0xF9, 'PF10': 0x7A, 'PF11': 0x7B, 'PF12': 0x7C,
    'PF13': 0xC1, 'PF14': 0xC2, 'PF15': 0xC3, 'PF16': 0xC4,
    'PF17': 0xC5, 'PF18': 0xC6, 'PF19': 0xC7, 'PF20': 0xC8,
    'PF21': 0xC9, 'PF22': 0x4A, 'PF23': 0x4B, 'PF24': 0x4C,
    'PA1': 0x6C, 'PA2': 0x6E, 'PA3': 0x6B,
    'CLEAR': 0x6D,
    'SYSREQ': 0xF0,
}
# (ATTN is not an AID: it is a telnet signal - see TN3270Session.send_attn.)


# Telnet constants
class TELNET:
    IAC = 0xFF
    DONT = 0xFE
    DO = 0xFD
    WONT = 0xFC
    WILL = 0xFB
    SB = 0xFA
    GA = 0xF9
    EL = 0xF8
    EC = 0xF7
    AYT = 0xF6
    AO = 0xF5                       # abort output: the TN3270E SYSREQ key (x3270 net_abort)
    IP = 0xF4
    BRK = 0xF3
    DM = 0xF2
    NOP = 0xF1
    SE = 0xF0
    EOR = 0xEF


# Telnet options
class TELNET_OPTIONS:
    BINARY = 0x00
    TIMING_MARK = 0x06              # z/OS TN3270 TIMEMARK keepalive: must be answered
    TERMINAL_TYPE = 0x18
    EOR = 0x19
    TN3270E = 0x28

    _NAMES = {
        0x00: 'BINARY',
        0x06: 'TIMING-MARK',
        0x18: 'TERMINAL-TYPE',
        0x19: 'EOR',
        0x28: 'TN3270E',
    }
    
    @classmethod
    def get_name(cls, opt: int) -> str:
        """Get human-readable name for telnet option."""
        return cls._NAMES.get(opt, f'UNKNOWN({opt:#04x})')


# TN3270E subnegotiation
class TN3270E:
    ASSOCIATE = 0x00
    CONNECT = 0x01
    DEVICE_TYPE = 0x02
    FUNCTIONS = 0x03
    IS = 0x04
    REASON = 0x05
    REJECT = 0x06
    REQUEST = 0x07
    SEND = 0x08
    
    # Functions
    FUNC_BIND_IMAGE = 0x00
    FUNC_DATA_STREAM_CTL = 0x02
    FUNC_RESPONSES = 0x04
    FUNC_SYSREQ = 0x05

    # DEVICE-TYPE REJECT reason codes (RFC 2355)
    REASON_CONN_PARTNER = 0x00
    REASON_DEVICE_IN_USE = 0x01
    REASON_INV_ASSOCIATE = 0x02
    REASON_INV_DEVICE_NAME = 0x03
    REASON_INV_DEVICE_TYPE = 0x04
    REASON_TYPE_NAME_ERROR = 0x05
    REASON_UNKNOWN_ERROR = 0x06
    REASON_UNSUPPORTED_REQ = 0x07

    # Header data types
    DT_3270_DATA = 0x00
    DT_SCS_DATA = 0x01
    DT_RESPONSE = 0x02
    DT_BIND_IMAGE = 0x03
    DT_UNBIND = 0x04
    DT_NVT_DATA = 0x05
    DT_REQUEST = 0x06
    DT_SSCP_LU_DATA = 0x07
    DT_PRINT_EOJ = 0x08

    # Header response flags (3270-DATA from the host / RESPONSE from us)
    RSF_NO_RESPONSE = 0x00
    RSF_ERROR_RESPONSE = 0x01
    RSF_ALWAYS_RESPONSE = 0x02
    RSF_POSITIVE_RESPONSE = 0x00
    RSF_NEGATIVE_RESPONSE = 0x01
    # Header request flag
    RQF_KEYBOARD_RESTORE = 0x02     # (DATA-STREAM-CTL) unlock the keyboard after this record
    # RESPONSE data byte
    POS_DEVICE_END = 0x00
    NEG_COMMAND_REJECT = 0x00
    NEG_INTERVENTION_REQUIRED = 0x01
    NEG_OPERATION_CHECK = 0x02
    NEG_COMPONENT_DISCONNECTED = 0x03

    HEADER_SIZE = 5
    SEQ_MASK = 0x7FFF               # RFC 2355: the counter wraps to zero after 32767


# Extended attribute types
class ATTR_TYPES:
    ALL = 0x00
    T3270 = 0xC0
    VALIDATION = 0xC1
    OUTLINING = 0xC2
    HIGHLIGHTING = 0x41
    FOREGROUND_COLOR = 0x42
    CHARSET = 0x43
    BACKGROUND_COLOR = 0x45
    TRANSPARENCY = 0x46


# Field attribute bit masks
class FIELD_ATTR:
    PROTECTED = 0x20      # Bit 2
    NUMERIC = 0x10        # Bit 3
    DISPLAY_MASK = 0x0C   # Bits 4-5
    MDT = 0x01            # Bit 7 (Modified Data Tag)


def get_default_field_color(attr: int) -> str:
    """
    Get default color based on field attributes (for screens without explicit colors)
    Classic 3270 color mapping:
    - Protected + Intensified = White
    - Protected + Normal = Blue
    - Unprotected + Intensified = Red
    - Unprotected + Normal = Green
    """
    is_protected = (attr & FIELD_ATTR.PROTECTED) != 0
    display = attr & FIELD_ATTR.DISPLAY_MASK
    is_intensified = display == 0x08
    is_hidden = display == 0x0C
    
    if is_hidden:
        return 'green'  # Hidden fields don't matter
    
    if is_protected:
        return 'white' if is_intensified else 'blue'
    else:
        return 'red' if is_intensified else 'green'


# Colors
COLORS = {
    0xF0: 'default',
    0xF1: 'blue',
    0xF2: 'red',
    0xF3: 'pink',
    0xF4: 'green',
    0xF5: 'turquoise',
    0xF6: 'yellow',
    0xF7: 'white',
}


# Highlighting
HIGHLIGHTS = {
    0xF0: 'normal',
    0xF1: 'blink',
    0xF2: 'reverse',
    0xF4: 'underscore',
}


# 12-bit address encoding table
ADDR_TABLE = [
    0x40, 0xC1, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7,
    0xC8, 0xC9, 0x4A, 0x4B, 0x4C, 0x4D, 0x4E, 0x4F,
    0x50, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7,
    0xD8, 0xD9, 0x5A, 0x5B, 0x5C, 0x5D, 0x5E, 0x5F,
    0x60, 0x61, 0xE2, 0xE3, 0xE4, 0xE5, 0xE6, 0xE7,
    0xE8, 0xE9, 0x6A, 0x6B, 0x6C, 0x6D, 0x6E, 0x6F,
    0xF0, 0xF1, 0xF2, 0xF3, 0xF4, 0xF5, 0xF6, 0xF7,
    0xF8, 0xF9, 0x7A, 0x7B, 0x7C, 0x7D, 0x7E, 0x7F,
]

# Reverse lookup for decoding
ADDR_DECODE = {v: i for i, v in enumerate(ADDR_TABLE)}


def decode_buffer_address(b1: int, b2: int) -> int:
    """Decode 2-byte buffer address to screen position (x3270 DECODE_BADDR).

    14-bit addressing when the top two bits of the first byte are 00 (the query reply advertises 12/14-bit
    addressing, so a host may use it). Otherwise 12-bit: the low six bits of each byte, whatever the graphic in
    the top two - lenient like x3270, where a table lookup would turn an unexpected code byte into address 0."""
    if (b1 & 0xC0) == 0x00:
        return ((b1 & 0x3F) << 8) | b2
    return ((b1 & 0x3F) << 6) | (b2 & 0x3F)


def encode_buffer_address(addr: int) -> bytes:
    """Encode screen position to 2-byte buffer address"""
    high = (addr >> 6) & 0x3F
    low = addr & 0x3F
    return bytes([ADDR_TABLE[high], ADDR_TABLE[low]])
