# G-Shock BLE Debug TUI

A terminal-based debug tool for Casio G-Shock Bluetooth LE watches.
Connects to a watch as a GATT central (PC-side client), logs all raw BLE
traffic, decodes protocol commands, and syncs the watch time from NTP.

Supports both G-Shock generations:

| Generation | Example models | Advertised UUID |
|---|---|---|
| **NEW** | GW-B5600, GMW-B5600, GA-B2100, GBD-800 | `0x1804` TX Power |
| **OLD** | GB-5600, GB-6900, GB-X6900, STB-1000 | `0x1802` / `0x1803` |

---

## Features

- Full-screen Textual TUI with colour-coded raw and decoded log panes
- Automatic watch detection — scans all nearby BLE devices, picks the first
  Casio candidate
- Auto time-sync using NTP (`pool.ntp.org`) with system-clock fallback
- Model-aware DST/world-city prepare sequence (GA vs GW profile)
- Old-watch reactive protocol: responds to time/feature requests from the watch
- `--debug` flag writes a timestamped session log to disk
- Rainbow ASCII-art splash on startup (if `ascii-art.txt` is present)

---

## Requirements

- Python 3.10+
- Windows 10/11 (WinRT BLE stack), macOS, or Linux with BlueZ
- A compatible Casio G-Shock BLE watch

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Usage

```bash
python gshock_tui.py          # normal mode
python gshock_tui.py --debug  # also write a session log file
```

### Keyboard shortcuts

| Key | Action |
|-----|--------|
| `s` | Scan / rescan for watches |
| `t` | Manually trigger time sync |
| `i` | Probe watch info (name, firmware, battery) |
| `d` | Dump all known feature codes |
| `c` | Clear both log panes |
| `q` | Quit |

---

## Project structure

```
gshock_tui.py          Entry point
version.py             Version string
requirements.txt       Python dependencies
ascii-art.txt          Optional splash art
lib/
  protocol/
    constants.py       All GATT UUIDs and name tables
    events.py          BLEEvent dataclass + factory helpers
    encoders.py        NTP helper + time byte encoders
    decoders.py        Raw-bytes → BLEEvent decoder
  ble/
    client.py          GShockBLE — scan, connect, protocol handlers
  tui/
    widgets.py         TUILogHandler + StatusPanel widget
    app.py             GShockApp (Textual) + main()
```

---

## Protocol notes

The BLE protocol was reverse-engineered from the official Casio G-Shock+ APK
and the excellent ESP32 reference implementation by Ivo Zivkov:

> **gshock-api-esp32** — <https://github.com/izivkov/gshock-api-esp32>

Key findings documented in `lib/ble/client.py` and `lib/protocol/`:

- **NEW watches** require a model-specific DST/world-city *prepare sequence*
  (read-then-echo-back) before the watch will accept a time write.  Skipping
  this causes the time write to be silently discarded.
- **OLD watches** are driven entirely by the watch: it sends notification
  requests for VS-feature, local time, and current time in that order.  All
  replies must use write-with-response and be serialised FIFO.
- On Windows the CCC descriptor writes (subscribe) must happen *before* the
  link-loss write-with-response or the ATT response never arrives.

---

## License

MIT License — Copyright © 2026 Gary Brewer

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
