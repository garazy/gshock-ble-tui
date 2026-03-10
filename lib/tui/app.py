"""
G-Shock BLE Debug TUI — main application.

Usage:
    python gshock_tui.py [--debug]

    --debug   Write a timestamped session log to <DeviceName>_<date>.txt

Keyboard shortcuts:
    q   Quit
    s   Start scan / rescan
    t   Send time-sync command
    c   Clear both logs
    i   Probe watch info (name, version, battery)
    d   Dump all features to decoded log
"""

import asyncio
import datetime
import logging
import os
import re
import sys
from pathlib import Path
from typing import Optional

from rich.markup import escape as markup_escape

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Label, RichLog

from lib.protocol import (
    BLEEvent,
    NEW_ADV_UUID, NEW_SERVICE_UUID,
    CHAR_READ_REQUEST, CHAR_ALL_FEATURES,
    NEW_NOTIFY_CHAR_UUIDS,
    OLD_ADV_UUIDS, OLD_SVC_VIRTUAL_SERVER,
    build_time_command_new, decode_event,
)
from lib.ble.client import GShockBLE
from lib.tui.widgets import TUILogHandler, StatusPanel
from version import VERSION


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class GShockApp(App):
    """Casio G-Shock BLE debug terminal interface."""

    TITLE     = f"G-Shock BLE Debug TUI  v{VERSION}"
    SUB_TITLE = "PC → BLE Client (bleak)"

    CSS = """
    Screen {
        layout: vertical;
    }

    #top-row {
        height: 1fr;
        layout: horizontal;
    }

    #left-col {
        width: 40;
        layout: vertical;
    }

    #right-col {
        width: 1fr;
        layout: vertical;
    }

    #status-panel {
        height: auto;
        min-height: 18;
        border: round $primary;
        padding: 0 1;
    }

    #decoded-log {
        height: 1fr;
        border: round $accent;
        padding: 0 1;
    }

    #raw-log {
        height: 14;
        border: round $warning;
        padding: 0 1;
    }

    #decoded-log-title {
        color: $accent;
        text-style: bold;
        height: 1;
        margin: 0 1;
    }

    #raw-log-title {
        color: $warning;
        text-style: bold;
        height: 1;
        margin: 0 1;
    }

    #status-title {
        color: $primary;
        text-style: bold;
        height: 1;
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit",          "Quit"),
        Binding("s", "scan",          "Scan/Rescan"),
        Binding("t", "send_time",     "Sync Time"),
        Binding("c", "clear_logs",    "Clear Logs"),
        Binding("i", "probe_info",    "Watch Info"),
        Binding("d", "dump_features", "Dump Features"),
    ]

    def __init__(self, debug: bool = False) -> None:
        super().__init__()
        self._debug = debug
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._ble: Optional[GShockBLE] = None
        self._ble_task: Optional[asyncio.Task] = None
        self._queue_task: Optional[asyncio.Task] = None

        self._log_file = None
        self._log_path: Optional[Path] = None
        self._log_device_name: Optional[str] = None

        handler = TUILogHandler(self._event_queue)
        handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
        logging.getLogger("gshock_ble").addHandler(handler)
        logging.getLogger("gshock_ble").setLevel(logging.DEBUG)
        logging.getLogger("bleak").addHandler(handler)
        logging.getLogger("bleak").setLevel(logging.WARNING)

    # ------------------------------------------------------------------
    # File logging helpers
    # ------------------------------------------------------------------

    _MARKUP_RE = re.compile(r"\[/?[^\]]*\]")

    @staticmethod
    def _strip_markup(text: str) -> str:
        return GShockApp._MARKUP_RE.sub("", text)

    def _open_log_file(self) -> None:
        log_dir = Path(__file__).parent.parent.parent   # project root
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self._log_path = log_dir / f"gshock_{ts}.txt"
        self._log_file = open(self._log_path, "w", encoding="utf-8", buffering=1)
        self._log_raw(f"=== G-Shock BLE Session  {ts} ===\n")

    def _finalise_log_filename(self, device_name: str) -> None:
        """Rename the log file to include the device name (called once on connect)."""
        if self._log_device_name is not None or not self._log_path:
            return
        self._log_device_name = device_name
        safe_name = re.sub(r"[^\w\-]", "_", device_name).strip("_") or "GSHOCK"
        date_str  = datetime.datetime.now().strftime("%Y-%m-%d")
        new_path  = self._log_path.parent / f"{safe_name}_{date_str}.txt"
        try:
            self._log_file.flush()
            self._log_file.close()
            os.rename(self._log_path, new_path)
            self._log_path = new_path
            self._log_file = open(self._log_path, "a", encoding="utf-8", buffering=1)
            self._log_raw(f"=== Connected to: {device_name} ===\n")
        except OSError:
            self._log_file = open(self._log_path, "a", encoding="utf-8", buffering=1)

    def _log_raw(self, text: str) -> None:
        if self._log_file:
            try:
                self._log_file.write(text)
            except Exception:
                pass

    def _log(self, text: str) -> None:
        self._log_raw(self._strip_markup(text) + "\n")

    def _close_log_file(self) -> None:
        if self._log_file:
            try:
                self._log_raw(
                    f"\n=== Session ended  "
                    f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n"
                )
                self._log_file.close()
            except Exception:
                pass
            self._log_file = None

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="top-row"):
            with Vertical(id="left-col"):
                yield Label(" STATUS", id="status-title")
                yield StatusPanel(id="status-panel")
            with Vertical(id="right-col"):
                yield Label(" DECODED COMMANDS", id="decoded-log-title")
                yield RichLog(id="decoded-log", highlight=True, markup=True, wrap=True)
        yield Label(" RAW BLE LOG", id="raw-log-title")
        yield RichLog(id="raw-log", highlight=True, markup=True, wrap=False)
        yield Footer()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        if self._debug:
            self._open_log_file()
        self._queue_task = asyncio.create_task(self._process_queue())
        self._start_ble()
        self.set_interval(1.0, self._refresh_status)

    async def on_unmount(self) -> None:
        if self._ble_task:
            self._ble_task.cancel()
        if self._queue_task:
            self._queue_task.cancel()
        if self._ble:
            await self._ble.stop()
        self._close_log_file()

    # ------------------------------------------------------------------
    # BLE setup
    # ------------------------------------------------------------------

    def _start_ble(self) -> None:
        self._ble = GShockBLE(
            on_event  = self._on_ble_event,
            on_status = self._on_ble_status,
        )
        self._ble_task = asyncio.create_task(self._ble.run())

    def _on_ble_event(self, evt: BLEEvent) -> None:
        try:
            self._event_queue.put_nowait(evt)
        except Exception:
            pass

    def _on_ble_status(self, msg: str) -> None:
        try:
            self._event_queue.put_nowait((msg, "status"))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Queue processor
    # ------------------------------------------------------------------

    async def _process_queue(self) -> None:
        while True:
            item = await self._event_queue.get()
            try:
                if isinstance(item, BLEEvent):
                    self._handle_ble_event(item)
                elif isinstance(item, tuple):
                    msg, kind = item
                    if kind in ("status", "log"):
                        self._append_status(msg)
            except Exception:
                pass

    def _handle_ble_event(self, evt: BLEEvent) -> None:
        raw_log     = self.query_one("#raw-log",     RichLog)
        decoded_log = self.query_one("#decoded-log", RichLog)
        status      = self.query_one("#status-panel", StatusPanel)

        status.inc_events()
        if evt.direction == "TX":
            status.set_last_tx(evt.timestamp)
        if self._ble:
            status.set_connection(
                self._ble.connected,
                self._ble.device_name,
                self._ble.device_addr,
                self._ble.watch_gen,
            )
            if self._ble.connected and self._ble.device_name not in ("", "—"):
                self._finalise_log_filename(self._ble.device_name)

        DIR_COLOR = {
            "TX":   "cyan",
            "RX":   "green",
            "SYS":  "yellow",
            "SCAN": "blue",
        }
        color = DIR_COLOR.get(evt.direction, "dim")

        if evt.direction == "SCAN":
            is_casio = evt.details.get("is_casio", False)
            marker   = " [bold blue][CASIO][/bold blue]" if is_casio else ""
            raw_log.write(
                f"[{evt.timestamp}] [blue]SCAN[/blue]{marker} "
                f"{markup_escape(evt.raw_hex[:120])}"
            )
            self._log(f"[{evt.timestamp}] SCAN{'  [CASIO]' if is_casio else ''}  {evt.raw_hex[:120]}")
            if is_casio:
                decoded_log.write(
                    f"\n[bold blue][{evt.timestamp}] CASIO CANDIDATE FOUND[/bold blue]"
                )
                self._log(f"\n[{evt.timestamp}] CASIO CANDIDATE FOUND")
                for k, v in evt.details.items():
                    decoded_log.write(
                        f"  [bold]{markup_escape(str(k))}[/bold] = "
                        f"[yellow]{markup_escape(str(v))}[/yellow]"
                    )
                    self._log(f"  {k} = {v}")
            return

        raw_log.write(
            f"[{evt.timestamp}] [{color}]{evt.direction:4s}[/{color}] "
            f"{markup_escape(evt.char_label):24s}  {markup_escape(evt.raw_hex)}"
        )
        self._log(f"[{evt.timestamp}] {evt.direction:<4s}  {evt.char_label:<24s}  {evt.raw_hex}")

        if evt.direction == "SYS":
            decoded_log.write(
                f"\n[bold yellow][{evt.timestamp}] {markup_escape(evt.feature_name)}[/bold yellow]"
            )
            self._log(f"\n[{evt.timestamp}] SYS {evt.feature_name}")
            for line in evt.raw_hex.splitlines():
                decoded_log.write(f"[dim]{markup_escape(line)}[/dim]")
                self._log(line)
            return

        feat_color = "cyan" if evt.direction == "TX" else "green"
        decoded_log.write(
            f"\n[bold {feat_color}][{evt.timestamp}] {markup_escape(evt.direction)} "
            f"{markup_escape(evt.feature_name)}[/bold {feat_color}]"
        )
        self._log(f"\n[{evt.timestamp}] {evt.direction} {evt.feature_name}")
        decoded_log.write(f"  [dim]char: {markup_escape(evt.char_label)}[/dim]")
        decoded_log.write(f"  [dim]raw : {markup_escape(evt.raw_hex)}[/dim]")
        self._log(f"  char: {evt.char_label}")
        self._log(f"  raw : {evt.raw_hex}")
        for k, v in evt.details.items():
            decoded_log.write(
                f"  [bold]{markup_escape(str(k))}[/bold] = "
                f"[yellow]{markup_escape(str(v))}[/yellow]"
            )
            self._log(f"  {k} = {v}")
        if evt.note:
            decoded_log.write(f"  [italic cyan]>> {markup_escape(evt.note)}[/italic cyan]")
            self._log(f"  >> {evt.note}")

    def _append_status(self, msg: str) -> None:
        status = self.query_one("#status-panel", StatusPanel)
        lines  = [l for l in msg.splitlines() if l.strip()]
        display = lines[0][:120] if lines else msg[:120]
        status.set_status(display)
        self._log(f"[{self._ts()}] STATUS  {msg}")

        if len(lines) > 2:
            raw_log = self.query_one("#raw-log", RichLog)
            raw_log.write(f"[dim][SYS] {markup_escape(msg[:300])}[/dim]")

        if self._ble:
            status.set_connection(
                self._ble.connected,
                self._ble.device_name,
                self._ble.device_addr,
                self._ble.watch_gen,
            )

    def _refresh_status(self) -> None:
        panel = self.query_one("#status-panel", StatusPanel)
        panel.tick()
        if self._ble:
            panel.set_connection(
                self._ble.connected,
                self._ble.device_name,
                self._ble.device_addr,
                self._ble.watch_gen,
            )

    # ------------------------------------------------------------------
    # Key actions
    # ------------------------------------------------------------------

    async def action_quit(self) -> None:
        if self._ble:
            await self._ble.stop()
        self.exit()

    async def action_scan(self) -> None:
        if self._ble:
            await self._ble.rescan()
            self._append_status("Rescanning for G-Shock watches…")

    async def action_send_time(self) -> None:
        if not self._ble:
            return
        if self._ble.connected:
            ok  = await self._ble.send_time()
            msg = "Time sync sent." if ok else "Time sync failed (see log)."
        else:
            msg = "Not connected – cannot send time."
        self._append_status(msg)

    async def action_clear_logs(self) -> None:
        self.query_one("#raw-log",     RichLog).clear()
        self.query_one("#decoded-log", RichLog).clear()

    async def action_probe_info(self) -> None:
        if not self._ble or not self._ble.connected:
            self._append_status("Not connected.")
            return
        for code in [0x23, 0x20, 0x26, 0x28, 0x11, 0x13]:
            await self._ble.request_feature(code)
            await asyncio.sleep(0.3)
        self._append_status("Watch info probe sent (name/version/module/battery/ble/basic).")

    async def action_dump_features(self) -> None:
        if not self._ble or not self._ble.connected:
            self._append_status("Not connected.")
            return
        codes = [0x10, 0x23, 0x20, 0x26, 0x28, 0x11, 0x13, 0x15, 0x16,
                 0x1D, 0x1F, 0x22, 0x39, 0x3A, 0x3B]
        decoded_log = self.query_one("#decoded-log", RichLog)
        decoded_log.write(
            f"\n[bold magenta][{self._ts()}] FEATURE DUMP STARTED[/bold magenta]"
        )
        for code in codes:
            await self._ble.request_feature(code)
            await asyncio.sleep(0.4)
        decoded_log.write(
            f"[bold magenta][{self._ts()}] FEATURE DUMP COMPLETE[/bold magenta]"
        )

    def _ts(self) -> str:
        return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]


# ---------------------------------------------------------------------------
# Splash screen
# ---------------------------------------------------------------------------

def _rainbow_splash(art_path: Path) -> None:
    """Display ascii-art.txt centered, animated through a rainbow, for ~1 second."""
    import shutil
    import time

    try:
        lines = art_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return

    def hsv_to_rgb(hue: float) -> tuple:
        h = hue % 360
        c = 1.0
        x = c * (1 - abs((h / 60) % 2 - 1))
        if   h < 60:  r, g, b = c, x, 0.0
        elif h < 120: r, g, b = x, c, 0.0
        elif h < 180: r, g, b = 0.0, c, x
        elif h < 240: r, g, b = 0.0, x, c
        elif h < 300: r, g, b = x, 0.0, c
        else:         r, g, b = c, 0.0, x
        return int(r * 255), int(g * 255), int(b * 255)

    cols, rows = shutil.get_terminal_size(fallback=(80, 24))
    art_h = len(lines)
    art_w = max(len(l) for l in lines)
    top  = max(0, (rows - art_h) // 2)
    left = max(0, (cols - art_w) // 2)

    FRAMES   = 20
    INTERVAL = 1.0 / FRAMES

    sys.stdout.write("\x1b[?25l\x1b[2J")
    sys.stdout.flush()
    try:
        for frame in range(FRAMES):
            hue_base = frame * (360 / FRAMES)
            buf = []
            for i, line in enumerate(lines):
                hue = (hue_base + i * (360 / art_h)) % 360
                r, g, b = hsv_to_rgb(hue)
                buf.append(
                    f"\x1b[{top + i + 1};{left + 1}H"
                    f"\x1b[38;2;{r};{g};{b}m{line}\x1b[0m"
                )
            sys.stdout.write("".join(buf))
            sys.stdout.flush()
            time.sleep(INTERVAL)
    finally:
        sys.stdout.write("\x1b[0m\x1b[?25h")
        sys.stdout.flush()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    debug = "--debug" in sys.argv

    art_path = Path(__file__).parent.parent.parent / "ascii-art.txt"
    if art_path.exists():
        _rainbow_splash(art_path)

    logging.getLogger("bleak.backends.winrt").setLevel(logging.WARNING)
    logging.getLogger("bleak.backends.winrt.scanner").setLevel(logging.WARNING)
    logging.getLogger("bleak.backends.winrt.client").setLevel(logging.WARNING)

    app = GShockApp(debug=debug)
    app.run()
