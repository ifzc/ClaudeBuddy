import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from desktop_timezone.taskbar_clock import TaskbarClock, TaskbarLocator


class TaskbarRecoveryTests(unittest.TestCase):
    def locator(self):
        locator = TaskbarLocator.__new__(TaskbarLocator)
        locator.window = 1
        locator.element = None
        locator.user = Mock()
        locator.user.FindWindowW.return_value = 1
        locator.user.IsWindowVisible.return_value = True

        def bounds(window, rectangle):
            rectangle._obj.left = 0
            rectangle._obj.top = 1048
            rectangle._obj.right = 1920
            rectangle._obj.bottom = 1080
            return True

        locator.user.GetWindowRect.side_effect = bounds
        return locator

    def test_compact_clock_uses_the_button_containing_time_text(self):
        locator = self.locator()
        locator.automation = Mock()
        locator.conditions = ["old-id", "old-class"]
        locator.time_text_condition = "time-text"
        root = locator.automation.ElementFromHandle.return_value
        root.FindFirst.side_effect = [None, None, object()]
        button = SimpleNamespace(
            CurrentControlType=50000,
            CurrentAutomationId="SystemTrayIcon",
            CurrentClassName="SystemTray.AccentButton",
        )
        locator.automation.RawViewWalker.GetParentElement.return_value = button
        self.assertIs(locator._find_clock(1), button)

    def test_offscreen_cached_element_is_replaced_without_taskbar_handle_change(self):
        locator = self.locator()
        locator.element = SimpleNamespace(
            CurrentIsOffscreen=True,
            CurrentBoundingRectangle=SimpleNamespace(left=0, top=0, right=0, bottom=0),
        )
        locator._find_clock = Mock(
            return_value=SimpleNamespace(
                CurrentIsOffscreen=False,
                CurrentBoundingRectangle=SimpleNamespace(
                    left=1854, top=1048, right=1890, bottom=1080
                ),
            )
        )
        self.assertEqual(locator.locate(), (1854, 1048, 1890, 1080))
        locator._find_clock.assert_called_once_with(1)

    def test_missing_clock_waits_and_recovers_instead_of_stopping(self):
        events = []
        clock = TaskbarClock("UTC", events.append)
        clock.user = Mock()
        clock.clock = SimpleNamespace(zone="UTC", now=lambda: datetime(2026, 10, 26, 12))
        clock.locator = SimpleNamespace(window=1, locate=Mock(return_value=None))
        clock.missing_since = 0
        with patch("desktop_timezone.taskbar_clock.time.monotonic", return_value=20):
            clock._tick()
            clock._tick()
        self.assertEqual(events, [{"event": "waiting"}])
        self.assertFalse(clock.stopping.is_set())
        clock.locator.locate.return_value = (1854, 1048, 1890, 1080)
        clock.user.GetWindowRect.return_value = False
        clock._tick()
        self.assertEqual(events[-1], {"event": "ready"})
        self.assertTrue(clock.visible)
        self.assertEqual(clock.rectangle, (1854, 1050, 1890, 1078))


if __name__ == "__main__":
    unittest.main()
