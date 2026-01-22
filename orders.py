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
    'ATTN': 0x00,
}


# Telnet constants
class TELNET:
    IAC = 0xFF
    DONT = 0xFE
    DO = 0xFD
    WONT = 0xFC
    WILL = 0xFB
    SB = 0xFA
    SE = 0xF0
    EOR = 0xEF


# Telnet options
class TELNET_OPTIONS:
    BINARY = 0x00
    TERMINAL_TYPE = 0x18
    EOR = 0x19
    TN3270E = 0x28
    
    _NAMES = {
        0x00: 'BINARY',
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
    
    # Header for 3270 data (data-type=0x00, request=0x00, response=0x00, seq=0x0000, data-type-indicator=0x01)
    HEADER = bytes([0x00, 0x00, 0x00, 0x00, 0x01])


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
    """Decode 2-byte buffer address to screen position"""
    # Check for 14-bit addressing (high bit set)
    if b1 & 0xC0 == 0x00:
        return ((b1 & 0x3F) << 8) | b2
    
    # 12-bit addressing
    high = ADDR_DECODE.get(b1, 0)
    low = ADDR_DECODE.get(b2, 0)
    return (high << 6) | low


def encode_buffer_address(addr: int) -> bytes:
    """Encode screen position to 2-byte buffer address"""
    high = (addr >> 6) & 0x3F
    low = addr & 0x3F
    return bytes([ADDR_TABLE[high], ADDR_TABLE[low]])
