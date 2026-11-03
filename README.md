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
python python3270.py [host] [port] [-t] [-l LU]

Arguments:
  host          TN3270 server hostname or IP (default: 127.0.0.1)
  port          TN3270 server port (default: 3271)
  -t, --tls     Enable TLS/SSL encryption
  -l, --lu      LU name to request (TN3270E CONNECT); default: any
  -d, --debug   Debug logging (telnet negotiation, records sent and received)
```

### Tests

```bash
pip install pytest
python -m pytest tests        # the GUI smoke test runs offscreen (QT_QPA_PLATFORM=offscreen)
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
| Backspace | Erase the character to the left (the rest of the field shifts left) |
| Delete | Delete the character at the cursor (the rest of the field shifts left) |
| Ctrl+Delete | Erase EOF (clear from the cursor to the end of the field) |
| Any character | Type at the cursor (refused in protected fields) |

Editing marks the field modified (MDT), so a field you clear is sent to the host as empty. MDTs stay set until
the host resets them, as on a real 3270.

### Other keys (keyboard bar)

| Button / key | Action |
|--------------|--------|
| SysReq | TN3270E: telnet IAC AO (the SYSREQ function; also toggles back from the SSCP session); plain TN3270: the 3270 test request |
| Attn | TN3270E: telnet IAC IP; plain TN3270: PA1 then telnet BREAK (as PCOMM does) |
| Reset / Ctrl+R | Unlock the keyboard |

After an AID key the keyboard locks (the status bar shows `X SYSTEM`) until the host's write unlocks it, as on a
real 3270 - so a double Enter can't submit twice. Reset unlocks it by hand.

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
- Enter, Clear, PA1, PA2, PA3, SysReq, Attn buttons

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

python3270 implements TN3270 (RFC 1576) and TN3270E (RFC 2355), checked against the open-source x3270 emulator:

### Telnet
- A byte-level telnet state machine: IAC IAC un-escaped inside records, telnet commands recognised anywhere
  (e.g. an IAC NOP keepalive), IAC EOR ends a record; every outbound record has its 0xFF bytes doubled
- Terminal type IBM-3278-2-E; BINARY and EOR; options answered once (no negotiation loops)
- TIMING-MARK answered (the z/OS TN3270 server's TIMEMARK keepalive)

### TN3270E negotiation
- DEVICE-TYPE REQUEST (optionally CONNECT <LU>: `--lu`); DEVICE-TYPE IS (the LU the host assigned is shown)
- DEVICE-TYPE REJECT backs off with WONT TN3270E, so the host falls back to plain TN3270
- FUNCTIONS REQUEST BIND-IMAGE, RESPONSES, SYSREQ; a host counter-proposal is answered with FUNCTIONS IS (or the
  overlap), as RFC 2355 requires

### TN3270E records
- 3270-DATA, BIND-IMAGE, UNBIND, SSCP-LU-DATA (the VTAM logon screen), NVT-DATA
- RESPONSES: a host record flagged ALWAYS-RESPONSE gets a positive response (DEVICE-END) with its sequence
  number; a bad command or address gets a negative response (COMMAND-REJECT / OPERATION-CHECK)
- SSCP-LU mode: logon input is sent as SSCP-LU-DATA text, the way a 3270 does before an application is bound
- Outbound sequence numbers count and wrap at 32767

### 3270 commands
- Write, Erase/Write, Erase/Write Alternate, Erase All Unprotected, Write Structured Field, No-op
- Read Buffer, Read Modified, Read Modified All (the host asks; the terminal answers)
- WCC: reset MDT, keyboard restore, sound alarm

### Orders
- SBA (12- and 14-bit addresses; an out-of-range address is a write error, not a crash), SF, SFE, SA, MF, IC,
  PT, RA (including RA with GE, and RA to the start address = the whole buffer), EUA, GE, format controls

### Structured fields
- Read Partition: Query, Query List, and Read Buffer / Read Modified / Read Modified All
- Erase/Reset, Set Reply Mode, Outbound 3270DS

### Query Reply
Built like x3270's, every length computed: Summary, Usable Area (24x80, 1920-cell buffer), Alphanumeric
Partitions, Character Sets (CP 037), Color, Highlighting, Reply Modes (field, extended field), Implicit Partition (24x80, alternate
24x80). The Summary lists exactly the replies that are sent.

### Code page
EBCDIC CP 037 through Python's built-in `cp037` codec (all of Latin-1, including `[ ] ^`).

### Not implemented
TLS negotiated in-band (START_TLS on port 23; implicit TLS with `-t` works), IND$FILE file transfer, DBCS,
models larger than 3278-2 (24x80), printer sessions, insert mode, type-ahead, and character reply mode (not
advertised in the query reply).

## Project Structure

```
python3270/
├── python3270.py      # Main entry point and Qt application setup
├── main_window.py     # Main window; hands network events to the GUI thread
├── terminal_widget.py # Terminal display widget with keyboard input
├── connection.py      # TCP/TLS, telnet state machine, TN3270E negotiation and records (no Qt)
├── session.py         # Glue: host records -> screen -> responses; keys -> inbound records (no Qt)
├── screen.py          # Screen buffer, 3270 data stream processing, reads (no Qt)
├── query.py           # Query Reply structured fields
├── orders.py          # TN3270 protocol constants and utilities
├── ebcdic.py          # EBCDIC CP 037 conversion
├── tests/             # pytest suite, incl. an end-to-end TN3270E host simulation
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
