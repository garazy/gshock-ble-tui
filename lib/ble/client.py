"""
G-Shock BLE client — PC-side GATT central (uses bleak).

Supports:
  NEW protocol  GW-B5600, GBD-800, GMW-B5600, GA-B2100, …
                Advertises 0x1804 (TX Power).  Service 26eb000d.
  OLD protocol  GB-5600, GB-6900, GB-X6900, STB-1000, …
                Advertises 0x1802 (Immediate Alert) or 0x1803 (Link Loss).
                Services 26eb0007 (Virtual Server) + 26eb0002 (Current Time).

Scan strategy:
  - No service-UUID filter → see ALL nearby BLE devices for maximum debug info.
  - Every new device is logged as a SCAN event.
  - A device is a "Casio candidate" if it advertises a known Casio UUID OR its
    name contains a Casio model string.
  - Connect to the first candidate found.
  - After connecting, detect watch generation by inspecting GATT services and
    dispatch to the appropriate protocol handler.
"""

import asyncio
import logging
from typing import Callable, Optional, Set

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakError, BleakDeviceNotFoundError

from lib.protocol import (
    # new watch
    NEW_SERVICE_UUID,
    CHAR_READ_REQUEST, CHAR_ALL_FEATURES,
    NEW_NOTIFY_CHAR_UUIDS,
    # old watch
    OLD_SVC_VIRTUAL_SERVER, OLD_SVC_IMMEDIATE_ALERT, OLD_SVC_ALERT_NOTIF,
    OLD_CHAR_VS_FEATURE, OLD_CHAR_A_NOT_W_REQ, OLD_CHAR_A_NOT_COM_SET,
    OLD_CHAR_NEW_ALERT, OLD_CHAR_ALERT_NOTIF_CP,
    STD_CHAR_CURRENT_TIME, STD_CHAR_LOCAL_TIME, STD_CHAR_ALERT_LEVEL,
    OLD_NOTIFY_CHAR_UUIDS,
    # shared
    ALL_CASIO_ADV_UUIDS, CASIO_UUID_PREFIX, UUID_LABELS,
    # encoders / events
    build_time_command_new, encode_time_old, encode_local_time, encode_new_alert,
    get_ntp_time, decode_event, make_sys_event, make_scan_event,
    BLEEvent,
)

logger = logging.getLogger(__name__)

# Name fragments that identify a Casio/G-Shock device regardless of UUID
CASIO_NAME_TOKENS = (
    "CASIO", "GW-", "GBD", "GMW", "GST", "MRG", "MSG",
    "ECB", "GA-B", "GBX", "GB-", "G-SHOCK", "GSHOCK",
    "STB", "WSD",
)

EventCallback  = Callable[[BLEEvent], None]
StatusCallback = Callable[[str], None]


