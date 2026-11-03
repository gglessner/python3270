"""
Main Window
PySide6 main application window for python3270

Copyright (C) 2026 Garland Glessner <gglessner@gmail.com>
License: GPL-3.0 (see LICENSE)
"""

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLabel, QLineEdit, QCheckBox, QFrame,
    QSizePolicy
)
from PySide6.QtCore import Qt, Slot, QObject, Signal
from PySide6.QtGui import QFont

try:
    from .screen import ScreenBuffer
    from .connection import TN3270Connection
    from .session import TN3270Session
    from .terminal_widget import TerminalWidget
except ImportError:
    from screen import ScreenBuffer
    from connection import TN3270Connection
    from session import TN3270Session
    from terminal_widget import TerminalWidget


class _NetBridge(QObject):
    """Carries connection callbacks (fired on the receive thread) to the GUI thread as queued signals.
    Touching widgets or the screen buffer from the receive thread races the painter and can crash Qt."""
    record = Signal(object)
    connected = Signal()
    disconnected = Signal()
    error = Signal(str)
    state = Signal()


class KeyboardBar(QFrame):
    """AID key button bar"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Panel | QFrame.Raised)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(3)
        
        self.buttons = {}
        
        # PF keys row 1 (PF1-12)
        for i in range(1, 13):
            btn = QPushButton(f"PF{i}")
            btn.setFixedWidth(45)
            btn.setStyleSheet(self._button_style())
            btn.setFocusPolicy(Qt.NoFocus)  # Don't steal focus from terminal
            layout.addWidget(btn)
            self.buttons[f'PF{i}'] = btn
        
        layout.addStretch()
        
        # Special keys
        for key in ['Enter', 'Clear', 'PA1', 'PA2', 'PA3', 'SysReq', 'Attn', 'Reset']:
            btn = QPushButton(key)
            btn.setFixedWidth(50)
            btn.setStyleSheet(self._button_style())
            btn.setFocusPolicy(Qt.NoFocus)  # Don't steal focus from terminal
            layout.addWidget(btn)
            self.buttons[key.upper()] = btn
    
    def _button_style(self):
        return """
            QPushButton {
                background-color: #2d2d2d;
                color: #33ff33;
                border: 1px solid #444;
                border-radius: 3px;
                padding: 5px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #3d3d3d;
            }
            QPushButton:pressed {
                background-color: #1d1d1d;
            }
            QPushButton:disabled {
                color: #666;
            }
        """


class StatusBar(QFrame):
    """Connection status bar"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Panel | QFrame.Sunken)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        
        self.status_label = QLabel("DISCONNECTED")
        self.status_label.setStyleSheet("color: #ff6666;")
        layout.addWidget(self.status_label)
        
        layout.addStretch()
        
        self.cursor_label = QLabel("Row: 1  Col: 1")
        self.cursor_label.setStyleSheet("color: #888;")
        layout.addWidget(self.cursor_label)
        
        layout.addSpacing(20)
        
        self.mode_label = QLabel("TN3270")
        self.mode_label.setStyleSheet("color: #888;")
        layout.addWidget(self.mode_label)
    
    def set_connected(self, connected: bool, tn3270e: bool = False, detail: str = ""):
        if connected:
            self.status_label.setText("CONNECTED")
            self.status_label.setStyleSheet("color: #33ff33;")
            self.mode_label.setText(("TN3270E" if tn3270e else "TN3270") + (f"  {detail}" if detail else ""))
        else:
            self.status_label.setText("DISCONNECTED")
            self.status_label.setStyleSheet("color: #ff6666;")
            self.mode_label.setText("TN3270")
    
    def set_cursor(self, pos: int):
        row = pos // 80 + 1
        col = pos % 80 + 1
        self.cursor_label.setText(f"Row: {row}  Col: {col}")


