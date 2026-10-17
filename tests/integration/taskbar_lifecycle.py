"""Opt-in desktop test: draws over the real clock briefly; never restarts Explorer."""

import ctypes
import json
import os
import tempfile
import time
import tkinter as tk
from ctypes import wintypes as w
from pathlib import Path

from desktop_timezone.app import App
from desktop_timezone.native_timezone import DynamicTimeZone


def wait_for(root, predicate):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        root.update()
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("Timed out waiting for taskbar clock")


def system_zone():
    rules = DynamicTimeZone()
    ctypes.windll.kernel32.GetDynamicTimeZoneInformation(ctypes.byref(rules))
    return bytes(rules)


def main():
    original_directory = Path.cwd()
    before = system_zone()
    window = None
    controller = None
    with tempfile.TemporaryDirectory() as directory:
        try:
            os.chdir(directory)
            window = tk.Tk()
            app = App(window)
            panel = app.panels["taskbar"]
            panel.start()
            controller = panel.controller
            wait_for(
                window,
                lambda: (
                    controller.ready
                    or controller.thread is None
                    or not controller.thread.is_alive()
                ),
            )
            assert controller.ready, panel.status.get()
            assert controller.visible
            rect = controller.rectangle
            user = controller.user
            user.GetWindowLongPtrW.argtypes = [w.HWND, ctypes.c_int]
            user.GetWindowLongPtrW.restype = ctypes.c_ssize_t
            flags = user.GetWindowLongPtrW(controller.window, -20)
            assert flags & 0x080800A0 == 0x080800A0
            user.WindowFromPoint.argtypes = [w.POINT]
            user.WindowFromPoint.restype = w.HWND
            point = w.POINT((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)
            assert user.WindowFromPoint(point) != controller.window
            assert controller.clock.zone == "Asia/Shanghai"

            app.close()
            window.update()
            assert window.state() in ("withdrawn", "iconic")
            assert controller.visible and controller.thread.is_alive()
            app.show()
            panel.zone_label.set("协调世界时（UTC）")
            panel.start()
            wait_for(window, lambda: controller.clock.zone == "UTC")
            panel.stop()
            wait_for(window, lambda: panel.controller is None)
            assert not controller.visible and controller.window is None
            assert system_zone() == before
            app.close()
            window = None
            print(
                json.dumps(
                    {
                        "clockRectangle": rect,
                        "clickThrough": True,
                        "closeKeepsClock": True,
                        "liveZoneChange": True,
                        "stopRemovesOverlay": True,
                        "systemZoneUnchanged": True,
                    }
                )
            )
        finally:
            if controller:
                controller.stop()
                controller.thread.join(5)
            if window:
                app.tray.close()
                window.destroy()
            os.chdir(original_directory)


if __name__ == "__main__":
    main()