class GShockBLE:
    """
    Scans for any nearby G-Shock watch, connects as a GATT client, logs all
    traffic, auto-detects the watch generation, and attempts time sync.
    """

    def __init__(self, on_event: EventCallback, on_status: StatusCallback):
        self._on_event  = on_event
        self._on_status = on_status

        self._client:       Optional[BleakClient] = None
        self._device_name:  str  = "—"
        self._device_addr:  str  = "—"
        self._connected:    bool = False
        self._watch_gen:    str  = "?"   # "NEW" | "OLD" | "UNKNOWN"

        self._stop_event:      asyncio.Event = asyncio.Event()
        self._found_event:     asyncio.Event = asyncio.Event()
        self._found_device:    Optional[BLEDevice] = None
        self._found_adv:       Optional[AdvertisementData] = None
        self._handshake_event: asyncio.Event = asyncio.Event()
        # Serialises concurrent old-watch time writes (reactive vs. manual)
        self._old_time_lock:   asyncio.Lock  = asyncio.Lock()
        # feature_code → Future[bytes]: used by _request_and_echo to pair responses
        self._response_futures: dict = {}
        # Pending alerts to deliver when the next watch connects
        self._alert_queue: list = []   # list of (category: int, count: int, text: str)

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def device_name(self) -> str:
        return self._device_name

    @property
    def device_addr(self) -> str:
        return self._device_addr

    @property
    def watch_gen(self) -> str:
        return self._watch_gen

    @property
    def alert_queue_depth(self) -> int:
        return len(self._alert_queue)

    # ------------------------------------------------------------------
    # Public control
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Main loop: scan → connect → protocol → repeat."""
        while not self._stop_event.is_set():
            try:
                await self._scan_loop()
                if self._found_device and not self._stop_event.is_set():
                    await self._connect_and_run(self._found_device)
            except asyncio.CancelledError:
                break
            except (BleakError, BleakDeviceNotFoundError) as exc:
                self._status(f"BLE error – will rescan: {exc}")
                logger.warning("BLE error: %s", exc)
                await asyncio.sleep(2)
            except OSError as exc:
                self._status(f"OS/BLE error – will rescan: {exc}")
                logger.warning("OS BLE error: %s", exc)
                await asyncio.sleep(2)
            except Exception as exc:
                self._status(f"Unexpected error: {type(exc).__name__}: {exc}")
                logger.exception("BLE loop unexpected error")
                await asyncio.sleep(3)

        self._status("BLE stopped.")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._client and self._connected:
            try:
                await self._client.disconnect()
            except Exception:
                pass

    async def rescan(self) -> None:
        """Disconnect and restart the scan."""
        self._found_event.clear()
        self._found_device = None
        self._found_adv    = None
        if self._client and self._connected:
            try:
                await self._client.disconnect()
            except Exception:
                pass

    async def send_time(self) -> bool:
        """Send current local time to the connected watch."""
        if not self._connected or not self._client:
            self._status("Cannot send time: not connected.")
            return False
        if self._watch_gen == "OLD":
            return await self._send_time_old()
        return await self._send_time_new()

    async def request_feature(self, feature_code: int) -> bool:
        """
        NEW-watch: write [feature_code] → CHAR_READ_REQUEST (0x0C).
        OLD-watch: not directly applicable; logged as unsupported.
        """
        if not self._connected or not self._client:
            return False
        if self._watch_gen == "OLD":
            self._status(
                f"feature request 0x{feature_code:02X} not applicable for old watch"
            )
            return False
        cmd = bytes([feature_code])
        self._emit_tx(cmd, CHAR_READ_REQUEST, f"request 0x{feature_code:02X}")
        try:
            await self._write_char(CHAR_READ_REQUEST, cmd, prefer_response=False)
            return True
        except Exception as exc:
            self._status(
                f"request_feature 0x{feature_code:02X} failed: "
                f"{type(exc).__name__}: {exc}"
            )
            return False

    def queue_alert(self, category: int, count: int, text: str) -> None:
        """Add an alert to the queue; it will be delivered when the next watch connects."""
        self._alert_queue.append((category, count, text))
        self._status(
            f"Alert queued (depth={len(self._alert_queue)}): "
            f"cat={category} '{text}' — will send on next connection."
        )

    async def _flush_alert_queue(self) -> None:
        """Drain the alert queue to the connected watch (OLD protocol only)."""
        if not self._alert_queue:
            return
        if not self._connected or not self._client:
            return
        if self._watch_gen != "OLD":
            self._status(
                f"Alert queue has {len(self._alert_queue)} item(s) but alerts are only "
                "supported on OLD watches (GB-series) — clearing queue."
            )
            self._alert_queue.clear()
            return
        self._status(f"Flushing {len(self._alert_queue)} queued alert(s) to watch…")
        while self._alert_queue:
            cat, cnt, text = self._alert_queue.pop(0)
            ok = await self.send_alert(cat, cnt, text)
            self._status(
                f"Queued alert {'sent' if ok else 'FAILED'}: cat={cat} '{text}'"
            )
            await asyncio.sleep(0.3)

    async def send_alert(self, category: int, count: int, text: str) -> bool:
        """Push a notification alert to an OLD watch via New Alert (00002a46)."""
        client = self._client
        if not client or self._watch_gen != "OLD":
            return False
        svc = client.services.get_service(OLD_SVC_ALERT_NOTIF)
        if svc is None:
            self._status("Alert Notification Service (26eb0000) not found on this watch.")
            return False
        char = svc.get_characteristic(OLD_CHAR_NEW_ALERT)
        if char is None:
            self._status("NEW_ALERT characteristic (00002a46) not found in alert service.")
            return False
        data = encode_new_alert(category, count, text)
        self._emit_tx(data, OLD_CHAR_NEW_ALERT, f"NEW_ALERT cat={category}")
        try:
            await client.write_gatt_char(char.handle, data, response=False)
            return True
        except Exception as exc:
            self._status(f"NEW_ALERT write failed: {type(exc).__name__}: {exc}")
            return False

    async def send_raw(self, char_uuid: str, data: bytes,
                       response: bool = False) -> bool:
        """Send arbitrary bytes to any characteristic (debug helper)."""
        if not self._connected or not self._client:
            return False
        self._emit_tx(data, char_uuid, "raw-send")
        try:
            await self._write_char(char_uuid, data, prefer_response=response)
            return True
        except Exception as exc:
            self._status(f"send_raw failed: {type(exc).__name__}: {exc}")
            return False

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def _is_casio_candidate(self, device: BLEDevice,
                             adv: AdvertisementData) -> bool:
        adv_uuids_low = {str(u).lower() for u in adv.service_uuids}
        name_up = (device.name or "").upper()

        has_casio_uuid   = bool(adv_uuids_low & {u.lower() for u in ALL_CASIO_ADV_UUIDS})
        has_casio_prefix = any(u.startswith(CASIO_UUID_PREFIX) for u in adv_uuids_low)
        has_casio_name   = any(tok in name_up for tok in CASIO_NAME_TOKENS)

        return has_casio_uuid or has_casio_prefix or has_casio_name

    async def _scan_loop(self) -> None:
        self._found_event.clear()
        self._found_device = None
        self._status("Scanning all nearby BLE devices (no UUID filter)…")

        seen_addrs: Set[str] = set()

        def _detection_cb(device: BLEDevice, adv: AdvertisementData) -> None:
            addr     = device.address
            is_casio = self._is_casio_candidate(device, adv)
            uuids    = [str(u) for u in adv.service_uuids]

            if addr not in seen_addrs:
                seen_addrs.add(addr)
                evt = make_scan_event(device.name or "", addr,
                                      adv.rssi or 0, uuids, is_casio)
                self._on_event(evt)
                if is_casio:
                    self._status(
                        f"CASIO CANDIDATE: {device.name or 'unnamed'} "
                        f"[{addr}] RSSI={adv.rssi} "
                        f"uuids={[str(u)[:8] for u in adv.service_uuids]}"
                    )

            if is_casio and not self._found_event.is_set():
                self._found_device = device
                self._found_adv    = adv
                self._found_event.set()

        scanner = BleakScanner(detection_callback=_detection_cb)
        await scanner.start()
        try:
            await asyncio.wait_for(self._found_event.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            n = len(seen_addrs)
            self._status(
                f"No G-Shock found in 30 s ({n} device(s) seen) – rescanning…"
            )
        finally:
            await scanner.stop()

    # ------------------------------------------------------------------
    # Connection dispatch
    # ------------------------------------------------------------------

    def _adv_likely_new(self) -> bool:
        """Return True if the stored advertisement looks like a new-protocol watch.

        New watches advertise 0x1804 (TX Power Level service).
        Old watches advertise 0x1802 / 0x1803 (Immediate Alert / Link Loss).
        When in doubt (no recognisable UUIDs), assume new so we get fresh GATT.
        """
        adv = self._found_adv
        if adv is None:
            return True
        uuids_low = {str(u).lower() for u in adv.service_uuids}
        if "00001804-0000-1000-8000-00805f9b34fb" in uuids_low:
            return True
        if uuids_low & {
            "00001802-0000-1000-8000-00805f9b34fb",
            "00001803-0000-1000-8000-00805f9b34fb",
        }:
            return False
        return True

    async def _connect_and_run(self, device: BLEDevice) -> None:
        name = device.name or "unnamed"
        addr = device.address
        self._status(f"Connecting to {name} [{addr}]…")

        def _disc_cb(client: BleakClient) -> None:
            self._connected   = False
            self._device_name = "—"
            self._device_addr = "—"
            self._watch_gen   = "?"
            self._status("Watch disconnected.")

        # New watches need fresh GATT discovery (stale Windows cache causes
        # get_gatt_services_async() → UNREACHABLE).  Old watches bond during
        # or immediately after connect; forcing a re-read can make the OS
        # BLE stack time out while waiting for the device to respond.
        likely_new = self._adv_likely_new()
        self._status(
            f"{'New' if likely_new else 'Old'}-protocol heuristic from advertisement "
            f"(use_cached_services={'False' if likely_new else 'True (default)'})"
        )
        conn_kwargs: dict = {
            "disconnected_callback": _disc_cb,
            "timeout": 30.0,
        }
        if likely_new:
            conn_kwargs["winrt"] = {"use_cached_services": False}

        # On Windows, the BLEDevice object from the scanner may become stale
        # once the scanner stops (OS drops device tracking).  If the first
        # attempt times out, retry using the raw address string which forces
        # Windows to do a fresh BluetoothLEDevice.FromBluetoothAddressAsync()
        # lookup — effective for old watches whose connection window is short.
        targets = [device, addr]   # BLEDevice first, address string fallback
        last_exc: Optional[Exception] = None

        for target in targets:
            label = "BLEDevice" if target is device else "addr-string fallback"
            self._status(f"Connect attempt ({label})…")
            try:
                async with BleakClient(target, **conn_kwargs) as client:
                    self._client      = client
                    self._connected   = True
                    self._device_name = name
                    self._device_addr = addr

                    gen = self._detect_generation(client)
                    self._watch_gen = gen
                    self._status(f"Connected: {name} [{addr}]  generation={gen}")
                    await self._dump_services(client)

                    if gen == "OLD":
                        await self._ensure_paired(client, name)

                    if gen == "NEW":
                        await self._run_new_protocol(client)
                    elif gen == "OLD":
                        await self._run_old_protocol(client)
                    else:
                        self._status(
                            "Unknown watch type – subscribing to everything and waiting. "
                            "Check the decoded log for clues."
                        )
                        await self._subscribe_all_notify(client)
                        while client.is_connected and not self._stop_event.is_set():
                            await asyncio.sleep(1.0)

                return   # session completed normally

            except asyncio.TimeoutError:
                self._status(f"Connection timed out ({label}) [{name}]")
                logger.warning("Connection timed out (%s) for %s", label, addr)
                last_exc = None   # will retry or fall through
            except (BleakError, BleakDeviceNotFoundError) as exc:
                self._status(f"Connection failed ({label}) [{name}]: {exc}")
                logger.warning("Connection failed (%s) %s: %s", label, addr, exc)
                last_exc = exc
                break   # non-timeout error — no point retrying
            except OSError as exc:
                self._status(f"OS/BLE error ({label}) [{name}]: {exc}")
                logger.warning("OS BLE error (%s) %s: %s", label, addr, exc)
                last_exc = exc
                break
            finally:
                self._client    = None
                self._connected = False

        if last_exc is None:
            # Both attempts timed out
            self._status(
                f"All connection attempts timed out for {name}. "
                "If this is an old-protocol watch (GB-5600 / GB-6900), "
                "press the BLE/PHONE button on the watch face first — "
                "the watch only accepts connections when actively in BLE mode."
            )

    # ------------------------------------------------------------------
    # Pairing (old watches only)
    # ------------------------------------------------------------------

    async def _ensure_paired(self, client: BleakClient, name: str) -> None:
        """Trigger OS BLE pairing flow.  On Windows this shows the system dialog
        prompting the user to enter the 6-digit PIN from the watch face.
        Idempotent — already-bonded watches return immediately."""
        self._status(
            f"Old-protocol watch detected ({name}).  "
            "If a PIN is shown on the watch, enter it in the Windows "
            "pairing dialog that should appear now…"
        )
        try:
            paired = await client.pair()
            if paired:
                self._status("Pairing successful (or already bonded).")
            else:
                self._status(
                    "client.pair() returned False — watch may still work "
                    "if already bonded at OS level."
                )
        except Exception as exc:
            self._status(
                f"Pairing attempt raised {type(exc).__name__}: {exc}  "
                "— continuing anyway (watch may already be bonded)."
            )

    # ------------------------------------------------------------------
    # Generation detection
    # ------------------------------------------------------------------

    def _detect_generation(self, client: BleakClient) -> str:
        svc_uuids = {str(s.uuid).lower() for s in client.services}
        # Check for OLD protocol first - some watches (GB-5600B) have both
        # OLD and NEW services but are fundamentally OLD protocol watches
        if OLD_SVC_VIRTUAL_SERVER.lower() in svc_uuids:
            return "OLD"
        if any(u.startswith(CASIO_UUID_PREFIX) for u in svc_uuids):
            return "OLD"
        if NEW_SERVICE_UUID.lower() in svc_uuids:
            return "NEW"
        return "UNKNOWN"

    # ------------------------------------------------------------------
    # NEW watch protocol  (GW-B5600 etc.)
    # ------------------------------------------------------------------

    async def _run_new_protocol(self, client: BleakClient) -> None:
        self._status("NEW watch protocol: subscribing to notification characteristics…")
        self._handshake_event.clear()

        for uuid in NEW_NOTIFY_CHAR_UUIDS:
            await self._try_subscribe(client, uuid)

        await asyncio.sleep(0.2)

        # Ask the watch why it connected (button press / auto sync).
        # The watch responds with a 0x10 notification; _on_new_handshake()
        # picks that up and runs the DST prepare sequence then sends time.
        await self._request_feature_raw(client, 0x10, "button/reason")

        try:
            await asyncio.wait_for(self._handshake_event.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            self._status("No 0x10 response from watch in 10 s — sending time anyway…")
            await self._send_time_new()

        # Poll for watch info after time sync
        await asyncio.sleep(0.5)
        for code, label in [
            (0x23, "watch name"),
            (0x20, "firmware version"),
            (0x26, "module ID"),
            (0x28, "battery+temp"),
            (0x11, "time-adj setting"),
        ]:
            if not client.is_connected:
                break
            await self._request_feature_raw(client, code, label)
            await asyncio.sleep(0.3)

        # Wait briefly so the user can still use manual keys before disconnect
        for _ in range(10):
            if not client.is_connected or self._stop_event.is_set():
                break
            await asyncio.sleep(1.0)

        if client.is_connected:
            self._status("Session complete — disconnecting from watch.")
            try:
                await client.disconnect()
            except Exception as exc:
                self._status(f"Disconnect error: {exc}")

    async def _on_new_handshake(self) -> None:
        """Called when the watch sends its 0x10 notification (connection reason).
        Runs the DST/world-city prepare sequence, then sends time."""
        if self._handshake_event.is_set():
            return
        client = self._client
        if not client:
            return
        await self._prepare_time_set(client)
        await self._send_time_new()
        self._handshake_event.set()
        if self._alert_queue:
            self._status(
                f"Note: {len(self._alert_queue)} queued alert(s) — "
                "NEW watches do not support alert push; clearing queue."
            )
            self._alert_queue.clear()

    def _watch_model_config(self) -> tuple:
        """Return (dstCount, worldCitiesCount) for the connected watch.

        Derived from the advertised device name prefix:
          GW, GMW, MRG          → (3, 6)   full world-city set
          GA, DW, GB, GM, GBD,
          GPR, MSG, ECB, DW_H   → (1, 2)   small set
          GST, ABL               → (1, 2)   hasWorldCities=False but still echo
          default / unknown      → (1, 2)   safe fallback
        """
        name  = self._device_name or ""
        parts = name.split()
        short = parts[1].strip('\x00 \t\n\r') if len(parts) > 1 else ""

        if short in {"ECB-10", "ECB-20", "ECB-30"}:
            return (1, 2)

        prefix_table = [
            ("GMW",       (3, 6)),
            ("GW-BX5600", (1, 2)),
            ("GM-B2100",  (1, 2)),
            ("GW",        (3, 6)),
            ("MRG",       (3, 6)),
            ("GBM",       (1, 2)),
            ("GBD",       (1, 2)),
            ("GPR",       (1, 2)),
            ("MSG",       (1, 2)),
            ("DW-H",      (1, 2)),
            ("DW",        (1, 2)),
            ("GST",       (1, 2)),
            ("ABL",       (1, 2)),
            ("GA",        (1, 2)),
            ("GB",        (1, 2)),
            ("GM",        (1, 2)),
        ]
        for prefix, cfg in prefix_table:
            if short.startswith(prefix):
                return cfg
        return (1, 2)

    async def _prepare_time_set(self, client: BleakClient) -> None:
        """Read-then-echo-back DST/world-city config required before the watch
        will apply a time write.  Mirrors initialize_for_setting_time() from
        gshock-api-esp32.  Count is model-dependent (see _watch_model_config)."""
        dst_count, city_count = self._watch_model_config()
        for i in range(dst_count):
            await self._request_and_echo(client, bytes([0x1D, i]))
        for i in range(city_count):
            await self._request_and_echo(client, bytes([0x1E, i]))
        for i in range(city_count):
            await self._request_and_echo(client, bytes([0x1F, i]))

    async def _request_and_echo(self, client: BleakClient,
                                 request: bytes, timeout: float = 4.0) -> bool:
        """Write *request* to CHAR_READ_REQUEST, wait for a matching notification
        (keyed on request[0]), then write the response verbatim back to
        CHAR_ALL_FEATURES.  Returns True on success."""
        fc = request[0]
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._response_futures[fc] = fut

        self._emit_tx(request, CHAR_READ_REQUEST, f"prepare 0x{fc:02X}")
        try:
            await self._write_char_on(client, CHAR_READ_REQUEST, request,
                                       prefer_response=False)
        except Exception as exc:
            self._response_futures.pop(fc, None)
            self._status(f"prepare 0x{fc:02X} request failed: {exc}")
            return False

        try:
            response: bytes = await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._response_futures.pop(fc, None)
            self._status(f"prepare 0x{fc:02X}: no response in {timeout:.0f}s — skipping")
            return False

        self._emit_tx(response, CHAR_ALL_FEATURES, f"prepare echo-back 0x{fc:02X}")
        try:
            await self._write_char_on(client, CHAR_ALL_FEATURES, response,
                                       prefer_response=True)
            return True
        except Exception as exc:
            self._status(f"prepare 0x{fc:02X} echo-back failed: {exc}")
            return False

    async def _request_feature_raw(self, client: BleakClient,
                                    code: int, label: str) -> None:
        cmd = bytes([code])
        self._emit_tx(cmd, CHAR_READ_REQUEST, f"request 0x{code:02X} ({label})")
        try:
            await self._write_char_on(client, CHAR_READ_REQUEST, cmd,
                                       prefer_response=False)
        except Exception as exc:
            self._status(
                f"request 0x{code:02X} ({label}) failed: "
                f"{type(exc).__name__}: {exc}"
            )

    async def _send_time_new(self) -> bool:
        client = self._client
        if not client:
            return False
        ntp_dt = get_ntp_time()
        self._status(f"Time source: NTP → {ntp_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        cmd = build_time_command_new()
        self._emit_tx(cmd, CHAR_ALL_FEATURES, "NEW time-set command")
        for response_mode in (True, False):
            try:
                await client.write_gatt_char(CHAR_ALL_FEATURES, cmd,
                                             response=response_mode)
                self._status(f"Time sent (NEW watch, response={response_mode}).")
                self._emit_error_event(
                    f"Time sync OK (response={response_mode})", ok=True
                )
                return True
            except Exception as exc:
                err = (f"send_time_new(response={response_mode}): "
                       f"{type(exc).__name__}: {exc}")
                self._status(err)
                self._emit_error_event(err, ok=False)
        return False

    # ------------------------------------------------------------------
    # OLD watch protocol  (GB-5600, GB-6900 etc.)
    # ------------------------------------------------------------------

    async def _run_old_protocol(self, client: BleakClient) -> None:
        """
        Setup sequence from BleConfiguration.java / BleConfigurationServer.java (APK):
          1. Subscribe CCDs on 26eb0009 and 26eb000a FIRST (triggers WinRT BLE
             negotiations before the write-with-response on the link-loss char).
          2. Write link-loss alert level = 0x01 (MILD_ALERT) to Link Loss svc.
          3. Subscribe to optional notify chars (CIAS, CANS, CPASS).
          4. Wait — the watch drives everything via 26eb0009 notifications:
               [0x00, 0x00, 0x01] → init done
               [0x07, 0x00, 0x01] → write VS feature  → 26eb0008
               [0x02, 0x00, 0x02] → write local time  → 00002a0f
               [0x02, 0x00, 0x01] → write current time→ 00002a2b
        All reactive writes use WRITE_TYPE_DEFAULT (with-response), serialised FIFO.
        """
        self._status("OLD watch protocol (GB-5600/GB-6900): initialising…")

        for uuid in OLD_NOTIFY_CHAR_UUIDS:
            await self._try_subscribe(client, uuid)

        await asyncio.sleep(0.3)
        await self._write_alert_level_old(client)

        await self._subscribe_cias_alert(client)
        await self._try_subscribe(client, "00002a44-0000-1000-8000-00805f9b34fb")
        await self._try_subscribe(client, "00002a40-0000-1000-8000-00805f9b34fb")

        await asyncio.sleep(0.1)
        self._status("OLD watch init complete — waiting for watch notifications…")
        while client.is_connected and not self._stop_event.is_set():
            await asyncio.sleep(1.0)

    async def _subscribe_cias_alert(self, client: BleakClient) -> None:
        """Subscribe to CASIO Immediate Alert (26eb0005) AlertLevel notify.
        Must use the service object because 00002a06 appears in three services."""
        CIAS_SVC = "26eb0005-b012-49a8-b1f8-394fb2032b0f"
        svc  = client.services.get_service(CIAS_SVC)
        if svc is None:
            return
        char = svc.get_characteristic(STD_CHAR_ALERT_LEVEL)
        if char is None:
            return
        try:
            await client.start_notify(char.handle, self._notification_cb)
            self._status("Subscribed: CIAS AlertLevel (26eb0005/00002a06)")
        except Exception as exc:
            self._status(f"Subscribe CIAS AlertLevel (non-critical): {exc}")

    async def _write_alert_level_old(self, client: BleakClient) -> None:
        """Write MILD_ALERT (0x01) to the Link Loss service's Alert Level char.
        Targeted via service UUID to avoid the bleak 'Multiple Characteristics'
        error (00002a06 appears in 26eb0005, 00001802, and 00001803)."""
        LINK_LOSS_SVC = "00001803-0000-1000-8000-00805f9b34fb"
        for svc_uuid in (LINK_LOSS_SVC, OLD_SVC_IMMEDIATE_ALERT):
            svc  = client.services.get_service(svc_uuid)
            if svc is None:
                continue
            char = svc.get_characteristic(STD_CHAR_ALERT_LEVEL)
            if char is None:
                continue
            try:
                await client.write_gatt_char(char.handle, bytes([0x01]),
                                             response=True)
                self._status(
                    f"link-loss alert=MILD written to handle 0x{char.handle:02X} "
                    f"(svc {svc_uuid[:8]})"
                )
                return
            except Exception as exc:
                self._status(
                    f"link-loss alert write (h=0x{char.handle:02X}) failed: "
                    f"{type(exc).__name__}: {exc}"
                )
        self._status(
            "WARNING: could not find a suitable Alert Level characteristic — "
            "link-loss init skipped."
        )

    async def _send_time_old(self) -> bool:
        client = self._client
        if not client:
            return False
        async with self._old_time_lock:
            ntp_dt = get_ntp_time()
            self._status(f"Time source: NTP → {ntp_dt.strftime('%Y-%m-%d %H:%M:%S')}")
            lt_bytes = encode_local_time()
            self._emit_tx(lt_bytes, STD_CHAR_LOCAL_TIME, "OLD local-time-info")
            ok1 = await self._try_write(client, STD_CHAR_LOCAL_TIME,
                                         lt_bytes, prefer_response=True,
                                         label="LOCAL_TIME_INFO (old)")
            await asyncio.sleep(0.15)
            time_bytes = encode_time_old(ntp_dt)
            self._emit_tx(time_bytes, STD_CHAR_CURRENT_TIME, "OLD current-time")
            ok2 = await self._try_write(client, STD_CHAR_CURRENT_TIME,
                                         time_bytes, prefer_response=True,
                                         label="CURRENT_TIME (old)")
        if ok1 and ok2:
            self._status("Time sent (OLD watch).")
            return True
        return False

    def _handle_old_notification(self, svc_id: int, req: int) -> None:
        """React to a time/feature request notification from an old watch."""
        client = self._client
        if client is None:
            return
        if svc_id == 0x00 and req == 0x01:
            self._status("OLD watch: init handshake complete.")
            asyncio.get_event_loop().call_soon(
                lambda: asyncio.ensure_future(self._flush_alert_queue())
            )
        elif svc_id == 0x02 and req == 0x01:
            self._status("OLD watch: time request → writing current time…")
            asyncio.get_event_loop().call_soon(
                lambda: asyncio.ensure_future(self._reply_current_time())
            )
        elif svc_id == 0x02 and req == 0x02:
            self._status("OLD watch: local-time request → writing local time…")
            asyncio.get_event_loop().call_soon(
                lambda: asyncio.ensure_future(self._reply_local_time())
            )
        elif svc_id == 0x07:
            self._status("OLD watch: virtual-server feature request → resending…")
            asyncio.get_event_loop().call_soon(
                lambda: asyncio.ensure_future(self._reply_vs_feature())
            )

    async def _reply_current_time(self) -> None:
        client = self._client
        if not client:
            return
        async with self._old_time_lock:
            ntp_dt = get_ntp_time()
            data = encode_time_old(ntp_dt)
            self._emit_tx(data, STD_CHAR_CURRENT_TIME, "OLD time reply")
            await self._try_write(client, STD_CHAR_CURRENT_TIME, data,
                                   prefer_response=True, label="time reply (old)")

    async def _reply_local_time(self) -> None:
        client = self._client
        if not client:
            return
        async with self._old_time_lock:
            data = encode_local_time()
            self._emit_tx(data, STD_CHAR_LOCAL_TIME, "OLD local-time reply")
            await self._try_write(client, STD_CHAR_LOCAL_TIME, data,
                                   prefer_response=True, label="local-time reply (old)")

    async def _reply_vs_feature(self) -> None:
        client = self._client
        if not client:
            return
        async with self._old_time_lock:
            data = bytes([0x0F])
            self._emit_tx(data, OLD_CHAR_VS_FEATURE, "OLD VS feature reply")
            await self._try_write(client, OLD_CHAR_VS_FEATURE, data,
                                   prefer_response=True, label="VS feature reply (old)")

    # ------------------------------------------------------------------
    # "Subscribe everything" fallback (unknown generation)
    # ------------------------------------------------------------------

    async def _subscribe_all_notify(self, client: BleakClient) -> None:
        count = 0
        for svc in client.services:
            for char in svc.characteristics:
                props = set(char.properties)
                if "notify" in props or "indicate" in props:
                    uuid = str(char.uuid).lower()
                    await self._try_subscribe(client, uuid)
                    count += 1
        self._status(f"Subscribed to {count} notify/indicate characteristic(s).")

    # ------------------------------------------------------------------
    # Service / characteristic discovery dump
    # ------------------------------------------------------------------

    async def _dump_services(self, client: BleakClient) -> None:
        lines = ["=== GATT SERVICE DISCOVERY ==="]
        for svc in client.services:
            svc_label = UUID_LABELS.get(str(svc.uuid).lower(), str(svc.uuid))
            lines.append(f"  SVC  {svc.uuid}  {svc_label}")
            for char in svc.characteristics:
                props      = ",".join(char.properties)
                char_label = UUID_LABELS.get(str(char.uuid).lower(), str(char.uuid))
                lines.append(
                    f"    CHAR  {char.uuid}  h=0x{char.handle:02X}"
                    f"  [{props}]  {char_label}"
                )
                for desc in char.descriptors:
                    lines.append(f"      DESC  {desc.uuid}  h=0x{desc.handle:02X}")
        text = "\n".join(lines)
        self._status(f"Service discovery:\n{text}")
        self._on_event(BLEEvent(
            timestamp    = self._ts(),
            direction    = "SYS",
            char_label   = "DISCOVERY",
            raw_hex      = text,
            feature_name = "GATT_SERVICE_DISCOVERY",
            note         = f"gen={self._watch_gen}",
        ))

    # ------------------------------------------------------------------
    # Notification callback
    # ------------------------------------------------------------------

    def _notification_cb(self, char, data: bytearray) -> None:
        uuid = str(char.uuid).lower() if hasattr(char, "uuid") else str(char)
        raw  = bytes(data)
        evt  = decode_event(raw, char_uuid=uuid, direction="RX")
        self._on_event(evt)

        # Fulfill any pending _request_and_echo future
        if raw:
            fc  = raw[0]
            fut = self._response_futures.pop(fc, None)
            if fut is not None and not fut.done():
                fut.set_result(raw)

        # OLD watch: parse time/feature requests and auto-reply
        if uuid in (OLD_CHAR_A_NOT_W_REQ.lower(), OLD_CHAR_A_NOT_COM_SET.lower()):
            if len(data) >= 3:
                self._handle_old_notification(data[0], data[2])

        # NEW watch: 0x10 notification = watch is ready for time handshake
        elif evt.feature_code == 0x10 and self._watch_gen == "NEW":
            asyncio.get_event_loop().call_soon(
                lambda: asyncio.ensure_future(self._on_new_handshake())
            )

    # ------------------------------------------------------------------
    # Low-level write helpers
    # ------------------------------------------------------------------

    async def _try_subscribe(self, client: BleakClient, uuid: str) -> bool:
        label = UUID_LABELS.get(uuid.lower(), uuid[:22])
        try:
            await client.start_notify(uuid, self._notification_cb)
            self._status(f"Subscribed: {label}")
            return True
        except Exception as exc:
            self._status(f"Subscribe failed [{label}]: {exc}")
            return False

    async def _try_write(self, client: BleakClient, uuid: str, data: bytes,
                          prefer_response: bool, label: str = "") -> bool:
        try:
            await self._write_char_on(client, uuid, data, prefer_response)
            return True
        except Exception as exc:
            tag = label or uuid[:22]
            err = f"Write failed [{tag}]: {type(exc).__name__}: {exc}"
            self._status(err)
            self._emit_error_event(err, ok=False)
            return False

    async def _write_char_on(self, client: BleakClient, char_uuid: str,
                              data: bytes, prefer_response: bool) -> None:
        """Write to a characteristic, honouring its actual supported write type."""
        try:
            char = client.services.get_characteristic(char_uuid)
        except Exception:
            char = None

        if char is not None:
            props       = set(char.properties)
            has_write   = "write" in props
            has_no_rsp  = "write-without-response" in props
            if prefer_response:
                response = True if has_write else False
            else:
                response = False if has_no_rsp else True
        else:
            response = prefer_response

        await client.write_gatt_char(char_uuid, data, response=response)

    async def _write_char(self, char_uuid: str, data: bytes,
                           prefer_response: bool) -> None:
        if not self._client:
            raise BleakError("not connected")
        await self._write_char_on(self._client, char_uuid, data, prefer_response)

    # ------------------------------------------------------------------
    # Misc helpers
    # ------------------------------------------------------------------

    def _status(self, msg: str) -> None:
        logger.info(msg)
        self._on_status(msg)

    def _emit_error_event(self, msg: str, ok: bool = False) -> None:
        self._on_event(BLEEvent(
            timestamp    = self._ts(),
            direction    = "SYS",
            char_label   = "TIME_SYNC",
            raw_hex      = msg,
            feature_name = "TIME_SYNC_OK" if ok else "TIME_SYNC_ERROR",
            note         = msg,
        ))

    def _emit_tx(self, data: bytes, char_uuid: str, note: str = "") -> None:
        evt = decode_event(bytes(data), char_uuid=char_uuid.lower(),
                           direction="TX", note=note)
        self._on_event(evt)

    def _ts(self) -> str:
        import datetime
        return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
