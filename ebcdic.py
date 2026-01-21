"""
EBCDIC to ASCII and ASCII to EBCDIC conversion tables
Based on Code Page 037 (US/Canada)

Copyright (C) 2026 Garland Glessner <gglessner@gmail.com>
License: GPL-3.0 (see LICENSE)
"""

# EBCDIC to ASCII lookup table (256 entries)
E2A = [
    '\x00', '\x01', '\x02', '\x03', '\x04', '\x05', '\x06', '\x07', '\x08', '\x09', '\x0A', '\x0B', '\x0C', '\x0D', '\x0E', '\x0F',
    '\x10', '\x11', '\x12', '\x13', '\x14', '\x15', '\x16', '\x17', '\x18', '\x19', '\x1A', '\x1B', '\x1C', '\x1D', '\x1E', '\x1F',
    '\x20', '\x21', '\x22', '\x23', '\x24', '\x25', '\x26', '\x27', '\x28', '\x29', '\x2A', '\x2B', '\x2C', '\x2D', '\x2E', '\x2F',
    '\x30', '\x31', '\x32', '\x33', '\x34', '\x35', '\x36', '\x37', '\x38', '\x39', '\x3A', '\x3B', '\x3C', '\x3D', '\x3E', '\x3F',
    ' ',    '\x41', '\x42', '\x43', '\x44', '\x45', '\x46', '\x47', '\x48', '\x49', '\xA2', '.',    '<',    '(',    '+',    '|',
    '&',    '\x51', '\x52', '\x53', '\x54', '\x55', '\x56', '\x57', '\x58', '\x59', '!',    '$',    '*',    ')',    ';',    '\xAC',
    '-',    '/',    '\x62', '\x63', '\x64', '\x65', '\x66', '\x67', '\x68', '\x69', '|',    ',',    '%',    '_',    '>',    '?',
    '\x70', '\x71', '\x72', '\x73', '\x74', '\x75', '\x76', '\x77', '\x78', '`',    ':',    '#',    '@',    "'",    '=',    '"',
    '\x80', 'a',    'b',    'c',    'd',    'e',    'f',    'g',    'h',    'i',    '\x8A', '\x8B', '\x8C', '\x8D', '\x8E', '\x8F',
    '\x90', 'j',    'k',    'l',    'm',    'n',    'o',    'p',    'q',    'r',    '\x9A', '\x9B', '\x9C', '\x9D', '\x9E', '\x9F',
    '\xA0', '~',    's',    't',    'u',    'v',    'w',    'x',    'y',    'z',    '\xAA', '\xAB', '\xAC', '\xAD', '\xAE', '\xAF',
    '\xB0', '\xB1', '\xB2', '\xB3', '\xB4', '\xB5', '\xB6', '\xB7', '\xB8', '\xB9', '\xBA', '\xBB', '\xBC', '\xBD', '\xBE', '\xBF',
    '{',    'A',    'B',    'C',    'D',    'E',    'F',    'G',    'H',    'I',    '\xCA', '\xCB', '\xCC', '\xCD', '\xCE', '\xCF',
    '}',    'J',    'K',    'L',    'M',    'N',    'O',    'P',    'Q',    'R',    '\xDA', '\xDB', '\xDC', '\xDD', '\xDE', '\xDF',
    '\\',   '\xE1', 'S',    'T',    'U',    'V',    'W',    'X',    'Y',    'Z',    '\xEA', '\xEB', '\xEC', '\xED', '\xEE', '\xEF',
    '0',    '1',    '2',    '3',    '4',    '5',    '6',    '7',    '8',    '9',    '\xFA', '\xFB', '\xFC', '\xFD', '\xFE', '\xFF',
]

# Build reverse lookup: ASCII to EBCDIC
A2E = {}
for i, char in enumerate(E2A):
    if char not in A2E:
        A2E[char] = i

# Add standard ASCII mappings
A2E.update({
    ' ': 0x40, '.': 0x4B, '<': 0x4C, '(': 0x4D, '+': 0x4E, '|': 0x4F,
    '&': 0x50, '!': 0x5A, '$': 0x5B, '*': 0x5C, ')': 0x5D, ';': 0x5E,
    '-': 0x60, '/': 0x61, ',': 0x6B, '%': 0x6C, '_': 0x6D, '>': 0x6E, '?': 0x6F,
    '`': 0x79, ':': 0x7A, '#': 0x7B, '@': 0x7C, "'": 0x7D, '=': 0x7E, '"': 0x7F,
    'a': 0x81, 'b': 0x82, 'c': 0x83, 'd': 0x84, 'e': 0x85, 'f': 0x86, 'g': 0x87, 'h': 0x88, 'i': 0x89,
    'j': 0x91, 'k': 0x92, 'l': 0x93, 'm': 0x94, 'n': 0x95, 'o': 0x96, 'p': 0x97, 'q': 0x98, 'r': 0x99,
    '~': 0xA1, 's': 0xA2, 't': 0xA3, 'u': 0xA4, 'v': 0xA5, 'w': 0xA6, 'x': 0xA7, 'y': 0xA8, 'z': 0xA9,
    '{': 0xC0, 'A': 0xC1, 'B': 0xC2, 'C': 0xC3, 'D': 0xC4, 'E': 0xC5, 'F': 0xC6, 'G': 0xC7, 'H': 0xC8, 'I': 0xC9,
    '}': 0xD0, 'J': 0xD1, 'K': 0xD2, 'L': 0xD3, 'M': 0xD4, 'N': 0xD5, 'O': 0xD6, 'P': 0xD7, 'Q': 0xD8, 'R': 0xD9,
    '\\': 0xE0, 'S': 0xE2, 'T': 0xE3, 'U': 0xE4, 'V': 0xE5, 'W': 0xE6, 'X': 0xE7, 'Y': 0xE8, 'Z': 0xE9,
    '0': 0xF0, '1': 0xF1, '2': 0xF2, '3': 0xF3, '4': 0xF4, '5': 0xF5, '6': 0xF6, '7': 0xF7, '8': 0xF8, '9': 0xF9,
})


def ebcdic_to_ascii(ebcdic_byte: int) -> str:
    """Convert single EBCDIC byte to ASCII character"""
    if 0 <= ebcdic_byte <= 255:
        char = E2A[ebcdic_byte]
        # Return space for non-printable characters
        if ord(char) < 0x20 or ord(char) > 0x7E:
            return ' '
        return char
    return ' '


def ascii_to_ebcdic(text: str) -> bytes:
    """Convert ASCII string to EBCDIC bytes"""
    result = []
    for char in text:
        if char in A2E:
            result.append(A2E[char])
        else:
            result.append(0x40)  # Default to space
    return bytes(result)


def ebcdic_bytes_to_ascii(data: bytes) -> str:
    """Convert EBCDIC bytes to ASCII string"""
    return ''.join(ebcdic_to_ascii(b) for b in data)
