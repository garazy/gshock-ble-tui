"""
Reusable TUI widgets.

  TUILogHandler  — bridges Python logging into the event queue
  StatusPanel    — live connection-state display in the left column
"""

import asyncio
import datetime
import logging

from rich.markup import escape as me
from textual.widgets import Static

from lib.protocol.constants import (
    NEW_SERVICE_UUID, OLD_SVC_VIRTUAL_SERVER,
    CHAR_READ_REQUEST, CHAR_ALL_FEATURES,
)


# ---------------------------------------------------------------------------
# Logging bridge
# ---------------------------------------------------------------------------

class TUILogHandler(logging.Handler):
    """Routes Python logger records into a queue for the TUI."""

    def __init__(self, queue: asyncio.Queue):
        super().__init__()
        self._queue = queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._queue.put_nowait(("[LOG] " + self.format(record), "log"))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Status panel
# ---------------------------------------------------------------------------

class StatusPanel(Static):
    """Displays current connection state and watch info."""

    DEFAULT_CSS = """
    StatusPanel {
        border: round $primary;
        height: auto;
        min-height: 18;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__("", **kwargs)
        self._status_text = "Idle"
        self._connected   = False
        self._device_name = "—"
        self._device_addr = "—"
        self._last_tx     = "—"
        self._event_count = 0
        self._watch_gen   = "?"

    def set_status(self, text: str):
        self._status_text = text
        self._refresh()

    def set_connection(self, connected: bool, name: str, addr: str,
                       gen: str = "?"):
        self._connected   = connected
        self._device_name = name
        self._device_addr = addr
        self._watch_gen   = gen
        self._refresh()

    def inc_events(self):
        self._event_count += 1
        self._refresh()

    def set_last_tx(self, ts: str):
        self._last_tx = ts
        self._refresh()

    def tick(self):
        """Called once per second to update the clock."""
        self._refresh()

    def _refresh(self):
        conn_str = (
            "[bold green]CONNECTED[/bold green]"
            if self._connected
            else "[bold red]DISCONNECTED[/bold red]"
        )
        gen_color = {"NEW": "cyan", "OLD": "yellow", "?": "dim", "UNKNOWN": "red"}
        gc = gen_color.get(self._watch_gen, "dim")
        gen_str = f"[{gc}]{self._watch_gen}[/{gc}]"
        ts = datetime.datetime.now().strftime("%H:%M:%S")

        content = (
            f" [bold]G-Shock BLE Debug[/bold]            {ts}\n"
            f" Connection : {conn_str}  gen={gen_str}\n"
            f" Device     : [cyan]{me(self._device_name)}[/cyan]  {me(self._device_addr)}\n"
            f" Status     : {me(self._status_text)}\n"
            f" Events     : [yellow]{self._event_count}[/yellow]\n"
            f" Last TX    : {me(self._last_tx)}\n"
            f"\n"
            f" [bold]Scan[/bold]: all devices (no UUID filter)\n"
            f" [bold]NEW[/bold]: adv=0x1804  svc={NEW_SERVICE_UUID[:8]}…\n"
            f" [bold]OLD[/bold]: adv=0x1802/0x1803  svc={OLD_SVC_VIRTUAL_SERVER[:8]}…\n"
            f" [dim]req→{CHAR_READ_REQUEST[:8]}…  "
            f"time→{CHAR_ALL_FEATURES[:8]}…[/dim]"
        )
        self.update(content)
