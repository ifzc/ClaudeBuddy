"""Exercise repeat/exit/relaunch with real instrumented probe processes."""

import json
import os
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from desktop_timezone.app import App
from desktop_timezone.native_timezone import Controller


def wait_for(window, predicate):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        window.update()
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("Application lifecycle did not settle")


def main():
    probes = []

    class ProbeController(Controller):
        def launch(self, executable):
            process = subprocess.Popen(
                [sys._base_executable, "-u", str(Path(__file__).with_name("clock_probe.py"))],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
            )
            probes.append(process)
            json.loads(process.stdout.readline())
            self.root_pid = process.pid
            self.attach(process.pid, gate_children=False)
            return process.pid

    original = Path.cwd()
    window = app = None
    opened = Mock()
    with tempfile.TemporaryDirectory() as directory:
        try:
            os.chdir(directory)
            window = tk.Tk()
            app = App(window)
            panel = app.panels["feishu"]
            panel.exe = Path(directory) / "Feishu.exe"
            panel.exe.touch()
            # Stub only process discovery/opening. Probe injection, handles,
            # process exits and the Tk event loop remain real.
            with (
                patch("desktop_timezone.launching.Controller", ProbeController),
                patch(
                    "desktop_timezone.launching.frida",
                    SimpleNamespace(
                        get_local_device=lambda: SimpleNamespace(enumerate_processes=lambda: [])
                    ),
                ),
                patch.object(panel.launcher, "_open_window", opened),
            ):
                for attempt in range(2):
                    panel.start_button.invoke()
                    wait_for(window, lambda: not panel.busy)
                    assert panel.controller is not None, panel.status.get()
                    assert "disabled" not in panel.start_button.state()
                    probes[-1].stdin.write("sample\n")
                    probes[-1].stdin.flush()
                    assert json.loads(probes[-1].stdout.readline())["key"] == "China Standard Time"
                    panel.start_button.invoke()
                    wait_for(window, lambda: not panel.busy)
                    assert len(probes) == attempt + 1, "Repeat click spawned a duplicate session"
                    probes[-1].stdin.write("quit\n")
                    probes[-1].stdin.flush()
                    probes[-1].wait(timeout=5)
                    wait_for(window, lambda: panel.controller is None and not panel.busy)
                    assert "已退出" in panel.status.get()
                assert opened.call_count == 2
            app.close()
            window = None
            print(json.dumps({"repeatStart": True, "exitDetected": True, "relaunch": True}))
        finally:
            for process in probes:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
            if app:
                app.panels["feishu"].launcher.release()
                app.tray.close()
            if window:
                window.destroy()
            os.chdir(original)


if __name__ == "__main__":
    main()
