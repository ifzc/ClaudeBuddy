"""Check window-close behavior against an actual instrumented test process."""

import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

from desktop_timezone.app import App
from desktop_timezone.native_timezone import (
    Controller,
    close_process_watch,
    open_process_watch,
    zone_config,
)


def main():
    process = subprocess.Popen(
        [sys._base_executable, "-u", str(Path(__file__).with_name("clock_probe.py"))],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    json.loads(process.stdout.readline())
    controller = Controller(zone_config("Asia/Shanghai"), report=lambda event: None)
    window = None
    app = None
    watch = open_process_watch(process.pid)
    original_directory = Path.cwd()
    with tempfile.TemporaryDirectory() as directory:
        try:
            os.chdir(directory)
            window = tk.Tk()
            app = App(window)
            window.update()
            controller.attach(process.pid, gate_children=False)
            app.panels["weixin"].controller = controller
            app.panels["weixin"].process_handle = watch

            # No confirmation or application restart may happen on window close.
            with patch("desktop_timezone.app.messagebox.askyesno", side_effect=AssertionError):
                app.close()
            window.update()
            assert window.state() in ("withdrawn", "iconic"), window.state()
            assert process.poll() is None
            process.stdin.write("sample\n")
            process.stdin.flush()
            assert json.loads(process.stdout.readline())["key"] == "China Standard Time"

            tray_available = app.tray.visible
            if tray_available:
                # Deliver the same notification that a left click emits and
                # verify that the Tk event loop restores the settings window.
                post = ctypes.windll.user32.PostMessageW
                post.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
                assert post(app.tray.window, app.tray.MESSAGE, 0, 0x202)
                deadline = time.monotonic() + 3
                while window.state() != "normal" and time.monotonic() < deadline:
                    window.update()
                    time.sleep(0.02)
            else:
                app.show()  # Headless CI may not provide the Windows taskbar.
            window.update()
            assert window.state() == "normal"
            process.stdin.write("sample\n")
            process.stdin.flush()
            assert json.loads(process.stdout.readline())["key"] == "China Standard Time"

            controller.close()
            app.panels["weixin"].controller = None
            app.panels["weixin"].process_handle = None
            app.close()
            window = None
            assert not app.tray.visible
            print(
                json.dumps(
                    {
                        "windowCloseKeepsTimezone": True,
                        "reopenKeepsTimezone": True,
                        "trayAvailable": tray_available,
                    }
                )
            )
        finally:
            controller.close()
            if app is not None:
                app.tray.close()
            if window is not None:
                window.destroy()
            close_process_watch(watch)
            os.chdir(original_directory)
            process.stdin.write("quit\n")
            process.stdin.flush()
            process.wait(timeout=5)


if __name__ == "__main__":
    main()
