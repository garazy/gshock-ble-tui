"""
Reusable TUI widgets.

  TUILogHandler  — bridges Python logging into the event queue
  StatusPanel    — live connection-state display in the left column
"""

import asyncio
import datetime
import logging

from rich.markup import escape as me
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static

from lib.protocol.constants import (
    NEW_SERVICE_UUID, OLD_SVC_VIRTUAL_SERVER,
    CHAR_READ_REQUEST, CHAR_ALL_FEATURES,
    ALERT_CATEGORIES,
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
        self._status_text  = "Idle"
        self._connected    = False
        self._device_name  = "—"
        self._device_addr  = "—"
        self._last_tx      = "—"
        self._event_count  = 0
        self._watch_gen    = "?"
        self._queue_depth  = 0

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

    def set_queue_depth(self, depth: int):
        self._queue_depth = depth
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

        queue_str = (
            f"[bold yellow]{self._queue_depth} pending[/bold yellow]"
            if self._queue_depth > 0
            else "[dim]empty[/dim]"
        )
        content = (
            f" [bold]G-Shock BLE Debug[/bold]            {ts}\n"
            f" Connection : {conn_str}  gen={gen_str}\n"
            f" Device     : [cyan]{me(self._device_name)}[/cyan]  {me(self._device_addr)}\n"
            f" Status     : {me(self._status_text)}\n"
            f" Events     : [yellow]{self._event_count}[/yellow]\n"
            f" Last TX    : {me(self._last_tx)}\n"
            f" Alert Queue: {queue_str}\n"
            f"\n"
            f" [bold]Scan[/bold]: all devices (no UUID filter)\n"
            f" [bold]NEW[/bold]: adv=0x1804  svc={NEW_SERVICE_UUID[:8]}…\n"
            f" [bold]OLD[/bold]: adv=0x1802/0x1803  svc={OLD_SVC_VIRTUAL_SERVER[:8]}…\n"
            f" [dim]req→{CHAR_READ_REQUEST[:8]}…  "
            f"time→{CHAR_ALL_FEATURES[:8]}…[/dim]"
        )
        self.update(content)


# ---------------------------------------------------------------------------
# Alert push modal  (OLD watches only)
# ---------------------------------------------------------------------------

class AlertModal(ModalScreen):
    """Modal dialog for composing and sending a New Alert to an OLD watch."""

    DEFAULT_CSS = """
    AlertModal {
        align: center middle;
    }
    #modal-panel {
        width: 46;
        height: auto;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    #modal-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #modal-buttons {
        height: 3;
        margin-top: 1;
        align-horizontal: right;
    }
    #btn-send {
        margin-left: 1;
    }
    """

    def compose(self) -> ComposeResult:
        options = [(name, cat_id) for cat_id, name in sorted(ALERT_CATEGORIES.items())]
        with Vertical(id="modal-panel"):
            yield Label("Push Alert to Watch", id="modal-title")
            yield Label("Category:")
            yield Select(options, id="cat-select")
            yield Label("Message (≤ 18 chars):")
            yield Input(placeholder="Enter message…", max_length=18, id="msg-input")
            with Horizontal(id="modal-buttons"):
                yield Button("Cancel", id="btn-cancel", variant="default")
                yield Button("Send", id="btn-send", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(None)
            return
        cat_select = self.query_one("#cat-select", Select)
        msg_input  = self.query_one("#msg-input", Input)
        cat_val    = cat_select.value
        if cat_val is Select.BLANK:
            self.notify("Please select a category.")
            return
        self.dismiss((cat_val, msg_input.value))
