"""
Time encoders and NTP helper.

Provides get_ntp_time() and the byte-level encode functions for both the
new (GW-B5600 etc.) and old (GB-5600, GB-6900) watch protocols.
"""

import datetime
import logging
import time as _time
from typing import Optional

try:
    import ntplib as _ntplib
    _NTPLIB_AVAILABLE = True
except ImportError:
    _NTPLIB_AVAILABLE = False

_NTP_HOST = "pool.ntp.org"
logger = logging.getLogger(__name__)


def get_ntp_time() -> datetime.datetime:
    """Return current local time sourced from NTP (pool.ntp.org).

    Falls back to the local system clock if ntplib is not installed or the
    NTP request fails (no network, firewall, etc.).  Always returns a naive
    datetime in local time.
    """
    if _NTPLIB_AVAILABLE:
        try:
            c = _ntplib.NTPClient()
            resp = c.request(_NTP_HOST, version=3)
            utc_dt = datetime.datetime.fromtimestamp(resp.tx_time,
                                                     tz=datetime.timezone.utc)
            local_dt = utc_dt.astimezone().replace(tzinfo=None)
            logger.debug("NTP time: %s (offset %.3f s)", local_dt, resp.offset)
            return local_dt
        except Exception as exc:
            logger.warning("NTP request failed (%s) — using local clock", exc)
    return datetime.datetime.now()


def encode_time_new(dt: Optional[datetime.datetime] = None) -> bytes:
    """
    10-byte time payload for NEW watches (GW-B5600 etc.).
    Full command: [0x09] + this  →  CHAR_ALL_FEATURES (0x0E)

    Layout: yr_lo yr_hi mon day hr min sec weekday(0=Mon) 0x00 0x01
    """
    if dt is None:
        dt = get_ntp_time()
    yr = dt.year
    return bytes([
        yr & 0xFF, (yr >> 8) & 0xFF,
        dt.month, dt.day,
        dt.hour, dt.minute, dt.second,
        dt.weekday(),   # 0=Monday (utime convention)
        0x00,
        0x01,           # ADJUST_REASON_MANUAL_TIME_UPDATE
    ])


def build_time_command_new() -> bytes:
    """Full 11-byte time-set command for new watches."""
    return bytes([0x09]) + encode_time_new()


def encode_time_old(dt: Optional[datetime.datetime] = None) -> bytes:
    """
    10-byte payload for OLD watches (GB-5600, GB-6900).
    Write to STD_CHAR_CURRENT_TIME (00002a2b).

    Layout: yr_lo yr_hi mon day hr min sec weekday(1=Mon,7=Sun) fractions adjust_reason
    Note: weekday mapping differs from new: 1=Monday … 7=Sunday
    """
    if dt is None:
        dt = get_ntp_time()
    yr = dt.year
    weekday = dt.weekday() + 1   # Python 0=Mon → 1=Mon, 6=Sun → 7=Sun
    return bytes([
        yr & 0xFF, (yr >> 8) & 0xFF,
        dt.month, dt.day,
        dt.hour, dt.minute, dt.second,
        weekday,
        0x00,           # fractions (ms/256) — 0 is fine
        0x01,           # ADJUST_REASON_MANUAL_TIME_UPDATE
    ])


def encode_local_time() -> bytes:
    """
    2-byte LOCAL_TIME_INFORMATION payload for old watches (00002a0f).

    Byte 0: standard timezone offset in 15-minute units (signed, WITHOUT DST)
    Byte 1: DST offset in 15-minute units (signed)

    Per GATT spec the watch sums byte0 + byte1 to get current UTC offset, so
    byte0 must be the *standard* (non-DST) offset only.  Using the total UTC
    offset (which already includes DST) in byte0 would double-count DST and
    place the clock 1 h ahead when DST is active.
    """
    now = datetime.datetime.now().astimezone()
    utc_off = now.utcoffset()
    total_min = int(utc_off.total_seconds() / 60) if utc_off else 0

    try:
        std_off_sec   = _time.timezone                           # seconds WEST of UTC
        dst_off_sec   = _time.altzone if _time.daylight else std_off_sec
        dst_delta_min = int((std_off_sec - dst_off_sec) / 60)   # DST savings in minutes
        dst_15        = dst_delta_min // 15
    except Exception:
        dst_delta_min = 0
        dst_15        = 0

    std_min = total_min - dst_delta_min
    tz_15   = std_min // 15

    return bytes([tz_15 & 0xFF, dst_15 & 0xFF])
