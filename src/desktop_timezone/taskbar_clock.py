"""An independent, click-through clock over the primary Windows taskbar clock."""

import ctypes
import threading
import time
import winreg
from ctypes import wintypes as w
from datetime import datetime

import comtypes

from .native_timezone import DynamicTimeZone, SystemTime, zone_config


class ZoneClock:
    """Convert UTC using an explicit Windows zone, never the system default."""

    def __init__(self, zone):
        self.zone = zone
        self.rules = DynamicTimeZone.from_buffer_copy(bytes(zone_config(zone)["dynamic"]))
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.GetSystemTime.argtypes = [ctypes.POINTER(SystemTime)]
        self.kernel.SystemTimeToTzSpecificLocalTimeEx.argtypes = [
            ctypes.POINTER(DynamicTimeZone),
            ctypes.POINTER(SystemTime),
            ctypes.POINTER(SystemTime),
        ]
        self.kernel.SystemTimeToTzSpecificLocalTimeEx.restype = w.BOOL

    def now(self, utc=None):
        source = SystemTime()
        if utc is None:
            self.kernel.GetSystemTime(ctypes.byref(source))
        else:
            source.year, source.month, source.day = utc.year, utc.month, utc.day
            source.hour, source.minute, source.second = utc.hour, utc.minute, utc.second
        local = SystemTime()
        if not self.kernel.SystemTimeToTzSpecificLocalTimeEx(
            ctypes.byref(self.rules), ctypes.byref(source), ctypes.byref(local)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return datetime(local.year, local.month, local.day, local.hour, local.minute, local.second)


class TaskbarLocator:
    """Read only known clock elements; never infer a position from screen edges."""

    def __init__(self):
        import comtypes.client

        try:
            from comtypes.gen import UIAutomationClient as uia
        except ImportError:
            uia = comtypes.client.GetModule("UIAutomationCore.dll")
        self.automation = comtypes.client.CreateObject(
            uia.CUIAutomation, interface=uia.IUIAutomation
        )
        self.conditions = [
            self.automation.CreatePropertyCondition(30011, "SystemTray.DateTimeIcon"),
            self.automation.CreatePropertyCondition(30012, "SystemTray.DateTimeIcon"),
            self.automation.CreatePropertyCondition(30012, "SystemTray.OmniButton"),
        ]
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.user.FindWindowW.argtypes = [w.LPCWSTR, w.LPCWSTR]
        self.user.FindWindowW.restype = w.HWND
        self.user.IsWindowVisible.argtypes = [w.HWND]
        self.user.IsWindowVisible.restype = w.BOOL
        self.user.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
        self.user.GetWindowRect.restype = w.BOOL
        self.window = None
        self.element = None

    def locate(self):
        window = self.user.FindWindowW("Shell_TrayWnd", None)
        if not window or not self.user.IsWindowVisible(window):
            self.element = None
            return None
        if window != self.window or not self.element:
            self.window, self.element = window, None
            root = self.automation.ElementFromHandle(window)
            for condition in self.conditions:
                candidate = root.FindFirst(4, condition)
                if candidate:
                    self.element = candidate
                    break
        if not self.element:
            return None
        try:
            if self.element.CurrentIsOffscreen:
                return None
            rect = self.element.CurrentBoundingRectangle
            bar = w.RECT()
            if not self.user.GetWindowRect(window, ctypes.byref(bar)):
                return None
            if (
                rect.right - rect.left < 24
                or rect.bottom - rect.top < 20
                or rect.left < bar.left
                or rect.right > bar.right
                or rect.top < bar.top
                or rect.bottom > bar.bottom
            ):
                return None
            return rect.left, rect.top, rect.right, rect.bottom
        except Exception:
            self.element = None
            return None


PROCEDURE = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)


class WindowClass(ctypes.Structure):
    _fields_ = [
        ("style", w.UINT),
        ("procedure", PROCEDURE),
        ("class_extra", ctypes.c_int),
        ("window_extra", ctypes.c_int),
        ("instance", w.HINSTANCE),
        ("icon", w.HICON),
        ("cursor", w.HANDLE),
        ("background", w.HBRUSH),
        ("menu", w.LPCWSTR),
        ("name", w.LPCWSTR),
    ]


