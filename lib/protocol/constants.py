"""
G-Shock BLE protocol constants.

All UUID strings, feature/button name tables, and related lookup maps.

Sources:
  - gshock-api-esp32 (MicroPython / aioble client for newer watches)
    https://github.com/izivkov/gshock-api-esp32
  - Gadgetbridge CasioGB6900DeviceSupport.java (older series)
  - Casio G-Shock+ APK decompile (com.casio.gshockplus BleConstants.java etc.)
"""

from typing import Dict

# ---------------------------------------------------------------------------
# NEW watch  (GW-B5600, GBD-800, GMW-B5600, GA-B2100, …)
# ---------------------------------------------------------------------------

NEW_ADV_UUID      = "00001804-0000-1000-8000-00805f9b34fb"   # TX Power Level (scan filter)
NEW_SERVICE_UUID  = "26eb000d-b012-49a8-b1f8-394fb2032b0f"

CHAR_READ_REQUEST = "26eb002c-b012-49a8-b1f8-394fb2032b0f"   # 0x0C  write no-resp → request
CHAR_ALL_FEATURES = "26eb002d-b012-49a8-b1f8-394fb2032b0f"   # 0x0E  write resp → set time; notify ← resp
CHAR_NOTIFY       = "26eb0030-b012-49a8-b1f8-394fb2032b0f"   # 0x0D  notify only
CHAR_DATA_SP      = "26eb0023-b012-49a8-b1f8-394fb2032b0f"   # 0x11  notify
CHAR_CONVOY       = "26eb0024-b012-49a8-b1f8-394fb2032b0f"   # 0x14  notify

NEW_NOTIFY_CHAR_UUIDS = [CHAR_ALL_FEATURES, CHAR_DATA_SP, CHAR_CONVOY]

# ---------------------------------------------------------------------------
# OLD watch  (GB-5600, GB-6900, GB-X6900, STB-1000)
# ---------------------------------------------------------------------------

OLD_ADV_UUIDS = [
    "00001802-0000-1000-8000-00805f9b34fb",   # Immediate Alert Service
    "00001803-0000-1000-8000-00805f9b34fb",   # Link Loss Service
]

# Casio proprietary services (prefix 26eb????-b012-49a8-b1f8-394fb2032b0f)
OLD_SVC_ALERT_NOTIF     = "26eb0000-b012-49a8-b1f8-394fb2032b0f"
OLD_SVC_PHONE_ALERT     = "26eb0001-b012-49a8-b1f8-394fb2032b0f"
OLD_SVC_CURRENT_TIME    = "26eb0002-b012-49a8-b1f8-394fb2032b0f"   # time sync
OLD_SVC_IMMEDIATE_ALERT = "26eb0005-b012-49a8-b1f8-394fb2032b0f"
OLD_SVC_VIRTUAL_SERVER  = "26eb0007-b012-49a8-b1f8-394fb2032b0f"   # key old-watch identifier
OLD_SVC_KEY_COMMANDER   = "26eb0018-b012-49a8-b1f8-394fb2032b0f"
OLD_SVC_MORE_ALERT      = "26eb001a-b012-49a8-b1f8-394fb2032b0f"

# Characteristics (old watch)
OLD_CHAR_VS_FEATURE    = "26eb0008-b012-49a8-b1f8-394fb2032b0f"   # VS feature write [0x0F]
OLD_CHAR_A_NOT_W_REQ   = "26eb0009-b012-49a8-b1f8-394fb2032b0f"   # Watch→PC time/feature reqs
OLD_CHAR_A_NOT_COM_SET = "26eb000a-b012-49a8-b1f8-394fb2032b0f"   # Watch→PC init done
OLD_CHAR_SETTING_BLE   = "26eb000f-b012-49a8-b1f8-394fb2032b0f"
OLD_CHAR_KEY_CONTAINER = "26eb0019-b012-49a8-b1f8-394fb2032b0f"   # Button presses → PC
OLD_CHAR_NAME_OF_APP   = "26eb001d-b012-49a8-b1f8-394fb2032b0f"   # Read: app name

# Standard GATT characteristics used by old watches
STD_CHAR_CURRENT_TIME = "00002a2b-0000-1000-8000-00805f9b34fb"   # Write time
STD_CHAR_LOCAL_TIME   = "00002a0f-0000-1000-8000-00805f9b34fb"   # Write tz offset
STD_CHAR_ALERT_LEVEL  = "00002a06-0000-1000-8000-00805f9b34fb"   # Link Loss alert level
STD_CHAR_TX_POWER     = "00002a07-0000-1000-8000-00805f9b34fb"
STD_CHAR_FIRMWARE_REV = "00002a26-0000-1000-8000-00805f9b34fb"
STD_CCC_DESCRIPTOR    = "00002902-0000-1000-8000-00805f9b34fb"

OLD_NOTIFY_CHAR_UUIDS = [OLD_CHAR_A_NOT_W_REQ, OLD_CHAR_A_NOT_COM_SET]

# ---------------------------------------------------------------------------
# Scan helpers
# ---------------------------------------------------------------------------

ALL_CASIO_ADV_UUIDS = {
    NEW_ADV_UUID,
    NEW_SERVICE_UUID,
    *OLD_ADV_UUIDS,
}

# Any service UUID starting with this prefix is Casio-proprietary
CASIO_UUID_PREFIX = "26eb"

# ---------------------------------------------------------------------------
# Human-readable labels for all known Casio service / char UUIDs
# ---------------------------------------------------------------------------

