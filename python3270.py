#!/usr/bin/env python3
"""
python3270 - Python TN3270 Terminal Emulator

A standalone TN3270 terminal emulator using PySide6 (Qt6).
Can connect directly to mainframes or through hack3270's proxy.

Copyright (C) 2026 Garland Glessner <gglessner@gmail.com>
License: GPL-3.0

Usage:
    python python3270.py [host] [port] [-t]

Examples:
    python python3270.py                    # Launch GUI, connect manually
    python python3270.py 127.0.0.1 3271     # Connect to hack3270 proxy
    python python3270.py -t host.com 992    # Connect with TLS
"""

import sys
import signal
import argparse
import logging

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

try:
    from main_window import MainWindow
except ImportError:
    from .main_window import MainWindow


def main():
    parser = argparse.ArgumentParser(
        description='python3270 - Python TN3270 Terminal Emulator'
    )
    parser.add_argument('host', nargs='?', default='127.0.0.1',
                        help='TN3270 server host (default: 127.0.0.1)')
    parser.add_argument('port', nargs='?', type=int, default=3271,
                        help='TN3270 server port (default: 3271)')
    parser.add_argument('-t', '--tls', action='store_true',
                        help='Enable TLS encryption')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='Enable debug logging')
    
    args = parser.parse_args()
    
    # Set up logging
    log_level = logging.DEBUG if args.debug else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create Qt application
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    # Set dark palette
    from PySide6.QtGui import QPalette, QColor
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(26, 26, 26))
    palette.setColor(QPalette.WindowText, Qt.white)
    palette.setColor(QPalette.Base, QColor(37, 37, 37))
    palette.setColor(QPalette.AlternateBase, QColor(45, 45, 45))
    palette.setColor(QPalette.ToolTipBase, Qt.white)
    palette.setColor(QPalette.ToolTipText, Qt.white)
    palette.setColor(QPalette.Text, Qt.white)
    palette.setColor(QPalette.Button, QColor(45, 45, 45))
    palette.setColor(QPalette.ButtonText, Qt.white)
    palette.setColor(QPalette.BrightText, Qt.red)
    palette.setColor(QPalette.Highlight, QColor(51, 255, 51))
    palette.setColor(QPalette.HighlightedText, Qt.black)
    app.setPalette(palette)
    
    # Create main window
    window = MainWindow()
    
    # Set initial connection values from command line
    window.server_input.setText(args.host)
    window.port_input.setText(str(args.port))
    window.tls_checkbox.setChecked(args.tls)
    
    # Auto-connect if host was specified on command line
    if len(sys.argv) > 1 and args.host != '127.0.0.1':
        window.connection.connect(args.host, args.port, args.tls)
    
    window.show()
    
    # Handle Ctrl+C gracefully
    def sigint_handler(*args):
        window.close()
        app.quit()
    
    signal.signal(signal.SIGINT, sigint_handler)
    
    # Allow Python to process signals (Qt blocks them by default)
    from PySide6.QtCore import QTimer
    timer = QTimer()
    timer.timeout.connect(lambda: None)
    timer.start(100)
    
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
