"""
3270 Screen Buffer Model
Manages the 24x80 character screen and field tracking

Copyright (C) 2026 Garland Glessner <gglessner@gmail.com>
License: GPL-3.0 (see LICENSE)
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)
try:
    from .ebcdic import ebcdic_to_ascii
    from .orders import (
        ORDERS, WRITE_COMMANDS, WRITE_COMMANDS_CCW, ALL_WRITE_COMMANDS, ERASE_COMMANDS,
        decode_buffer_address, ATTR_TYPES, COLORS, HIGHLIGHTS, get_default_field_color
    )
except ImportError:
    from ebcdic import ebcdic_to_ascii
    from orders import (
        ORDERS, WRITE_COMMANDS, WRITE_COMMANDS_CCW, ALL_WRITE_COMMANDS, ERASE_COMMANDS,
        decode_buffer_address, ATTR_TYPES, COLORS, HIGHLIGHTS, get_default_field_color
    )


@dataclass
class Cell:
    """Single screen cell"""
    char: str = ' '
    is_field_start: bool = False
    is_protected: bool = False
    is_numeric: bool = False
    is_hidden: bool = False
    is_intensified: bool = False
    is_modified: bool = False
    color: str = 'green'
    highlight: str = 'normal'
    background: str = 'default'


@dataclass
class Field:
    """Field definition"""
    start_pos: int
    attr_byte: int
    is_protected: bool = False
    is_numeric: bool = False
    is_hidden: bool = False
    is_intensified: bool = False
    is_modified: bool = False
    color: str = 'green'
    highlight: str = 'normal'


class ScreenBuffer:
    """24x80 3270 screen buffer"""
    
    ROWS = 24
    COLS = 80
    SIZE = ROWS * COLS  # 1920
    
    def __init__(self):
        self.cells: List[Cell] = [Cell() for _ in range(self.SIZE)]
        self.fields: List[Field] = []
        self.cursor_pos: int = 0
        self.tn3270e: bool = False
        self.current_color: str = 'green'
        self.current_highlight: str = 'normal'
        self.current_background: str = 'default'
    
    def clear(self):
        """Clear the screen"""
        self.cells = [Cell() for _ in range(self.SIZE)]
        self.fields = []
        self.cursor_pos = 0
        self.current_color = 'green'
        self.current_highlight = 'normal'
        self.current_background = 'default'
    
    def get_row_col(self, pos: int) -> tuple:
        """Convert position to row, col (0-based)"""
        return pos // self.COLS, pos % self.COLS
    
    def get_pos(self, row: int, col: int) -> int:
        """Convert row, col to position"""
        return row * self.COLS + col
    
    def process_data(self, data: bytes, tn3270e_mode: bool = None):
        """
        Process incoming 3270 data stream.
        
        Args:
            data: Raw 3270 data (may include TN3270E header and IAC EOR)
            tn3270e_mode: If True, expect 5-byte TN3270E header. If None, auto-detect.
        """
        if len(data) < 3:
            return
        
        # Skip IAC EOR at end if present (do this first)
        if len(data) >= 2 and data[-2] == 0xFF and data[-1] == 0xEF:
            data = data[:-2]
        
        if len(data) < 1:
            return
        
        offset = 0
        
        # Valid 3270 orders (for detecting order-only streams)
        # Note: 0x05 (PT) is NOT included here because it's also CCW Erase/Write command
        VALID_ORDERS = (0x1D, 0x29, 0x11, 0x28, 0x2C, 0x13, 0x3C, 0x12, 0x08)
        
        # Determine if this is TN3270E data by checking specific positions
        # Write commands can only be at offset 0 (raw) or offset 5 (after TN3270E header)
        # We must NOT scan the TN3270E header bytes (0-4) as they may contain values
        # that match command codes (e.g., 0x01 in REQUEST field = CCW Write)
        write_cmd_offset = None
        
        # Check offset 5 first (TN3270E mode) - more common
        if len(data) > 5 and data[5] in ALL_WRITE_COMMANDS:
            write_cmd_offset = 5
        # Check offset 0 (raw 3270 data, no TN3270E header)
        elif len(data) > 0 and data[0] in ALL_WRITE_COMMANDS:
            write_cmd_offset = 0
        
        # If no write command found, check for order-only streams
        orders_only_offset = None
        if write_cmd_offset is None:
            # Check at offset 5 (after TN3270E header) or offset 0
            if len(data) > 5 and data[5] in VALID_ORDERS:
                orders_only_offset = 5
            elif len(data) > 0 and data[0] in VALID_ORDERS:
                orders_only_offset = 0
        
        # Determine starting offset
        if write_cmd_offset is not None:
            offset = write_cmd_offset
            self.tn3270e = (write_cmd_offset == 5)
            logger.debug(f"Found write command {data[offset]:#04x} at offset {offset}")
        elif orders_only_offset is not None:
            # No write command, but found orders - process as incremental update
            offset = orders_only_offset
            self.tn3270e = (orders_only_offset == 5)
            logger.debug(f"No write command, processing orders starting at offset {offset}")
            # Jump to order processing (no write command or WCC to skip)
            self._process_orders(data, offset)
            return
        else:
            logger.debug(f"No write command or orders found, first bytes: {data[:min(10,len(data))].hex()}")
            return
        
        if offset >= len(data):
            logger.debug(f"No data after header (offset={offset}, len={len(data)})")
            return
        
        # Get write command
        cmd = data[offset]
        offset += 1
        
        cmd_name = ALL_WRITE_COMMANDS.get(cmd, 'UNKNOWN')
        logger.debug(f"Processing write command: {cmd:#04x} ({cmd_name}), data length: {len(data)}, offset: {offset}")
        
        # Handle erase commands (clear screen before write)
        if cmd in ERASE_COMMANDS:
            self.clear()
        elif cmd in (WRITE_COMMANDS.ERASE_ALL_UNPROTECTED, WRITE_COMMANDS_CCW.ERASE_ALL_UNPROTECTED):
            self._erase_unprotected()
            return
        elif cmd == WRITE_COMMANDS.WRITE_STRUCTURED_FIELD:
            # Skip structured fields for now
            return
        elif cmd not in ALL_WRITE_COMMANDS:
            # Unknown/unhandled command
            logger.warning(f"Unknown write command: {cmd:#04x}, ignoring message")
            return
        
        # Skip WCC byte
        if offset < len(data):
            offset += 1
        
        # Process the orders and data
        self._process_orders(data, offset)
    
    def _process_orders(self, data: bytes, offset: int, start_pos: int = 0):
        """Process 3270 orders and data starting at the given offset."""
        pos = start_pos
        
        while offset < len(data):
            byte = data[offset]
            
            if byte == ORDERS.SBA:
                # Set Buffer Address
                if offset + 2 < len(data):
                    pos = decode_buffer_address(data[offset + 1], data[offset + 2])
                    offset += 3
                else:
                    break
            
            elif byte == ORDERS.SF:
                # Start Field
                if offset + 1 < len(data):
                    attr = data[offset + 1]
                    self._start_field(pos, attr)
                    pos = (pos + 1) % self.SIZE
                    offset += 2
                else:
                    break
            
            elif byte == ORDERS.SFE:
                # Start Field Extended
                if offset + 1 < len(data):
                    pair_count = data[offset + 1]
                    offset += 2
                    
                    attr = 0x00
                    color = None  # Track if explicit color was set
                    highlight = self.current_highlight
                    
                    for _ in range(pair_count):
                        if offset + 1 < len(data):
                            attr_type = data[offset]
                            attr_value = data[offset + 1]
                            offset += 2
                            
                            if attr_type == ATTR_TYPES.T3270:
                                attr = attr_value
                            elif attr_type == ATTR_TYPES.HIGHLIGHTING:
                                highlight = HIGHLIGHTS.get(attr_value, 'normal')
                            elif attr_type == ATTR_TYPES.FOREGROUND_COLOR:
                                color = COLORS.get(attr_value, 'green')
                    
                    # Use default color based on attributes if no explicit color
                    if color is None:
                        color = get_default_field_color(attr)
                    
                    self._start_field_extended(pos, attr, color, highlight)
                    pos = (pos + 1) % self.SIZE
                else:
                    break
            
            elif byte == ORDERS.SA:
                # Set Attribute
                if offset + 2 < len(data):
                    attr_type = data[offset + 1]
                    attr_value = data[offset + 2]
                    
                    if attr_type == ATTR_TYPES.FOREGROUND_COLOR:
                        self.current_color = COLORS.get(attr_value, 'green')
                    elif attr_type == ATTR_TYPES.HIGHLIGHTING:
                        self.current_highlight = HIGHLIGHTS.get(attr_value, 'normal')
                    elif attr_type == ATTR_TYPES.BACKGROUND_COLOR:
                        self.current_background = COLORS.get(attr_value, 'default')
                    
                    offset += 3
                else:
                    break
            
            elif byte == ORDERS.IC:
                # Insert Cursor
                self.cursor_pos = pos
                offset += 1
            
            elif byte == ORDERS.PT:
                # Program Tab - skip to next unprotected field
                pos = self._get_next_unprotected(pos)
                offset += 1
            
            elif byte == ORDERS.RA:
                # Repeat to Address
                if offset + 3 < len(data):
                    end_addr = decode_buffer_address(data[offset + 1], data[offset + 2])
                    char_byte = data[offset + 3]
                    char = ebcdic_to_ascii(char_byte)
                    
                    while pos != end_addr:
                        self.cells[pos].char = char
                        self.cells[pos].color = self.current_color
                        self.cells[pos].highlight = self.current_highlight
                        pos = (pos + 1) % self.SIZE
                    
                    offset += 4
                else:
                    break
            
            elif byte == ORDERS.EUA:
                # Erase Unprotected to Address
                if offset + 2 < len(data):
                    end_addr = decode_buffer_address(data[offset + 1], data[offset + 2])
                    
                    while pos != end_addr:
                        if not self.cells[pos].is_protected and not self.cells[pos].is_field_start:
                            self.cells[pos].char = ' '
                        pos = (pos + 1) % self.SIZE
                    
                    offset += 3
                else:
                    break
            
            elif byte == ORDERS.MF:
                # Modify Field
                if offset + 1 < len(data):
                    pair_count = data[offset + 1]
                    offset += 2 + (pair_count * 2)
                else:
                    break
            
            elif byte == ORDERS.GE:
                # Graphic Escape
                if offset + 1 < len(data):
                    # Just display the character
                    char = ebcdic_to_ascii(data[offset + 1])
                    self.cells[pos].char = char
                    self.cells[pos].color = self.current_color
                    self.cells[pos].highlight = self.current_highlight
                    pos = (pos + 1) % self.SIZE
                    offset += 2
                else:
                    break
            
            else:
                # Regular data character
                char = ebcdic_to_ascii(byte)
                self.cells[pos].char = char
                self.cells[pos].color = self.current_color
                self.cells[pos].highlight = self.current_highlight
                pos = (pos + 1) % self.SIZE
                offset += 1
    
    def _start_field(self, pos: int, attr: int):
        """Start a new field at position"""
        is_protected = bool(attr & 0x20)
        is_numeric = bool(attr & 0x10)
        is_hidden = (attr & 0x0C) == 0x0C
        is_intensified = (attr & 0x0C) == 0x08
        is_modified = bool(attr & 0x01)
        
        # Get default color based on field attributes
        color = get_default_field_color(attr)
        
        # Mark field start cell
        self.cells[pos].is_field_start = True
        self.cells[pos].char = ' '
        
        # Create field
        field = Field(
            start_pos=pos,
            attr_byte=attr,
            is_protected=is_protected,
            is_numeric=is_numeric,
            is_hidden=is_hidden,
            is_intensified=is_intensified,
            is_modified=is_modified,
            color=color,
        )
        self.fields.append(field)
        
        # Update current color for following characters
        self.current_color = color
        
        # Apply attributes to following cells until next field
        self._apply_field_attributes(pos, field)
    
    def _start_field_extended(self, pos: int, attr: int, color: str, highlight: str):
        """Start a new extended field"""
        is_protected = bool(attr & 0x20)
        is_numeric = bool(attr & 0x10)
        is_hidden = (attr & 0x0C) == 0x0C
        is_intensified = (attr & 0x0C) == 0x08
        is_modified = bool(attr & 0x01)
        
        # Mark field start cell
        self.cells[pos].is_field_start = True
        self.cells[pos].char = ' '
        
        # Create field
        field = Field(
            start_pos=pos,
            attr_byte=attr,
            is_protected=is_protected,
            is_numeric=is_numeric,
            is_hidden=is_hidden,
            is_intensified=is_intensified,
            is_modified=is_modified,
            color=color,
            highlight=highlight,
        )
        self.fields.append(field)
        
        # Update current attributes
        self.current_color = color
        self.current_highlight = highlight
        
        # Apply attributes
        self._apply_field_attributes(pos, field)
    
    def _apply_field_attributes(self, pos: int, field: Field):
        """Apply field attributes to cells after field start"""
        current_pos = (pos + 1) % self.SIZE
        
        while current_pos != pos:
            cell = self.cells[current_pos]
            if cell.is_field_start:
                break
            
            cell.is_protected = field.is_protected
            cell.is_numeric = field.is_numeric
            cell.is_hidden = field.is_hidden
            cell.is_intensified = field.is_intensified
            cell.color = field.color
            cell.highlight = field.highlight
            
            current_pos = (current_pos + 1) % self.SIZE
    
    def _erase_unprotected(self):
        """Erase all unprotected fields"""
        for cell in self.cells:
            if not cell.is_protected and not cell.is_field_start:
                cell.char = ' '
                cell.is_modified = False
    
    def _get_next_unprotected(self, pos: int) -> int:
        """Get next unprotected field position"""
        start = pos
        current = (pos + 1) % self.SIZE
        
        while current != start:
            if self.cells[current].is_field_start and not self.cells[current].is_protected:
                return (current + 1) % self.SIZE
            current = (current + 1) % self.SIZE
        
        return pos
    
    def get_next_input_field(self, pos: int) -> int:
        """Get next input (unprotected) field position"""
        return self._get_next_unprotected(pos)
    
    def get_prev_input_field(self, pos: int) -> int:
        """Get previous input field position"""
        start = pos
        current = (pos - 1 + self.SIZE) % self.SIZE
        
        while current != start:
            if self.cells[current].is_field_start and not self.cells[current].is_protected:
                return (current + 1) % self.SIZE
            current = (current - 1 + self.SIZE) % self.SIZE
        
        return pos
    
    def get_first_input_field(self) -> int:
        """Get first input field position"""
        for i, cell in enumerate(self.cells):
            if cell.is_field_start and not cell.is_protected:
                return (i + 1) % self.SIZE
        return 0
    
    def get_field_at(self, pos: int) -> Optional[Field]:
        """Get field containing position"""
        if not self.fields:
            return None
        
        # Find the field that contains this position
        # Fields are in screen order, so find the one with the largest start_pos <= pos
        result = None
        for field in self.fields:
            if field.start_pos <= pos:
                result = field
            elif result is not None:
                # We've passed the position, use the last matching field
                break
        
        # If no field found with start_pos <= pos, it might be before the first field
        # In that case, the position belongs to the last field (wrapping)
        if result is None and self.fields:
            result = self.fields[-1]
        
        return result
    
    def mark_field_modified(self, pos: int):
        """Mark the field at position as modified (MDT)"""
        field = self.get_field_at(pos)
        if field:
            field.is_modified = True
    
    def get_modified_fields(self) -> List[dict]:
        """Get all modified field data for transmission"""
        result = []
        
        for field in self.fields:
            if field.is_modified and not field.is_protected:
                # Get field content
                start = (field.start_pos + 1) % self.SIZE
                data = []
                pos = start
                
                # Find end of field (next field start or wrap)
                while True:
                    if self.cells[pos].is_field_start:
                        break
                    data.append(self.cells[pos].char)
                    pos = (pos + 1) % self.SIZE
                    if pos == start:
                        break
                
                # Trim trailing spaces
                content = ''.join(data).rstrip()
                
                if content:
                    result.append({
                        'start_pos': start,
                        'data': content
                    })
        
        return result
    
    def clear_modified_flags(self):
        """Clear the is_modified flag on all fields after sending AID"""
        for field in self.fields:
            field.is_modified = False
    
    def is_unformatted(self) -> bool:
        """Check if screen is unformatted (no fields)"""
        return len(self.fields) == 0
    
    def get_unformatted_data(self) -> str:
        """Get all screen data for unformatted screen"""
        return ''.join(cell.char for cell in self.cells).rstrip()
