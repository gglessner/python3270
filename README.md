# python3270 v1.0.0

A Python TN3270 terminal emulator using PySide6 (Qt6).

**Version:** 1.0.0  
**Author:** Garland Glessner (gglessner@gmail.com)  
**License:** GNU General Public License v3.0

## Overview

python3270 is a standalone TN3270 terminal emulator that provides a native desktop application for connecting to IBM mainframes and compatible systems. It can connect directly to mainframes or through hack3270's proxy for field manipulation and data injection.

## Features

- **Full TN3270E Protocol**: Implements RFC 2355 TN3270E negotiation with automatic Query Reply
- **24x80 Terminal Display**: Classic mainframe screen size with authentic 3270 font
- **Field Attributes**: Protected, unprotected, hidden, numeric, intensified fields
- **Color Support**: Full 8-color support (green, red, blue, pink, turquoise, yellow, white, default)
- **Classic Color Mapping**: Unprotected fields display in green/red, protected in blue/white
- **Keyboard Support**: Full PF key (F1-F24), PA key, and cursor navigation
- **TLS/SSL Support**: Secure encrypted connections to mainframes
- **Dark Theme**: Modern dark UI with green phosphor aesthetic
- **Focus-on-Hover**: Terminal automatically receives focus when mouse enters
- **Cross-Platform**: Runs on Windows, Linux, and macOS

## Requirements

- Python 3.10+
- PySide6 (Qt6)

## Installation

```bash
cd python3270
pip install -r requirements.txt
```

## Usage

### Launch GUI

```bash
python python3270.py
```

This opens the terminal with default connection settings (127.0.0.1:3271).

### Command Line Options

```
python python3270.py [host] [port] [-t]

Arguments:
  host          TN3270 server hostname or IP (default: 127.0.0.1)
  port          TN3270 server port (default: 3271)
  -t, --tls     Enable TLS/SSL encryption
```

### Examples

```bash
# Connect to hack3270 proxy (default)
python python3270.py

# Connect to hack3270 on custom port
python python3270.py 127.0.0.1 3271

# Connect directly to mainframe
python python3270.py mainframe.example.com 23

# Connect with TLS encryption
python python3270.py -t mainframe.example.com 992

# Connect to public Hercules system
python python3270.py public.hercules.example.com 3270
```

## Keyboard Shortcuts

### Function Keys

| Key | Action |
|-----|--------|
| F1-F12 | PF1-PF12 |
| Shift+F1-F12 | PF13-PF24 |

### Attention Keys

| Key | Action |
|-----|--------|
| Enter | ENTER (submit screen) |
| Escape | CLEAR |
| Ctrl+1 | PA1 |
| Ctrl+2 | PA2 |
| Ctrl+3 | PA3 |

### Navigation

| Key | Action |
|-----|--------|
| Tab | Jump to next input field |
| Shift+Tab | Jump to previous input field |
| Arrow keys | Move cursor one position |
| Home | Jump to first input field |

### Editing

| Key | Action |
|-----|--------|
| Backspace | Delete character to the left |
| Delete | Delete character at cursor |
| Any character | Insert at cursor position |

## User Interface

### Connection Bar

The top bar contains:
- **Server**: Hostname or IP address of the TN3270 server
- **Port**: Port number (standard ports: 23 for telnet, 992 for TLS, 3270 for Hercules)
- **TLS**: Checkbox to enable encrypted connection
- **Connect/Disconnect**: Connection control buttons

### Terminal Display

- 24 rows x 80 columns display area
- Authentic IBM 3270 font
- Color-coded fields based on attributes
- Blinking block cursor
- Click-to-position cursor support

### Keyboard Bar

Clickable buttons for all function keys:
- PF1-PF12 buttons
- Enter, Clear, PA1, PA2, PA3 buttons

### Status Bar

Shows current connection state:
- Connection status (Connected/Disconnected)
- TN3270E mode indicator
- Cursor position (row, column)

## Color Mapping

python3270 uses classic 3270 color conventions:

| Field Type | Display Mode | Color |
|------------|--------------|-------|
| Unprotected | Normal | Green |
| Unprotected | Intensified | Red |
| Protected | Normal | Blue |
| Protected | Intensified | White |
| Hidden | Any | Not displayed |

