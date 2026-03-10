"""
BLE packet decoder.

decode_event() converts raw bytes from any G-Shock characteristic into a
BLEEvent with human-readable feature name and decoded detail fields.
"""

from typing import Any, Dict

from lib.protocol.constants import (
    FEATURE_NAMES, BUTTON_NAMES,
    OLD_CHAR_A_NOT_W_REQ, OLD_CHAR_A_NOT_COM_SET,
    OLD_SVC_ID_NAMES, OLD_TIME_REQ_NAMES,
)
from lib.protocol.events import BLEEvent, _ts, label_for_uuid


def decode_event(
    data:      bytes,
    char_uuid: str = "",
    direction: str = "RX",
    note:      str = "",
) -> BLEEvent:
    """Decode raw BLE bytes into a BLEEvent with named fields."""
    ts      = _ts()
    label   = label_for_uuid(char_uuid)
    raw_hex = data.hex(" ").upper() if data else "(empty)"
    details: Dict[str, Any] = {}

    if not data:
        return BLEEvent(ts, direction, label, raw_hex, 0, "EMPTY", details, note)

    fc       = data[0]
    char_low = char_uuid.lower()

    # ---- OLD watch notification on 26eb0009 / 26eb000a ----
    if char_low in (OLD_CHAR_A_NOT_W_REQ.lower(), OLD_CHAR_A_NOT_COM_SET.lower()):
        if len(data) >= 3:
            svc_id   = data[0]
            req      = data[2]
            svc_name = OLD_SVC_ID_NAMES.get(svc_id, f"svc_0x{svc_id:02X}")
            req_name = OLD_TIME_REQ_NAMES.get(req,   f"req_0x{req:02X}")
            details["service_id"]   = f"0x{svc_id:02X} ({svc_name})"
            details["request_type"] = f"0x{req:02X} ({req_name})"
            fc   = svc_id
            name = f"OLD_WATCH_REQUEST:{svc_name}/{req_name}"
        else:
            name = f"OLD_WATCH_REQUEST (short, {len(data)}B)"
        return BLEEvent(ts, direction, label, raw_hex, fc, name, details, note)

    # ---- NEW watch features protocol ----
    name = FEATURE_NAMES.get(fc, f"UNKNOWN_0x{fc:02X}")

    if fc == 0x10:
        if len(data) >= 19:
            btn = data[8]
            details["button"] = BUTTON_NAMES.get(btn, f"0x{btn:02X}")
        else:
            details["packet_len"] = f"{len(data)} bytes (expected ≥19)"

    elif fc == 0x09:
        if len(data) >= 8:
            year = data[1] | (data[2] << 8)
            details["datetime"] = (
                f"{year}-{data[3]:02d}-{data[4]:02d} "
                f"{data[5]:02d}:{data[6]:02d}:{data[7]:02d}"
            )
        if len(data) >= 9:
            wdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            wd = data[8]
            details["weekday"] = wdays[wd] if wd < 7 else f"0x{wd:02X}"

    elif fc == 0x28:
        if len(data) >= 3:
            details["battery_raw"]   = f"0x{data[1]:02X} ({data[1]})"
            details["temperature_c"] = data[2]

    elif fc == 0x23:
        if len(data) > 1:
            try:
                details["watch_name"] = (
                    data[1:].decode("ascii", errors="replace")
                    .rstrip("\x00").strip()
                )
            except Exception:
                pass

    elif fc == 0x20:
        if len(data) > 1:
            details["version_hex"] = data[1:].hex(" ").upper()

    elif fc == 0x26:
        if len(data) > 1:
            details["module_id_hex"] = data[1:].hex(" ").upper()

    elif fc == 0x11:
        if len(data) >= 14:
            details["time_adj_on"] = (data[12] == 0x00)
        if len(data) >= 15:
            details["sync_after_min"] = data[13]

    elif fc == 0x13:
        if len(data) > 1:
            b = data[1]
            details["12h_mode"]   = bool(b & 0x01)
            details["op_sounds"]  = bool(b & 0x02)
            details["auto_light"] = bool(b & 0x04)
            details["power_save"] = bool(b & 0x10)

    elif fc == 0x15:
        if len(data) >= 5:
            flags = data[1]
            details["alarm1_enabled"] = bool(flags & 0x40)
            details["hourly_chime"]   = bool(flags & 0x80)
            details["hour"]           = data[3]
            details["minute"]         = data[4]

    elif fc == 0xFF:
        details["error_raw"] = raw_hex

    return BLEEvent(ts, direction, label, raw_hex, fc, name, details, note)
