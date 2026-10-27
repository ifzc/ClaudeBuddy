"""Repeatable application launches without restarting an active session."""

import re
import subprocess

import frida

from .native_timezone import (
    Controller,
    close_process_watch,
    open_process_watch,
    process_command_line,
    watched_process_is_running,
    zone_config,
)
from .profiles import PROFILES


class ApplicationLauncher:
    def __init__(self, profile, report):
        self.profile = profile
        self.report = report
        self.controller = None
        self.process_handle = None
        self.zone = None

    def is_running(self):
        return watched_process_is_running(self.process_handle)

    def release(self):
        """Release an exited session; never stop the application."""
        if self.controller:
            self.controller.close()
        self.controller = None
        close_process_watch(self.process_handle)
        self.process_handle = None
        self.zone = None

    def start(self, executable, zone):
        if self.is_running():
            self._open_window(executable)
            return "opened"
        self.release()
        # An application opened outside this tool keeps its existing session.
        # Do not stack hooks onto it or terminate it to change its time zone.
        for process in frida.get_local_device().enumerate_processes():
            if process.name.lower() not in PROFILES[self.profile]["executables"]:
                continue
            command_line = process_command_line(process.pid)
            if not command_line or re.search(r"(?:^|\s)--type(?:=|\s)", command_line):
                continue
            handle = open_process_watch(process.pid)
            if not watched_process_is_running(handle):
                close_process_watch(handle)
                continue
            try:
                self._open_window(executable)
            except Exception:
                close_process_watch(handle)
                raise
            self.process_handle = handle
            return "existing"
        controller = Controller(zone_config(zone), self.report, profile=self.profile)
        try:
            controller.launch(executable)
            handle = open_process_watch(controller.root_pid)
            if not handle:
                raise RuntimeError("应用启动后已退出，请再次点击启动。")
        except Exception:
            controller.close()
            raise
        self.controller = controller
        self.process_handle = handle
        self.zone = zone
        return "started"

    @staticmethod
    def _open_window(executable):
        subprocess.Popen([executable], creationflags=subprocess.CREATE_NO_WINDOW)