class PaintStruct(ctypes.Structure):
    _fields_ = [
        ("dc", w.HDC),
        ("erase", w.BOOL),
        ("rect", w.RECT),
        ("restore", w.BOOL),
        ("update", w.BOOL),
        ("reserved", ctypes.c_byte * 32),
    ]


class TaskbarClock:
    """Own a display window on a dedicated COM/message-loop thread."""

    def __init__(self, zone, report, *, show_date=True):
        self.zone, self.report = zone, report
        self.show_date = show_date
        self.window = None
        self.thread = None
        self.stopping = threading.Event()
        self.visible = False
        self.text = ("", "")
        self.rectangle = None
        self.ready = False

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True, name="taskbar-clock")
        self.thread.start()

    def stop(self):
        self.stopping.set()
        if self.window:
            self.user.PostMessageW(self.window, 0x10, 0, 0)

    def _bind(self):
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        definitions = [
            (self.kernel, "GetModuleHandleW", [w.LPCWSTR], w.HMODULE),
            (self.kernel, "CreateMutexW", [ctypes.c_void_p, w.BOOL, w.LPCWSTR], w.HANDLE),
            (self.kernel, "CloseHandle", [w.HANDLE], w.BOOL),
            (self.user, "SetThreadDpiAwarenessContext", [w.HANDLE], w.HANDLE),
            (self.user, "RegisterClassW", [ctypes.POINTER(WindowClass)], w.ATOM),
            (self.user, "UnregisterClassW", [w.LPCWSTR, w.HINSTANCE], w.BOOL),
            (
                self.user,
                "CreateWindowExW",
                [
                    w.DWORD,
                    w.LPCWSTR,
                    w.LPCWSTR,
                    w.DWORD,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    w.HWND,
                    w.HMENU,
                    w.HINSTANCE,
                    ctypes.c_void_p,
                ],
                w.HWND,
            ),
            (self.user, "DefWindowProcW", [w.HWND, w.UINT, w.WPARAM, w.LPARAM], ctypes.c_ssize_t),
            (self.user, "SetLayeredWindowAttributes", [w.HWND, w.DWORD, w.BYTE, w.DWORD], w.BOOL),
            (
                self.user,
                "SetTimer",
                [w.HWND, ctypes.c_size_t, w.UINT, ctypes.c_void_p],
                ctypes.c_size_t,
            ),
            (self.user, "GetMessageW", [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT], w.BOOL),
            (self.user, "TranslateMessage", [ctypes.POINTER(w.MSG)], w.BOOL),
            (self.user, "DispatchMessageW", [ctypes.POINTER(w.MSG)], ctypes.c_ssize_t),
            (self.user, "PostMessageW", [w.HWND, w.UINT, w.WPARAM, w.LPARAM], w.BOOL),
            (self.user, "DestroyWindow", [w.HWND], w.BOOL),
            (self.user, "PostQuitMessage", [ctypes.c_int], None),
            (self.user, "ShowWindow", [w.HWND, ctypes.c_int], w.BOOL),
            (
                self.user,
                "SetWindowPos",
                [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.UINT],
                w.BOOL,
            ),
            (self.user, "SetWindowTextW", [w.HWND, w.LPCWSTR], w.BOOL),
            (self.user, "InvalidateRect", [w.HWND, ctypes.POINTER(w.RECT), w.BOOL], w.BOOL),
            (self.user, "GetForegroundWindow", [], w.HWND),
            (self.user, "GetClassNameW", [w.HWND, w.LPWSTR, ctypes.c_int], ctypes.c_int),
            (self.user, "GetWindowRect", [w.HWND, ctypes.POINTER(w.RECT)], w.BOOL),
            (self.user, "GetDpiForWindow", [w.HWND], w.UINT),
            (self.user, "BeginPaint", [w.HWND, ctypes.POINTER(PaintStruct)], w.HDC),
            (self.user, "EndPaint", [w.HWND, ctypes.POINTER(PaintStruct)], w.BOOL),
            (self.user, "GetClientRect", [w.HWND, ctypes.POINTER(w.RECT)], w.BOOL),
            (self.user, "FillRect", [w.HDC, ctypes.POINTER(w.RECT), w.HBRUSH], ctypes.c_int),
            (
                self.user,
                "DrawTextW",
                [w.HDC, w.LPCWSTR, ctypes.c_int, ctypes.POINTER(w.RECT), w.UINT],
                ctypes.c_int,
            ),
            (self.gdi, "CreateSolidBrush", [w.DWORD], w.HBRUSH),
            (self.gdi, "DeleteObject", [w.HANDLE], w.BOOL),
            (self.gdi, "SelectObject", [w.HDC, w.HANDLE], w.HANDLE),
            (self.gdi, "SetTextColor", [w.HDC, w.DWORD], w.DWORD),
            (self.gdi, "SetBkMode", [w.HDC, ctypes.c_int], ctypes.c_int),
            (self.gdi, "CreateFontW", [ctypes.c_int] * 5 + [w.DWORD] * 8 + [w.LPCWSTR], w.HFONT),
        ]
        for library, name, arguments, result in definitions:
            method = getattr(library, name)
            method.argtypes, method.restype = arguments, result

    def _run(self):
        mutex = None
        registered = initialized = False
        try:
            self._bind()
            # Preserve the legacy name so old and new builds cannot overlap clocks.
            mutex = self.kernel.CreateMutexW(None, False, "Local\\DesktopTimezone.TaskbarClock")
            if not mutex:
                raise ctypes.WinError(ctypes.get_last_error())
            if ctypes.get_last_error() == 183:
                raise RuntimeError("另一个独立时区工具已启用任务栏时钟，请先在该工具中关闭。")
            # UIA rectangles and this window share physical pixels, at any scaling.
            self.user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
            comtypes.CoInitializeEx(0)
            initialized = True
            self.locator = TaskbarLocator()
            self.clock = ZoneClock(self.zone)
            self.instance = self.kernel.GetModuleHandleW(None)
            self.class_name = "DesktopTimezoneClock"
            self.procedure = PROCEDURE(self._message)
            definition = WindowClass(
                instance=self.instance, name=self.class_name, procedure=self.procedure
            )
            if not self.user.RegisterClassW(ctypes.byref(definition)):
                raise ctypes.WinError(ctypes.get_last_error())
            registered = True
            # LAYERED | TRANSPARENT | TOOLWINDOW | NOACTIVATE; never take focus.
            self.window = self.user.CreateWindowExW(
                0x080800A0,
                self.class_name,
                "ClaudeBuddy 时钟",
                0x80000000,
                0,
                0,
                1,
                1,
                None,
                None,
                self.instance,
                None,
            )
            if not self.window or not self.user.SetLayeredWindowAttributes(self.window, 0, 255, 2):
                raise ctypes.WinError(ctypes.get_last_error())
            self.started = time.monotonic()
            if not self.user.SetTimer(self.window, 1, 500, None):
                raise ctypes.WinError(ctypes.get_last_error())
            self._tick()
            message = w.MSG()
            while not self.stopping.is_set():
                result = self.user.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result == -1:
                    raise ctypes.WinError(ctypes.get_last_error())
                if result == 0:
                    break
                self.user.TranslateMessage(ctypes.byref(message))
                self.user.DispatchMessageW(ctypes.byref(message))
        except Exception as error:
            self.report({"event": "failed", "error": str(error)})
        finally:
            if self.window:
                self.user.DestroyWindow(self.window)
                self.window = None
            self.visible = False
            self.locator = None
            if registered:
                self.user.UnregisterClassW(self.class_name, self.instance)
            if initialized:
                comtypes.CoUninitialize()
            if mutex:
                self.kernel.CloseHandle(mutex)
            self.report({"event": "stopped"})

    def _tick(self):
        if self.stopping.is_set():
            return
        if self.clock.zone != self.zone:
            self.clock = ZoneClock(self.zone)
        now = self.clock.now()
        text = (now.strftime("%H:%M"),)
        if self.show_date:
            text += (f"{now.month}/{now.day}",)
        if text != self.text:
            self.text = text
            self.user.SetWindowTextW(
                self.window, f"ClaudeBuddy 时钟 · {now:%Y-%m-%d %H:%M} · {self.zone}"
            )
            self.user.InvalidateRect(self.window, None, False)
        rect = self.locator.locate()
        if not rect and not self.ready and time.monotonic() - self.started > 10:
            raise RuntimeError(
                "未识别到主屏任务栏时钟。请显示任务栏后重试；此 Windows 布局可能尚不支持。"
            )
        foreground = self.user.GetForegroundWindow()
        kind = ctypes.create_unicode_buffer(64)
        self.user.GetClassNameW(foreground, kind, len(kind))
        bounds = w.RECT()
        if (
            rect
            and foreground not in (self.window, self.locator.window)
            and kind.value not in ("Progman", "WorkerW")
        ):
            if self.user.GetWindowRect(foreground, ctypes.byref(bounds)):
                # Hide under fullscreen apps and shell flyouts covering the clock.
                if (
                    bounds.left <= rect[0]
                    and bounds.top <= rect[1]
                    and bounds.right >= rect[2]
                    and bounds.bottom >= rect[3]
                ):
                    rect = None
        if rect:
            left, top, right, bottom = rect
            # Inset the whole overlay so its background leaves taskbar edges visible.
            top += 2
            bottom -= 2
            if not self.user.SetWindowPos(
                self.window, ctypes.c_void_p(-1), left, top, right - left, bottom - top, 0x50
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            self.visible, self.rectangle = True, (left, top, right, bottom)
            if not self.ready:
                self.ready = True
                self.report({"event": "ready"})
        else:
            self.user.ShowWindow(self.window, 0)
            self.visible = False

    def _message(self, window, message, word, long):
        try:
            if message == 0x113:
                self._tick()
                return 0
            if message == 0x0F:
                self._paint(window)
                return 0
            if message == 0x14:
                return 1
            if message == 0x84:
                return -1
            if message == 0x21:
                return 3
            if message == 0x10:
                self.user.DestroyWindow(window)
                self.window = None
                return 0
            if message == 0x02:
                self.user.PostQuitMessage(0)
                return 0
        except Exception as error:
            self.report({"event": "failed", "error": str(error)})
            self.stopping.set()
            self.user.PostMessageW(window, 0x10, 0, 0)
            return 0
        return self.user.DefWindowProcW(window, message, word, long)

    def _paint(self, window):
        paint, rect = PaintStruct(), w.RECT()
        dc = self.user.BeginPaint(window, ctypes.byref(paint))
        brush = font = previous = None
        try:
            light = False
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                ) as key:
                    light = bool(winreg.QueryValueEx(key, "SystemUsesLightTheme")[0])
            except OSError:
                pass
            brush = self.gdi.CreateSolidBrush(0xF3F3F3 if light else 0x202020)
            self.user.GetClientRect(window, ctypes.byref(rect))
            self.user.FillRect(dc, ctypes.byref(rect), brush)
            dpi = self.user.GetDpiForWindow(window) or 96
            line_count = max(1, len(self.text))
            size = min(round(12 * dpi / 96), max(9, rect.bottom // line_count - 2))
            font = self.gdi.CreateFontW(-size, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe UI")
            previous = self.gdi.SelectObject(dc, font)
            self.gdi.SetTextColor(dc, 0x161616 if light else 0xFFFFFF)
            self.gdi.SetBkMode(dc, 1)
            for index, line in enumerate(self.text):
                bounds = w.RECT(
                    0,
                    rect.bottom * index // line_count,
                    rect.right,
                    rect.bottom * (index + 1) // line_count,
                )
                self.user.DrawTextW(dc, line, -1, ctypes.byref(bounds), 0x825)
        finally:
            if previous:
                self.gdi.SelectObject(dc, previous)
            if font:
                self.gdi.DeleteObject(font)
            if brush:
                self.gdi.DeleteObject(brush)
            self.user.EndPaint(window, ctypes.byref(paint))
