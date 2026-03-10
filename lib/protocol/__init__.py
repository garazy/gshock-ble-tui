"""
lib.protocol — G-Shock BLE protocol layer.

Re-exports the complete public API so callers can simply write:

    from lib.protocol import BLEEvent, decode_event, build_time_command_new, ...
"""

from lib.protocol.constants import (
    NEW_ADV_UUID, NEW_SERVICE_UUID,
    CHAR_READ_REQUEST, CHAR_ALL_FEATURES, CHAR_NOTIFY, CHAR_DATA_SP, CHAR_CONVOY,
    NEW_NOTIFY_CHAR_UUIDS,
    OLD_ADV_UUIDS,
    OLD_SVC_ALERT_NOTIF, OLD_SVC_PHONE_ALERT, OLD_SVC_CURRENT_TIME,
    OLD_SVC_IMMEDIATE_ALERT, OLD_SVC_VIRTUAL_SERVER,
    OLD_SVC_KEY_COMMANDER, OLD_SVC_MORE_ALERT,
    OLD_CHAR_VS_FEATURE, OLD_CHAR_A_NOT_W_REQ, OLD_CHAR_A_NOT_COM_SET,
    OLD_CHAR_SETTING_BLE, OLD_CHAR_KEY_CONTAINER, OLD_CHAR_NAME_OF_APP,
    OLD_CHAR_NEW_ALERT, OLD_CHAR_ALERT_NOTIF_CP,
    OLD_CHAR_MORE_ALERT, OLD_CHAR_MORE_ALERT_LONG,
    ALERT_CATEGORIES,
    STD_CHAR_CURRENT_TIME, STD_CHAR_LOCAL_TIME, STD_CHAR_ALERT_LEVEL,
    STD_CHAR_TX_POWER, STD_CHAR_FIRMWARE_REV, STD_CCC_DESCRIPTOR,
    OLD_NOTIFY_CHAR_UUIDS,
    ALL_CASIO_ADV_UUIDS, CASIO_UUID_PREFIX,
    UUID_LABELS, FEATURE_NAMES, BUTTON_NAMES,
    OLD_SVC_ID_NAMES, OLD_TIME_REQ_NAMES,
)
from lib.protocol.events import (
    BLEEvent,
    label_for_uuid,
    make_sys_event,
    make_scan_event,
)
from lib.protocol.encoders import (
    get_ntp_time,
    encode_time_new,
    encode_time_old,
    encode_local_time,
    build_time_command_new,
    encode_new_alert,
)
from lib.protocol.decoders import decode_event

__all__ = [
    # constants
    "NEW_ADV_UUID", "NEW_SERVICE_UUID",
    "CHAR_READ_REQUEST", "CHAR_ALL_FEATURES", "CHAR_NOTIFY",
    "CHAR_DATA_SP", "CHAR_CONVOY",
    "NEW_NOTIFY_CHAR_UUIDS",
    "OLD_ADV_UUIDS",
    "OLD_SVC_ALERT_NOTIF", "OLD_SVC_PHONE_ALERT", "OLD_SVC_CURRENT_TIME",
    "OLD_SVC_IMMEDIATE_ALERT", "OLD_SVC_VIRTUAL_SERVER",
    "OLD_SVC_KEY_COMMANDER", "OLD_SVC_MORE_ALERT",
    "OLD_CHAR_VS_FEATURE", "OLD_CHAR_A_NOT_W_REQ", "OLD_CHAR_A_NOT_COM_SET",
    "OLD_CHAR_SETTING_BLE", "OLD_CHAR_KEY_CONTAINER", "OLD_CHAR_NAME_OF_APP",
    "OLD_CHAR_NEW_ALERT", "OLD_CHAR_ALERT_NOTIF_CP",
    "OLD_CHAR_MORE_ALERT", "OLD_CHAR_MORE_ALERT_LONG",
    "ALERT_CATEGORIES",
    "STD_CHAR_CURRENT_TIME", "STD_CHAR_LOCAL_TIME", "STD_CHAR_ALERT_LEVEL",
    "STD_CHAR_TX_POWER", "STD_CHAR_FIRMWARE_REV", "STD_CCC_DESCRIPTOR",
    "OLD_NOTIFY_CHAR_UUIDS",
    "ALL_CASIO_ADV_UUIDS", "CASIO_UUID_PREFIX",
    "UUID_LABELS", "FEATURE_NAMES", "BUTTON_NAMES",
    "OLD_SVC_ID_NAMES", "OLD_TIME_REQ_NAMES",
    # events
    "BLEEvent", "label_for_uuid", "make_sys_event", "make_scan_event",
    # encoders
    "get_ntp_time", "encode_time_new", "encode_time_old",
    "encode_local_time", "build_time_command_new", "encode_new_alert",
    # decoders
    "decode_event",
]
