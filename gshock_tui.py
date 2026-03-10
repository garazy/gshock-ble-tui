"""
G-Shock BLE Debug TUI — entry point.

Usage:
    python gshock_tui.py [--debug]

    --debug   Write a timestamped session log to <DeviceName>_<date>.txt

See lib/tui/app.py for the full application, lib/ble/client.py for the BLE
client, and lib/protocol/ for protocol constants, encoders, and decoders.
"""

from lib.tui.app import main

if __name__ == "__main__":
    main()
