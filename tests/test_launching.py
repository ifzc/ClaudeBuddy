import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from desktop_timezone.launching import ApplicationLauncher


class ApplicationLaunchTests(unittest.TestCase):
    def setUp(self):
        self.launcher = ApplicationLauncher("feishu", lambda event: None)

    @patch("desktop_timezone.launching.subprocess.Popen")
    @patch("desktop_timezone.launching.watched_process_is_running", return_value=True)
    @patch("desktop_timezone.launching.Controller")
    def test_repeated_start_keeps_the_active_controller(self, factory, running, popen):
        controller = Mock()
        self.launcher.controller = controller
        self.launcher.process_handle = 12
        self.launcher.zone = "Asia/Shanghai"
        for _ in range(2):
            self.assertEqual(self.launcher.start("Feishu.exe", "UTC"), "opened")
        self.assertEqual(popen.call_count, 2)
        factory.assert_not_called()
        controller.close.assert_not_called()
        self.assertEqual(self.launcher.zone, "Asia/Shanghai")

    @patch("desktop_timezone.launching.open_process_watch", return_value=22)
    @patch("desktop_timezone.launching.zone_config", return_value={})
    @patch("desktop_timezone.launching.frida.get_local_device")
    @patch("desktop_timezone.launching.close_process_watch")
    @patch("desktop_timezone.launching.watched_process_is_running", return_value=False)
    @patch("desktop_timezone.launching.Controller")
    def test_exited_process_releases_the_old_session_and_launches_again(
        self, factory, running, close_watch, device, config, open_watch
    ):
        old_controller = Mock()
        new_controller = factory.return_value
        new_controller.root_pid = 456
        self.launcher.controller = old_controller
        self.launcher.process_handle = 12
        device.return_value.enumerate_processes.return_value = []
        self.assertEqual(self.launcher.start("Feishu.exe", "Asia/Shanghai"), "started")
        old_controller.close.assert_called_once()
        close_watch.assert_called_once_with(12)
        new_controller.launch.assert_called_once_with("Feishu.exe")
        self.assertIs(self.launcher.controller, new_controller)
        self.assertEqual(self.launcher.process_handle, 22)

    @patch("desktop_timezone.launching.subprocess.Popen")
    @patch("desktop_timezone.launching.open_process_watch", return_value=22)
    @patch("desktop_timezone.launching.process_command_line")
    @patch("desktop_timezone.launching.frida.get_local_device")
    @patch("desktop_timezone.launching.close_process_watch")
    @patch("desktop_timezone.launching.watched_process_is_running")
    @patch("desktop_timezone.launching.Controller")
    def test_existing_session_is_opened_without_restarting_or_reinjecting(
        self, factory, running, close_watch, device, command, open_watch, popen
    ):
        running.side_effect = [False, True]
        device.return_value.enumerate_processes.return_value = [
            SimpleNamespace(pid=1, name="Feishu.exe"),
            SimpleNamespace(pid=2, name="Feishu.exe"),
        ]
        command.side_effect = ["Feishu.exe --type=renderer", "Feishu.exe"]
        self.assertEqual(self.launcher.start("Feishu.exe", "Asia/Shanghai"), "existing")
        open_watch.assert_called_once_with(2)
        popen.assert_called_once()
        factory.assert_not_called()
        self.assertIsNone(self.launcher.controller)

    @patch("desktop_timezone.launching.open_process_watch", return_value=None)
    @patch("desktop_timezone.launching.zone_config", return_value={})
    @patch("desktop_timezone.launching.frida.get_local_device")
    @patch("desktop_timezone.launching.close_process_watch")
    @patch("desktop_timezone.launching.watched_process_is_running", return_value=False)
    @patch("desktop_timezone.launching.Controller")
    def test_failed_launch_leaves_the_next_attempt_available(
        self, factory, running, close_watch, device, config, open_watch
    ):
        device.return_value.enumerate_processes.return_value = []
        with self.assertRaisesRegex(RuntimeError, "再次点击"):
            self.launcher.start("Feishu.exe", "Asia/Shanghai")
        factory.return_value.close.assert_called_once()
        self.assertIsNone(self.launcher.controller)
        self.assertIsNone(self.launcher.process_handle)


if __name__ == "__main__":
    unittest.main()
