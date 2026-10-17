import argparse
import ctypes
import ctypes.wintypes as w
import json
import queue
import sys
import threading
from pathlib import Path

import frida

from .profiles import PROFILES, ZONES, child_needs_timezone, detect_executable


def process_command_line(pid):
    """Read only the command line of a child already gated by our session."""

    class UnicodeString(ctypes.Structure):
        _fields_ = [("length", w.USHORT), ("maximumLength", w.USHORT), ("buffer", ctypes.c_void_p)]

    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    query = ctypes.windll.ntdll.NtQueryInformationProcess
    query.argtypes = [w.HANDLE, w.ULONG, ctypes.c_void_p, w.ULONG, ctypes.POINTER(w.ULONG)]
    query.restype = w.LONG
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return ""
    try:
        needed = w.ULONG()
        query(handle, 60, None, 0, ctypes.byref(needed))
        if needed.value < ctypes.sizeof(UnicodeString) or needed.value > 1024 * 1024:
            return ""
        data = ctypes.create_string_buffer(needed.value)
        if query(handle, 60, data, needed, ctypes.byref(needed)) != 0:
            return ""
        text = UnicodeString.from_buffer(data)
        return ctypes.wstring_at(text.buffer, text.length // 2)
    finally:
        kernel.CloseHandle(handle)


def open_process_watch(pid):
    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    return kernel.OpenProcess(0x100000, False, pid)


def watched_process_is_running(handle):
    kernel = ctypes.windll.kernel32
    kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    return bool(handle) and kernel.WaitForSingleObject(handle, 0) == 258


def close_process_watch(handle):
    kernel = ctypes.windll.kernel32
    kernel.CloseHandle.argtypes = [w.HANDLE]
    if handle:
        kernel.CloseHandle(handle)


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


def zone_config(iana):
    if iana not in ZONES:
        raise ValueError("Unsupported time zone: " + iana)
    enum = ctypes.windll.advapi32.EnumDynamicTimeZoneInformation
    enum.argtypes = [w.DWORD, ctypes.POINTER(DynamicTimeZone)]
    enum.restype = w.DWORD
    value = DynamicTimeZone()
    for index in range(512):
        status = enum(index, ctypes.byref(value))
        if status == 259:
            break
        if status != 0:
            raise OSError(status, "EnumDynamicTimeZoneInformation")
        if value.keyName == ZONES[iana]:
            return {"iana": iana, "windows": ZONES[iana], "dynamic": list(bytes(value))}
    raise ValueError("Windows time zone not found: " + ZONES[iana])


class Controller:
    def __init__(self, config, report=None, profile="feishu"):
        if profile not in PROFILES:
            raise ValueError("Unknown application profile: " + profile)
        self.profile = profile
        self.device = frida.get_local_device()
        source = Path(__file__).with_name("agent.js").read_text(encoding="utf-8")
        self.source = source.replace("__CONFIG__", json.dumps(config))
        self.sessions = {}
        self.root_pid = None
        self.report = report or (lambda value: print(json.dumps(value), flush=True))
        self.children = queue.Queue()
        self.stop_event = threading.Event()
        self.closed = False
        self.device.on("child-added", self.child_added)
        self.worker = threading.Thread(target=self.process_children, daemon=True)
        self.worker.start()

    def child_added(self, child):
        # Multiple controllers share the local device. Never resume or
        # instrument a child owned by another controller/session.
        if child.parent_pid not in self.sessions:
            return
        # GPU, utility, updater, security, and backend processes are deliberately
        # excluded. They do not need a display time zone.
        if (
            not self.stop_event.is_set()
            and child.path
            and Path(child.path).name.lower() in PROFILES[self.profile]["executables"]
        ):
            self.children.put(child)
        else:
            try:
                self.device.resume(child.pid)
            except Exception:
                pass

    def process_children(self):
        while not self.stop_event.is_set():
            try:
                child = self.children.get(timeout=0.2)
            except queue.Empty:
                continue
            watch = None
            failure = None
            try:
                # Windows child events do not always contain argv. Query only
                # this owned, suspended child and never expose its arguments.
                command_line = process_command_line(child.pid) or " ".join(child.argv or [])
                if child_needs_timezone(self.profile, child.path, command_line):
                    watch = open_process_watch(child.pid)
                    self.attach(child.pid, gate_children=False)
            except Exception as error:
                failure = str(error)
            finally:
                try:
                    self.device.resume(child.pid)
                except Exception:
                    pass
                if failure and watch:
                    # A failed provisional renderer can exit only after resume.
                    # Keep its handle, not just its reusable PID, and assess it
                    # once startup has settled. Persistent failures stay visible.
                    timer = threading.Timer(
                        2, self.finish_failed_child, args=(watch, child.pid, failure)
                    )
                    timer.daemon = True
                    timer.start()
                else:
                    close_process_watch(watch)

    def finish_failed_child(self, watch, pid, error):
        try:
            if not self.stop_event.is_set() and watched_process_is_running(watch):
                self.report({"event": "child_error", "pid": pid, "error": error})
        finally:
            close_process_watch(watch)

    def attach(self, pid, gate_children=True):
        session = self.device.attach(pid)
        script = None
        try:
            if gate_children:
                session.enable_child_gating()
            script = session.create_script(self.source)
            script.on("message", self.message)
            script.load()
            self.sessions[pid] = (session, script)
            result = script.exports_sync.probe()
            self.report({"event": "probe", **result})
            return result
        except Exception:
            self.sessions.pop(pid, None)
            if script:
                try:
                    script.unload()
                except Exception:
                    pass
            session.detach()
            raise

    def message(self, message, data):
        if message["type"] == "send":
            self.report(message["payload"])
        else:
            self.report({"event": "agent_error", "error": message.get("description", "unknown")})

    def launch(self, executable):
        if Path(executable).name.lower() not in PROFILES[self.profile]["executables"]:
            raise ValueError("Executable does not match application profile: " + self.profile)
        pid = self.device.spawn([executable])
        self.root_pid = pid
        try:
            self.attach(pid, gate_children=PROFILES[self.profile]["gate_children"])
        finally:
            self.device.resume(pid)
        return pid

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.stop_event.set()
        self.device.off("child-added", self.child_added)
        self.worker.join(timeout=3)
        for session, script in list(self.sessions.values()):
            for action in (session.disable_child_gating, script.unload, session.detach):
                try:
                    action()
                except Exception:
                    pass
        while True:
            try:
                child = self.children.get_nowait()
                self.device.resume(child.pid)
            except queue.Empty:
                break
            except Exception:
                continue


def main():
    if sys.platform != "win32":
        raise SystemExit("Desktop Timezone requires Windows.")
    parser = argparse.ArgumentParser()
    parser.add_argument("--zone", default="Asia/Shanghai", choices=ZONES)
    parser.add_argument("--app", default="feishu", choices=PROFILES)
    parser.add_argument("--attach", type=int)
    parser.add_argument("--exe", help="Override the selected application executable path")
    parser.add_argument("--seconds", type=int, default=30)
    args = parser.parse_args()
    controller = Controller(zone_config(args.zone), profile=args.app)
    try:
        if args.attach:
            controller.attach(args.attach)
        else:
            controller.launch(args.exe or str(detect_executable(args.app)))
        print(json.dumps({"event": "running", "seconds": args.seconds}), flush=True)
        controller.stop_event.wait(args.seconds)
    finally:
        controller.close()
        print(json.dumps({"event": "detached"}), flush=True)


if __name__ == "__main__":
    main()