UUID_LABELS: Dict[str, str] = {
    NEW_SERVICE_UUID:          "NEW:WatchFeatures(26eb000d)",
    CHAR_READ_REQUEST:         "NEW:ReadRequest(26eb002c/0x0C)",
    CHAR_ALL_FEATURES:         "NEW:AllFeatures(26eb002d/0x0E)",
    CHAR_NOTIFY:               "NEW:Notify(26eb0030/0x0D)",
    CHAR_DATA_SP:              "NEW:DataSP(26eb0023/0x11)",
    CHAR_CONVOY:               "NEW:Convoy(26eb0024/0x14)",
    OLD_SVC_VIRTUAL_SERVER:    "OLD:VirtualServer(26eb0007)",
    OLD_SVC_CURRENT_TIME:      "OLD:CurrentTimeSvc(26eb0002)",
    OLD_SVC_ALERT_NOTIF:       "OLD:AlertNotif(26eb0000)",
    OLD_SVC_PHONE_ALERT:       "OLD:PhoneAlert(26eb0001)",
    OLD_SVC_IMMEDIATE_ALERT:   "OLD:ImmediateAlert(26eb0005)",
    OLD_SVC_KEY_COMMANDER:     "OLD:KeyCommander(26eb0018)",
    OLD_SVC_MORE_ALERT:        "OLD:MoreAlert(26eb001a)",
    OLD_CHAR_VS_FEATURE:       "OLD:VSFeature(26eb0008)",
    OLD_CHAR_A_NOT_W_REQ:      "OLD:TimeRequest(26eb0009)",
    OLD_CHAR_A_NOT_COM_SET:    "OLD:InitDone(26eb000a)",
    OLD_CHAR_KEY_CONTAINER:    "OLD:KeyContainer(26eb0019)",
    OLD_CHAR_NAME_OF_APP:      "OLD:NameOfApp(26eb001d)",
    STD_CHAR_CURRENT_TIME:     "STD:CurrentTime(00002a2b)",
    STD_CHAR_LOCAL_TIME:       "STD:LocalTime(00002a0f)",
    STD_CHAR_ALERT_LEVEL:      "STD:AlertLevel(00002a06)",
    STD_CHAR_TX_POWER:         "STD:TxPower(00002a07)",
    STD_CHAR_FIRMWARE_REV:     "STD:FirmwareRev(00002a26)",
    NEW_ADV_UUID:              "STD:TxPowerSvc(00001804)",
    "00001802-0000-1000-8000-00805f9b34fb": "STD:ImmediateAlertSvc(00001802)",
    "00001803-0000-1000-8000-00805f9b34fb": "STD:LinkLossSvc(00001803)",
    "00001805-0000-1000-8000-00805f9b34fb": "STD:CurrentTimeSvc(00001805)",
    "0000180a-0000-1000-8000-00805f9b34fb": "STD:DeviceInfo(0000180a)",
    "0000180e-0000-1000-8000-00805f9b34fb": "STD:PhoneAlertSvc(0000180e)",
    "00001811-0000-1000-8000-00805f9b34fb": "STD:AlertNotifSvc(00001811)",
}

# ---------------------------------------------------------------------------
# Feature code name tables  (new watch protocol)
# ---------------------------------------------------------------------------

FEATURE_NAMES: Dict[int, str] = {
    0x09: "CASIO_CURRENT_TIME",
    0x0A: "ALERT_LEVEL / FIND_PHONE",
    0x10: "CASIO_BLE_FEATURES",
    0x11: "CASIO_SETTING_FOR_BLE",
    0x13: "CASIO_SETTING_FOR_BASIC",
    0x15: "CASIO_SETTING_FOR_ALM",
    0x16: "CASIO_SETTING_FOR_ALM2",
    0x18: "CASIO_TIMER",
    0x1D: "CASIO_DST_WATCH_STATE",
    0x1E: "CASIO_DST_SETTING",
    0x1F: "CASIO_WORLD_CITIES",
    0x20: "CASIO_VERSION_INFORMATION",
    0x22: "CASIO_APP_INFORMATION",
    0x23: "CASIO_WATCH_NAME",
    0x26: "CASIO_MODULE_ID",
    0x28: "CASIO_WATCH_CONDITION",
    0x30: "CASIO_REMINDER_TITLE",
    0x31: "CASIO_REMINDER_TIME",
    0x39: "CASIO_CURRENT_TIME_MANAGER",
    0x3A: "CASIO_CONN_PARAM_MGR",
    0x3B: "CASIO_ADV_PARAM_MGR",
    0x43: "CASIO_TARGET_VALUE",
    0x45: "CASIO_USER_PROFILE",
    0x47: "CASIO_SERVICE_DISC_MGR",
    0xFF: "ERROR",
}

BUTTON_NAMES: Dict[int, str] = {
    0x00: "LOWER_LEFT (reset)",
    0x01: "LOWER_LEFT",
    0x02: "FIND_PHONE",
    0x03: "NO_BUTTON (auto sync)",
    0x04: "LOWER_RIGHT (time-set)",
}

# Old-watch notification service IDs (data[0] in CASIO_A_NOT_W_REQ notify)
OLD_SVC_ID_NAMES: Dict[int, str] = {
    0x00: "INIT",
    0x02: "TIME_REQUEST",
    0x07: "VIRTUAL_SERVER_FEATURE",
}

OLD_TIME_REQ_NAMES: Dict[int, str] = {
    0x01: "WRITE_CURRENT_TIME",
    0x02: "WRITE_LOCAL_TIME_INFO",
}
