"""Windows notification icon using the existing Tk message loop."""

import ctypes
from ctypes import wintypes as w


class NotificationData(ctypes.Structure):
    _fields_ = [
        ("size", w.DWORD),
        ("window", w.HWND),
        ("identifier", w.UINT),
        ("flags", w.UINT),
        ("callback_message", w.UINT),
        ("icon", w.HICON),
        ("tip", w.WCHAR * 128),
        ("state", w.DWORD),
        ("state_mask", w.DWORD),
        ("info", w.WCHAR * 256),
        ("version", w.UINT),
        ("info_title", w.WCHAR * 64),
        ("info_flags", w.DWORD),
        ("guid", ctypes.c_byte * 16),
        ("balloon_icon", w.HICON),
    ]


class TrayIcon:
    MESSAGE = 0x8000 + 20

    def __init__(self, root, report):
        self.root = root
        self.report = report
        self.visible = False
        self.callback = None
        self.window = None
        self.previous = None
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.shell = ctypes.WinDLL("shell32", use_last_error=True)
        self.user.SetWindowLongPtrW.argtypes = [w.HWND, ctypes.c_int, ctypes.c_ssize_t]
        self.user.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        self.user.CallWindowProcW.argtypes = [ctypes.c_void_p, w.HWND, w.UINT, w.WPARAM, w.LPARAM]
        self.user.CallWindowProcW.restype = ctypes.c_ssize_t
        self.user.LoadIconW.argtypes = [w.HINSTANCE, ctypes.c_void_p]
        self.user.LoadIconW.restype = w.HICON
        self.user.RegisterWindowMessageW.argtypes = [w.LPCWSTR]
        self.user.RegisterWindowMessageW.restype = w.UINT
        self.user.SetForegroundWindow.argtypes = [w.HWND]
        self.user.SetForegroundWindow.restype = w.BOOL
        self.shell.Shell_NotifyIconW.argtypes = [w.DWORD, ctypes.POINTER(NotificationData)]
        self.shell.Shell_NotifyIconW.restype = w.BOOL
        self.taskbar_created = self.user.RegisterWindowMessageW("TaskbarCreated")

    def _install_callback(self):
        if self.callback is not None:
            return
        self.root.update_idletasks()
        self.window = self.root.winfo_id()
        procedure = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)

        def handle(window, message, word, long):
            if message == self.MESSAGE:
                if long in (0x202, 0x203):  # left-button up / double-click
                    self.report("show")
                elif long == 0x205:  # right-button up
                    self.report("menu")
                return 0
            if message == self.taskbar_created and self.visible:
                self.shell.Shell_NotifyIconW(0, ctypes.byref(self.data))
            return self.user.CallWindowProcW(self.previous, window, message, word, long)

        self.callback = procedure(handle)
        ctypes.set_last_error(0)
        self.previous = self.user.SetWindowLongPtrW(
            self.window, -4, ctypes.cast(self.callback, ctypes.c_void_p).value
        )
        if not self.previous:
            self.callback = None
            raise ctypes.WinError()
        self.data = NotificationData()
        self.data.size = ctypes.sizeof(self.data)
        self.data.window = self.window
        self.data.identifier = 1
        self.data.flags = 1 | 2 | 4  # message, icon, tooltip
        self.data.callback_message = self.MESSAGE
        self.data.icon = self.user.LoadIconW(None, ctypes.c_void_p(32512))
        self.data.tip = "ClaudeBuddy · 飞书 + 微信 + 任务栏（点击打开设置）"

    def show(self):
        self._install_callback()
        if not self.visible:
            if not self.shell.Shell_NotifyIconW(0, ctypes.byref(self.data)):
                raise OSError("Windows notification icon could not be created")
            self.visible = True

    def remove(self):
        if self.visible:
            self.shell.Shell_NotifyIconW(2, ctypes.byref(self.data))
            self.visible = False

    def close(self):
        self.remove()
        if self.callback is not None:
            self.user.SetWindowLongPtrW(self.window, -4, self.previous)
            self.callback = None
