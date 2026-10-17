import sys
import unittest
from datetime import datetime


@unittest.skipUnless(sys.platform == "win32", "Windows explicit-zone conversion")
class TaskbarTimeTests(unittest.TestCase):
    def test_midnight_and_dst_boundaries_without_changing_system_zone(self):
        import ctypes

        from desktop_timezone.native_timezone import DynamicTimeZone
        from desktop_timezone.taskbar_clock import ZoneClock

        def system_zone():
            rules = DynamicTimeZone()
            ctypes.windll.kernel32.GetDynamicTimeZoneInformation(ctypes.byref(rules))
            return bytes(rules)

        before = system_zone()
        examples = [
            ("Asia/Shanghai", "2026-10-17T17:30:00", "2026-10-18T01:30:00"),
            ("America/Phoenix", "2026-10-17T02:00:00", "2026-10-16T19:00:00"),
            ("America/New_York", "2026-03-08T06:59:59", "2026-03-08T01:59:59"),
            ("America/New_York", "2026-03-08T07:00:00", "2026-03-08T03:00:00"),
            ("America/New_York", "2026-11-01T06:00:00", "2026-11-01T01:00:00"),
            ("UTC", "2026-10-17T17:30:00", "2026-10-17T17:30:00"),
        ]
        for zone, utc, expected in examples:
            with self.subTest(zone=zone, utc=utc):
                self.assertEqual(
                    ZoneClock(zone).now(datetime.fromisoformat(utc)),
                    datetime.fromisoformat(expected),
                )
        self.assertEqual(system_zone(), before)
