"""
BLEEvent dataclass and factory helpers.

All BLE traffic (scanned, received, transmitted, system messages) is wrapped
in a BLEEvent so the TUI has a single consistent message type to display.
"""

import datetime
from dataclasses import dataclass, field
from typing import Any, Dict

from lib.protocol.constants import UUID_LABELS, CASIO_UUID_PREFIX


def _ts() -> str:
    """Current time as a short HH:MM:SS.mmm string."""
    return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]


def label_for_uuid(uuid: str) -> str:
    """Return a short human-readable label for a GATT UUID."""
    low = uuid.lower()
    if low in UUID_LABELS:
        return UUID_LABELS[low]
    if low.startswith(CASIO_UUID_PREFIX):
        return f"CASIO({uuid[:8]})"
    return uuid[:22]


# ---------------------------------------------------------------------------
# Event dataclass
# ---------------------------------------------------------------------------

@dataclass
class BLEEvent:
    timestamp:    str
    direction:    str           # "RX" | "TX" | "SYS" | "SCAN"
    char_label:   str
    raw_hex:      str
    feature_code: int               = 0
    feature_name: str               = ""
    details:      Dict[str, Any]    = field(default_factory=dict)
    note:         str               = ""

    def raw_line(self) -> str:
        return (f"[{self.timestamp}] {self.direction:4s} "
                f"{self.char_label:22s} {self.raw_hex}")

    def decoded_line(self) -> str:
        parts = [f"[{self.timestamp}] {self.direction:4s} {self.feature_name}"]
        for k, v in self.details.items():
            parts.append(f"    {k} = {v}")
        if self.note:
            parts.append(f"    >> {self.note}")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def make_sys_event(msg: str, note: str = "") -> BLEEvent:
    return BLEEvent(_ts(), "SYS", "SYSTEM", msg, note=note)


def make_scan_event(name: str, addr: str, rssi: int,
                    uuids: list, is_casio: bool) -> BLEEvent:
    uuid_str = " | ".join(
        label_for_uuid(u) for u in uuids
    ) if uuids else "(no services advertised)"
    marker = "[CASIO CANDIDATE]" if is_casio else ""
    raw = (f"{name or '(unnamed)'} [{addr}] RSSI={rssi} {marker}\n"
           f"    adv_uuids: {uuid_str}")
    details: Dict[str, Any] = {
        "name":     name or "(unnamed)",
        "address":  addr,
        "rssi":     rssi,
        "is_casio": is_casio,
        "uuids":    ", ".join(uuids) if uuids else "none",
    }
    return BLEEvent(_ts(), "SCAN", "BLE_SCANNER", raw, note=marker)
