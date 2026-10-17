import ctypes
import ctypes.wintypes as w
import datetime
import json
import sys
import time


class SystemTime(ctypes.Structure):
    _fields_ = [
        (name, w.WORD)
        for name in ("year", "month", "dayOfWeek", "day", "hour", "minute", "second", "millisecond")
    ]


class DynamicTimeZone(ctypes.Structure):
    _fields_ = [
        ("bias", w.LONG),
        ("standardName", w.WCHAR * 32),
        ("standardDate", SystemTime),
        ("standardBias", w.LONG),
        ("daylightName", w.WCHAR * 32),
        ("daylightDate", SystemTime),
        ("daylightBias", w.LONG),
        ("keyName", w.WCHAR * 128),
        ("disabled", ctypes.c_ubyte),
    ]


def sample():
    k = ctypes.windll.kernel32
    zone, local, utc = DynamicTimeZone(), SystemTime(), SystemTime()
    k.GetDynamicTimeZoneInformation(ctypes.byref(zone))
    k.GetLocalTime(ctypes.byref(local))
    k.GetSystemTime(ctypes.byref(utc))

    def parts(value):
        return [value.year, value.month, value.day, value.hour, value.minute, value.second]

    local_dt = datetime.datetime(*parts(local))
    utc_dt = datetime.datetime(*parts(utc))
    conversions = []
    for month in [1, 7]:
        source = SystemTime(2026, month, 0, 15, 12, 0, 0, 0)
        target = SystemTime()
        ok = k.SystemTimeToTzSpecificLocalTimeEx(None, ctypes.byref(source), ctypes.byref(target))
        assert ok
        conversions.append(parts(target))
    return {
        "key": zone.keyName,
        "bias": zone.bias,
        "offsetMinutes": round((local_dt - utc_dt).total_seconds() / 60),
        "epoch": time.time(),
        "utc": parts(utc),
        "conversions": conversions,
        "address": hex(ctypes.cast(k.GetDynamicTimeZoneInformation, ctypes.c_void_p).value),
    }


print(json.dumps(sample()), flush=True)
for line in sys.stdin:
    if line.strip() == "quit":
        break
    print(json.dumps(sample()), flush=True)
