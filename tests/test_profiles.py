import queue
import threading
import unittest
from types import SimpleNamespace

from desktop_timezone.native_timezone import Controller
from desktop_timezone.profiles import child_needs_timezone


class ApplicationIsolationTests(unittest.TestCase):
    def test_only_feishu_renderers_are_selected(self):
        self.assertTrue(
            child_needs_timezone("feishu", r"C:\Apps\Feishu.exe", "Feishu.exe --type=renderer")
        )
        for profile, name, args in [
            ("feishu", "Feishu.exe", "--type=gpu-process"),
            ("feishu", "Feishu.exe", "--type=utility"),
            ("feishu", "WeChatAppEx.exe", "--type=renderer"),
            ("weixin", "Weixin.exe", "--type=wxocr"),
            ("weixin", "Weixin.exe", "--type=wxplayer"),
            ("weixin", "WeChatAppEx.exe", "--type=renderer"),
        ]:
            with self.subTest(profile=profile, name=name, args=args):
                self.assertFalse(child_needs_timezone(profile, name, args))

    def test_other_controller_children_are_not_resumed(self):
        resumed = []
        controller = Controller.__new__(Controller)
        controller.profile = "feishu"
        controller.sessions = {100: object()}
        controller.stop_event = threading.Event()
        controller.children = queue.Queue()
        controller.device = SimpleNamespace(resume=resumed.append)
        controller.child_added(SimpleNamespace(parent_pid=200, pid=201, path="Feishu.exe"))
        self.assertEqual(resumed, [])
        self.assertTrue(controller.children.empty())
        controller.child_added(SimpleNamespace(parent_pid=100, pid=101, path="Feishu.exe"))
        self.assertEqual(controller.children.get_nowait().pid, 101)
        controller.child_added(SimpleNamespace(parent_pid=100, pid=102, path="Other.exe"))
        self.assertEqual(resumed, [102])


if __name__ == "__main__":
    unittest.main()