When explicit colors are sent by the host, those override the defaults.

## TN3270E Protocol

python3270 implements the TN3270E protocol (RFC 2355) including:

### Negotiation
- Terminal type: IBM-3278-2-E
- Binary transmission
- End-of-record markers
- TN3270E functions (BIND-IMAGE, RESPONSES, SYSREQ)

### Write Commands
- Write (F1)
- Erase/Write (F5)
- Erase/Write Alternate (7E)
- Erase All Unprotected (6F)
- Write Structured Field (F3)

### Orders
- Set Buffer Address (SBA)
- Start Field (SF)
- Start Field Extended (SFE)
- Set Attribute (SA)
- Modify Field (MF)
- Insert Cursor (IC)
- Program Tab (PT)
- Repeat to Address (RA)
- Erase Unprotected to Address (EUA)
- Graphic Escape (GE)

### Query Reply
Automatic response to Read Partition Query with terminal capabilities:
- Usable Area (24x80)
- Color support
- Highlighting support
- Character sets
- Reply modes

## Project Structure

```
python3270/
├── python3270.py      # Main entry point and Qt application setup
├── main_window.py     # Main window with UI layout and AID handling
├── terminal_widget.py # Terminal display widget with keyboard input
├── connection.py      # TN3270 TCP/TLS connection and protocol handler
├── screen.py          # Screen buffer model and field tracking
├── orders.py          # TN3270 protocol constants and utilities
├── ebcdic.py          # EBCDIC/ASCII character conversion tables
├── requirements.txt   # Python dependencies
├── fonts/             # IBM 3270 font files
│   ├── 3270-Regular.ttf
│   ├── 3270Condensed-Regular.ttf
│   └── LICENSE.txt
└── README.md          # This documentation
```

## Using with hack3270

python3270 is designed to work seamlessly with hack3270 for security testing:

1. **Start hack3270** connecting to your target mainframe:
   ```bash
   python hack3270.py mainframe.example.com 23
   ```

2. **Start python3270** connecting to hack3270's proxy:
   ```bash
   python python3270.py 127.0.0.1 3271
   ```

3. **Click "Continue"** in hack3270 when the connection is received

This setup allows you to:
- Use hack3270's field manipulation features
- Inject data into protected fields
- Monitor and modify 3270 data streams
- Use python3270 as a fully-featured terminal

## Troubleshooting

### Connection Issues

**"Connection refused"**
- Verify the host and port are correct
- Check if the mainframe/proxy is running
- Ensure no firewall is blocking the connection

**"Connection timeout"**
- The host may be unreachable
- Try pinging the host first
- Check network connectivity

**TLS errors**
- Ensure the server supports TLS on the specified port
- Some servers use self-signed certificates

### Display Issues

**Characters not displaying correctly**
- Ensure the 3270 font is installed (fonts/ directory)
- The fallback Consolas font will be used if 3270 font fails to load

**Wrong colors**
- Some hosts don't send color attributes
- Default color mapping is based on field protection/intensity

### Keyboard Issues

**Function keys not working**
- Some desktop environments intercept F-keys
- Try the clickable button bar as an alternative
- Check if your terminal has F-key pass-through settings

## Fonts

The 3270 font is provided by the [3270font project](https://github.com/rbanffy/3270font) by Ricardo Banffy. The font is licensed under a BSD-style license - see `fonts/LICENSE.txt` for details.

## Comparison with react3270

| Feature | python3270 | react3270 |
|---------|------------|-----------|
| Platform | Desktop (Windows/Linux/macOS) | Browser |
| GUI Framework | PySide6 (Qt6) | React + Vite |
| Connection | Direct TCP/TLS | WebSocket via Node.js bridge |
| Dependencies | Python + PySide6 | Node.js + npm |
| Offline Use | Yes | Requires bridge server |
| Installation | pip install | npm install + build |

Both implement the same TN3270E protocol and can be used interchangeably with hack3270.

## License

Copyright (C) 2026 Garland Glessner <gglessner@gmail.com>

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.
