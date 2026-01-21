"""
Terminal Widget
PySide6 widget for 24x80 3270 terminal display

Copyright (C) 2026 Garland Glessner <gglessner@gmail.com>
License: GPL-3.0 (see LICENSE)
"""

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QPainter, QFont, QColor, QKeyEvent, QFontDatabase

try:
    from .screen import ScreenBuffer
except ImportError:
    from screen import ScreenBuffer


# Color mapping
COLORS = {
    'default': QColor(0, 255, 0),      # Green
    'green': QColor(0, 255, 0),
    'blue': QColor(100, 149, 237),
    'red': QColor(255, 80, 80),
    'pink': QColor(255, 182, 193),
    'turquoise': QColor(64, 224, 208),
    'yellow': QColor(255, 255, 100),
    'white': QColor(255, 255, 255),
}


class TerminalWidget(QWidget):
    """24x80 3270 terminal display widget"""
    
    # Signals
    aid_pressed = Signal(str)      # AID key pressed (ENTER, PF1, etc.)
    char_typed = Signal(str)       # Character typed
    cursor_moved = Signal(int)     # Cursor position changed
    
    ROWS = 24
    COLS = 80
    
    def __init__(self, screen: ScreenBuffer, parent=None):
        super().__init__(parent)
        
        self.screen = screen
        self.cursor_pos = 0
        self.cursor_visible = True
        
        # Load and set up 3270 font
        if self._load_3270_font() and self._font_family:
            self.font = QFont(self._font_family, 16)
        else:
            # Fallback to Consolas if 3270 font not available
            self.font = QFont("Consolas", 14)
        self.font.setStyleHint(QFont.Monospace)
        
        # Calculate cell dimensions
        self._update_cell_size()
        
        # Cursor blink timer
        self.cursor_timer = QTimer(self)
        self.cursor_timer.timeout.connect(self._blink_cursor)
        self.cursor_timer.start(500)
        
        # Enable keyboard focus
        self.setFocusPolicy(Qt.StrongFocus)
        
        # Enable mouse tracking for focus-on-hover
        self.setMouseTracking(True)
        
        # Background color
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(self.backgroundRole(), QColor(0, 0, 0))
        self.setPalette(palette)
    
    def _load_3270_font(self) -> bool:
        """Load the 3270 font from the fonts directory. Returns True if loaded."""
        import os
        font_dir = os.path.join(os.path.dirname(__file__), 'fonts')
        font_path = os.path.join(font_dir, '3270-Regular.ttf')
        if os.path.exists(font_path):
            font_id = QFontDatabase.addApplicationFont(font_path)
            if font_id != -1:
                families = QFontDatabase.applicationFontFamilies(font_id)
                if families:
                    self._font_family = families[0]
                    return True
        self._font_family = None
        return False
    
    def _update_cell_size(self):
        """Calculate cell dimensions based on font"""
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(self.font)
        self.cell_width = fm.horizontalAdvance('M')
        self.cell_height = fm.height()
        
        # Set widget size
        width = self.cell_width * self.COLS + 20
        height = self.cell_height * self.ROWS + 20
        self.setMinimumSize(width, height)
        self.setMaximumSize(width, height)
    
    def set_cursor_pos(self, pos: int):
        """Set cursor position"""
        self.cursor_pos = pos % (self.ROWS * self.COLS)
        self.cursor_visible = True
        self.update()
        self.cursor_moved.emit(self.cursor_pos)
    
    def _blink_cursor(self):
        """Toggle cursor visibility"""
        self.cursor_visible = not self.cursor_visible
        self.update()
    
    def enterEvent(self, event):
        """Grab focus when mouse enters the terminal"""
        self.setFocus()
        super().enterEvent(event)
    
    def paintEvent(self, event):
        """Paint the terminal screen"""
        painter = QPainter(self)
        painter.setFont(self.font)
        
        # Draw each cell
        for row in range(self.ROWS):
            for col in range(self.COLS):
                pos = row * self.COLS + col
                cell = self.screen.cells[pos]
                
                x = 10 + col * self.cell_width
                y = 10 + row * self.cell_height
                
                # Get character and color
                char = cell.char if not cell.is_hidden else ' '
                color = COLORS.get(cell.color, COLORS['green'])
                
                # Handle highlighting
                if cell.highlight == 'reverse':
                    # Draw background in foreground color
                    painter.fillRect(x, y, self.cell_width, self.cell_height, color)
                    painter.setPen(QColor(0, 0, 0))
                elif cell.highlight == 'underscore':
                    painter.setPen(color)
                    painter.drawLine(x, y + self.cell_height - 2, 
                                   x + self.cell_width, y + self.cell_height - 2)
                else:
                    painter.setPen(color)
                
                # Handle intensified
                if cell.is_intensified:
                    font = painter.font()
                    font.setBold(True)
                    painter.setFont(font)
                else:
                    font = painter.font()
                    font.setBold(False)
                    painter.setFont(font)
                
                # Draw character
                painter.drawText(x, y + self.cell_height - 4, char)
                
                # Reset pen for next character
                painter.setPen(color)
        
        # Draw cursor as solid block
        if self.cursor_visible:
            cursor_row = self.cursor_pos // self.COLS
            cursor_col = self.cursor_pos % self.COLS
            x = 10 + cursor_col * self.cell_width
            y = 10 + cursor_row * self.cell_height
            
            # Solid green block cursor
            painter.fillRect(x, y, self.cell_width, self.cell_height, QColor(0, 255, 0))
            
            # Draw the character under cursor in black
            cell = self.screen.cells[self.cursor_pos]
            char = cell.char if not cell.is_hidden else ' '
            painter.setPen(QColor(0, 0, 0))
            painter.drawText(x, y + self.cell_height - 4, char)
    
    def keyPressEvent(self, event: QKeyEvent):
        """Handle keyboard input"""
        key = event.key()
        modifiers = event.modifiers()
        
        # Function keys
        if key >= Qt.Key_F1 and key <= Qt.Key_F12:
            fn = key - Qt.Key_F1 + 1
            if modifiers & Qt.ShiftModifier:
                fn += 12  # PF13-PF24
            self.aid_pressed.emit(f'PF{fn}')
            return
        
        # PA keys (Ctrl + 1/2/3)
        if modifiers & Qt.ControlModifier:
            if key == Qt.Key_1:
                self.aid_pressed.emit('PA1')
                return
            elif key == Qt.Key_2:
                self.aid_pressed.emit('PA2')
                return
            elif key == Qt.Key_3:
                self.aid_pressed.emit('PA3')
                return
        
        # Enter
        if key == Qt.Key_Return or key == Qt.Key_Enter:
            self.aid_pressed.emit('ENTER')
            return
        
        # Clear (Escape)
        if key == Qt.Key_Escape:
            self.aid_pressed.emit('CLEAR')
            return
        
        # Tab
        if key == Qt.Key_Tab:
            if modifiers & Qt.ShiftModifier:
                new_pos = self.screen.get_prev_input_field(self.cursor_pos)
            else:
                new_pos = self.screen.get_next_input_field(self.cursor_pos)
            self.set_cursor_pos(new_pos)
            return
        
        # Arrow keys
        if key == Qt.Key_Up:
            self.set_cursor_pos((self.cursor_pos - self.COLS + 1920) % 1920)
            return
        elif key == Qt.Key_Down:
            self.set_cursor_pos((self.cursor_pos + self.COLS) % 1920)
            return
        elif key == Qt.Key_Left:
            self.set_cursor_pos((self.cursor_pos - 1 + 1920) % 1920)
            return
        elif key == Qt.Key_Right:
            self.set_cursor_pos((self.cursor_pos + 1) % 1920)
            return
        
        # Home
        if key == Qt.Key_Home:
            self.set_cursor_pos(self.screen.get_first_input_field())
            return
        
        # Backspace
        if key == Qt.Key_Backspace:
            new_pos = (self.cursor_pos - 1 + 1920) % 1920
            self.screen.cells[new_pos].char = ' '
            self.set_cursor_pos(new_pos)
            self.update()
            return
        
        # Delete
        if key == Qt.Key_Delete:
            self.screen.cells[self.cursor_pos].char = ' '
            self.update()
            return
        
        # Regular character input
        text = event.text()
        if text and len(text) == 1 and text.isprintable():
            cell = self.screen.cells[self.cursor_pos]
            
            # Check if we can type here
            if cell.is_protected or cell.is_field_start:
                return
            
            # Update cell
            cell.char = text
            self.screen.mark_field_modified(self.cursor_pos)
            
            # Move cursor
            self.set_cursor_pos((self.cursor_pos + 1) % 1920)
            self.char_typed.emit(text)
            self.update()