class MainWindow(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle("python3270 v1.0.0 - TN3270 Terminal Emulator")
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1a1a1a;
            }
            QLabel {
                color: #fff;
            }
            QLineEdit {
                background-color: #252525;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 5px;
                color: #fff;
            }
            QLineEdit:focus {
                border-color: #33ff33;
            }
            QLineEdit:disabled {
                color: #666;
            }
            QCheckBox {
                color: #fff;
            }
        """)
        
        # Create screen buffer, connection and the session that ties them together
        self.screen = ScreenBuffer()
        self.connection = TN3270Connection()
        self.session = TN3270Session(self.connection, self.screen)

        # Connection callbacks fire on the receive thread: hop to the GUI thread through queued signals
        self._net = _NetBridge()
        self._net.record.connect(self._on_record)
        self._net.connected.connect(self._on_connect)
        self._net.disconnected.connect(self._on_disconnect)
        self._net.error.connect(self._on_error)
        self._net.state.connect(self._on_state)
        self.connection.on_record = self._net.record.emit
        self.connection.on_connect = self._net.connected.emit
        self.connection.on_disconnect = self._net.disconnected.emit
        self.connection.on_error = self._net.error.emit
        self.connection.on_state = self._net.state.emit
        
        # Build UI
        self._build_ui()
    
    def _build_ui(self):
        """Build the user interface"""
        central = QWidget()
        self.setCentralWidget(central)
        
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # Header with connection controls
        header = QHBoxLayout()
        
        title = QLabel("python3270")
        title.setStyleSheet("color: #33ff33; font-size: 18px; font-weight: bold;")
        header.addWidget(title)
        
        header.addSpacing(20)
        
        # Server input
        header.addWidget(QLabel("Server:"))
        self.server_input = QLineEdit("127.0.0.1")
        self.server_input.setFixedWidth(120)
        header.addWidget(self.server_input)
        
        # Port input
        header.addWidget(QLabel("Port:"))
        self.port_input = QLineEdit("3271")
        self.port_input.setFixedWidth(60)
        header.addWidget(self.port_input)
        
        # TLS checkbox
        self.tls_checkbox = QCheckBox("TLS")
        header.addWidget(self.tls_checkbox)
        
        header.addStretch()
        
        # Connect/Disconnect buttons
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setFocusPolicy(Qt.NoFocus)
        self.connect_btn.setStyleSheet("""
            QPushButton {
                background-color: #2d8a2d;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
            }
            QPushButton:hover { background-color: #3da33d; }
            QPushButton:disabled { background-color: #555; color: #888; }
        """)
        self.connect_btn.clicked.connect(self._connect)
        header.addWidget(self.connect_btn)
        
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.setEnabled(False)
        self.disconnect_btn.setFocusPolicy(Qt.NoFocus)
        self.disconnect_btn.setStyleSheet("""
            QPushButton {
                background-color: #8a2d2d;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
            }
            QPushButton:hover { background-color: #a33d3d; }
            QPushButton:disabled { background-color: #555; color: #888; }
        """)
        self.disconnect_btn.clicked.connect(self._disconnect)
        header.addWidget(self.disconnect_btn)
        
        layout.addLayout(header)
        
        # Keyboard bar
        self.keyboard_bar = KeyboardBar()
        for key, btn in self.keyboard_bar.buttons.items():
            btn.clicked.connect(lambda checked, k=key: self._send_aid(k))
            btn.setEnabled(False)
        layout.addWidget(self.keyboard_bar)
        
        # Terminal widget
        self.terminal = TerminalWidget(self.screen)
        self.terminal.aid_pressed.connect(self._send_aid)
        self.terminal.cursor_moved.connect(self._on_cursor_moved)
        layout.addWidget(self.terminal, alignment=Qt.AlignCenter)
        
        # Status bar
        self.status_bar = StatusBar()
        layout.addWidget(self.status_bar)
    
    @Slot()
    def _connect(self):
        """Connect to server"""
        host = self.server_input.text().strip()
        if not host:
            self._on_error("Server address is required")
            return
        
        try:
            port = int(self.port_input.text().strip())
            if port < 1 or port > 65535:
                raise ValueError("Port out of range")
        except ValueError:
            self._on_error("Invalid port number")
            return
        
        use_tls = self.tls_checkbox.isChecked()
        
        # Disable controls while connecting
        self.connect_btn.setEnabled(False)
        self.status_bar.status_label.setText("CONNECTING...")
        self.status_bar.status_label.setStyleSheet("color: #ffff66;")
        
        self.connection.connect(host, port, use_tls)
    
    @Slot()
    def _disconnect(self):
        """Disconnect from server"""
        self.connection.disconnect()
        self.screen.clear()
        self.terminal.update()
    
    def _on_connect(self):
        """Handle connection established"""
        self.connect_btn.setEnabled(False)
        self.disconnect_btn.setEnabled(True)
        self.server_input.setEnabled(False)
        self.port_input.setEnabled(False)
        self.tls_checkbox.setEnabled(False)
        
        for btn in self.keyboard_bar.buttons.values():
            btn.setEnabled(True)
        
        self._on_state()

        # Focus terminal for immediate typing
        self.terminal.setFocus()

    def _on_state(self):
        """Negotiation / bind state changed: show mode, LU and SSCP/3270 state."""
        if not self.connection.connected:
            return
        c = self.connection
        bits = []
        if c.tn3270e_mode:
            if c.connected_lu:
                bits.append(f"LU {c.connected_lu}")
            bits.append({'sscp': 'SSCP-LU', '3270': '3270', 'nvt': 'NVT', 'unbound': 'unbound'}.get(c.submode, ''))
        if self.screen.keyboard_locked:
            bits.append("X SYSTEM")             # waiting for the host (Ctrl+R / Reset unlocks)
        self.status_bar.set_connected(True, c.tn3270e_mode, "  ".join(b for b in bits if b))
    
    def _on_disconnect(self):
        """Handle disconnection"""
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self.server_input.setEnabled(True)
        self.port_input.setEnabled(True)
        self.tls_checkbox.setEnabled(True)
        
        for btn in self.keyboard_bar.buttons.values():
            btn.setEnabled(False)
        
        self.status_bar.set_connected(False)
    
    def _on_error(self, error: str):
        """Handle connection error"""
        # Update status bar with error
        self.status_bar.status_label.setText(f"ERROR: {error[:40]}")
        self.status_bar.status_label.setStyleSheet("color: #ff6666;")
        
        # Re-enable connection controls
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self.server_input.setEnabled(True)
        self.port_input.setEnabled(True)
        self.tls_checkbox.setEnabled(True)
    
    def _on_record(self, record):
        """A host record (GUI thread): process it, answer it, repaint."""
        self.session.handle_record(record)
        self.terminal.set_cursor_pos(self.screen.cursor_pos)
        if self.screen.alarm:
            self.screen.alarm = False
            from PySide6.QtWidgets import QApplication
            QApplication.beep()
        self.terminal.update()
        self._on_state()

    def _on_cursor_moved(self, pos: int):
        """Handle cursor movement"""
        self.status_bar.set_cursor(pos)

    @Slot(str)
    def _send_aid(self, aid_name: str):
        """Send an AID key: AID + cursor + modified fields (the MDTs stay set until the host resets them,
        as on a real 3270 - CICS relies on that)."""
        if not self.connection.connected:
            return
        key = aid_name.upper()
        if key == 'RESET':
            self.session.reset()
        elif key == 'ATTN':
            self.session.send_attn()
        else:
            self.screen.cursor_pos = self.terminal.cursor_pos
            self.session.send_aid(key)
        self.terminal.set_cursor_pos(self.screen.cursor_pos)
        self.terminal.update()
        self._on_state()

        # Return focus to terminal
        self.terminal.setFocus()
    
    def closeEvent(self, event):
        """Handle window close"""
        self.connection.disconnect()
        event.accept()
