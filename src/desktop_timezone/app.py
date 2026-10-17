import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import frida

from .configuration import config_path, default_config, load_config, save_config
from .native_timezone import (
    Controller,
    close_process_watch,
    open_process_watch,
    watched_process_is_running,
    zone_config,
)
from .profiles import PROFILES, detect_executable
from .taskbar_clock import TaskbarClock
from .tray import TrayIcon

LABELS = {
    "北京时间（UTC+8）": "Asia/Shanghai",
    "亚利桑那时间（UTC-7）": "America/Phoenix",
    "东京时间（UTC+9）": "Asia/Tokyo",
    "纽约时间（自动夏令时）": "America/New_York",
    "洛杉矶时间（自动夏令时）": "America/Los_Angeles",
    "伦敦时间（自动夏令时）": "Europe/London",
    "协调世界时（UTC）": "UTC",
}


class AppPanel:
    def __init__(self, owner, key, parent):
        self.owner, self.key = owner, key
        self.label = PROFILES[key]["label"]
        self.controller = None
        self.process_handle = None
        self.busy = False
        self.verified = set()
        self.failure_count = 0
        self.config = owner.config["apps"].setdefault(key, {"timeZone": "Asia/Shanghai"})
        self.exe = Path(self.config.get("executable") or detect_executable(key))
        frame = ttk.Frame(parent, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=self.label + "时区", font=("Microsoft YaHei UI", 12, "bold")).pack(
            anchor="w"
        )
        self.zone_label = tk.StringVar(
            value=next(
                (k for k, v in LABELS.items() if v == self.config.get("timeZone")),
                next(iter(LABELS)),
            )
        )
        self.combo = ttk.Combobox(
            frame,
            textvariable=self.zone_label,
            values=list(LABELS),
            state="readonly",
            font=("Microsoft YaHei UI", 11),
        )
        self.combo.pack(fill="x", pady=(8, 16))
        self.status = tk.StringVar(value="准备就绪：请先从系统托盘完全退出" + self.label + "。")
        ttk.Label(frame, textvariable=self.status, wraplength=560).pack(anchor="w")
        scope = (
            "聊天主界面；小程序与内置网页不在覆盖范围。"
            if key == "weixin"
            else "聊天与日历界面；后台服务保持原设置。"
        )
        self.detail = tk.StringVar(value=scope)
        ttk.Label(frame, textvariable=self.detail, wraplength=560, foreground="#555555").pack(
            anchor="w", pady=(9, 0)
        )
        self.log = tk.Text(
            frame,
            height=6,
            state="disabled",
            font=("Microsoft YaHei UI", 9),
            relief="solid",
            borderwidth=1,
        )
        self.log.pack(fill="both", expand=True, pady=16)
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")
        self.start_button = ttk.Button(
            buttons, text="应用时区并启动" + self.label, command=self.start
        )
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(
            buttons, text="恢复普通启动", command=self.stop, state="disabled"
        )
        self.stop_button.pack(side="right")

    def append(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def emit(self, event):
        self.owner.events.put((self.key, event))

    def start(self):
        if self.busy or self.controller:
            return
        if not self.exe.is_file() or self.exe.name.lower() not in PROFILES[self.key]["executables"]:
            messagebox.showerror(
                "找不到" + self.label,
                f"请在 config.json 的 apps.{self.key}.executable 中填写完整路径。\n当前路径：{self.exe}",
            )
            return
        running = [
            p
            for p in frida.get_local_device().enumerate_processes()
            if p.name.lower() in PROFILES[self.key]["executables"]
        ]
        if running:
            messagebox.showinfo(
                "请先退出" + self.label,
                "请先保存草稿、结束通话，并从系统托盘完全退出" + self.label + "，再点击启动。",
            )
            return
        self.config["timeZone"] = LABELS[self.zone_label.get()]
        try:
            self.owner.save_config()
        except OSError:
            messagebox.showerror("配置保存失败", "请将整个文件夹放在有写入权限的位置再运行。")
            return
        self.busy = True
        self.verified.clear()
        self.failure_count = 0
        self.start_button.configure(state="disabled")
        self.combo.configure(state="disabled")
        self.status.set("正在启动" + self.label + "并应用时区……")
        threading.Thread(target=self.start_worker, daemon=True).start()

    def start_worker(self):
        controller = None
        try:
            controller = Controller(
                zone_config(self.config["timeZone"]), self.emit, profile=self.key
            )
            controller.launch(str(self.exe))
            self.emit(
                {
                    "event": "ready",
                    "controller": controller,
                    "handle": open_process_watch(controller.root_pid),
                }
            )
        except Exception as error:
            if controller:
                controller.close()
            self.emit({"event": "failed", "error": str(error)})

    def stop(self, confirmed=False):
        if self.busy or not self.controller:
            return
        if not confirmed and not messagebox.askyesno(
            "恢复普通启动",
            "这会退出并重新打开由本工具启动的"
            + self.label
            + "，以清除时区缓存。\n\n请先保存草稿并结束通话。现在恢复吗？",
        ):
            return
        self.busy = True
        self.stop_button.configure(state="disabled")
        self.status.set("正在恢复普通启动……")
        threading.Thread(target=self.stop_worker, daemon=True).start()

    def stop_worker(self):
        try:
            # Retain a live process handle to prevent PID reuse. Terminate the
            # confirmed owned process tree before detaching native callbacks.
            if watched_process_is_running(self.process_handle):
                result = subprocess.run(
                    ["taskkill", "/PID", str(self.controller.root_pid), "/T", "/F"],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                if result.returncode:
                    raise RuntimeError(self.label + "未能完全退出，请从托盘手动退出并正常重启。")
            self.controller.close()
            close_process_watch(self.process_handle)
            self.process_handle = None
            self.controller = None
            subprocess.Popen([str(self.exe)], creationflags=subprocess.CREATE_NO_WINDOW)
            self.emit({"event": "stopped"})
        except Exception as error:
            self.emit({"event": "failed", "error": str(error)})

    def handle(self, event):
        kind = event["event"]
        if kind == "probe":
            self.verified.add(event["pid"])
            self.append(f"进程 {event['pid']}：{event['timeZone']}")
            self.detail.set(f"已验证 {len(self.verified)} 个界面进程。更换时区请先恢复普通启动。")
        elif kind in ("child_error", "agent_error"):
            self.failure_count += 1
            self.status.set("部分界面进程未能应用时区，请恢复普通启动。")
            self.append("未覆盖的界面进程：" + event["error"])
        elif kind == "ready":
            self.controller = event["controller"]
            self.process_handle = event["handle"]
            self.busy = False
            self.stop_button.configure(state="normal")
            if not self.failure_count:
                self.status.set("已启动：" + self.config["timeZone"])
        elif kind == "stopped":
            self.busy = False
            self.status.set("已恢复普通启动，Windows 系统时区未修改。")
            self.start_button.configure(state="normal")
            self.combo.configure(state="readonly")
        elif kind == "failed":
            self.busy = False
            self.status.set("操作失败，请完全退出" + self.label + "后用原快捷方式启动。")
            self.append(event["error"])
            messagebox.showerror(self.label + "操作失败", event["error"])
            if self.controller:
                self.stop_button.configure(state="normal")
            else:
                self.start_button.configure(state="normal")
                self.combo.configure(state="readonly")


class TaskbarPanel:
    def __init__(self, owner, parent):
        self.owner = owner
        self.config = owner.config["taskbar"]
        self.controller = None
        self.busy = False
        self.failed = False
        frame = ttk.Frame(parent, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="任务栏时钟时区", font=("Microsoft YaHei UI", 12, "bold")).pack(
            anchor="w"
        )
        self.zone_label = tk.StringVar(
            value=next(k for k, v in LABELS.items() if v == self.config["timeZone"])
        )
        self.combo = ttk.Combobox(
            frame,
            textvariable=self.zone_label,
            values=list(LABELS),
            state="readonly",
            font=("Microsoft YaHei UI", 11),
        )
        self.combo.pack(fill="x", pady=(8, 16))
        self.status = tk.StringVar(value="未启用：当前显示 Windows 原来的任务栏时钟。")
        self.show_date = tk.BooleanVar(value=self.config["showDate"])
        ttk.Checkbutton(
            frame,
            text="显示日期（取消后只显示时间）",
            variable=self.show_date,
            command=self.change_date_visibility,
        ).pack(anchor="w", pady=(0, 12))
        ttk.Label(frame, textvariable=self.status, wraplength=550).pack(anchor="w")
        ttk.Label(
            frame,
            text="在主屏任务栏原时钟的位置显示所选时区的时间和日期。\n"
            "点击时钟仍可打开 Windows 日历；日历面板保持系统时区。\n\n"
            "无需重启资源管理器。关闭设置窗口后会继续在托盘运行，\n"
            "再次打开工具会恢复已启用的任务栏时钟。",
            wraplength=550,
            foreground="#555555",
            justify="left",
        ).pack(anchor="w", pady=16, fill="both", expand=True)
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")
        self.start_button = ttk.Button(buttons, text="应用任务栏时区", command=self.start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(
            buttons, text="关闭独立时钟", command=self.stop, state="disabled"
        )
        self.stop_button.pack(side="right")
        if self.config["enabled"]:
            owner.root.after(150, self.start)

    def emit(self, event):
        self.owner.events.put(("taskbar", event))

    def change_date_visibility(self):
        previous = self.config["showDate"]
        self.config["showDate"] = self.show_date.get()
        if not self.save():
            self.config["showDate"] = previous
            self.show_date.set(previous)
            return
        if self.controller:
            self.controller.show_date = self.config["showDate"]

    def save(self):
        try:
            self.owner.save_config()
            return True
        except OSError:
            messagebox.showerror("配置保存失败", "请将整个文件夹放在有写入权限的位置再运行。")
            return False

    def start(self):
        if self.busy:
            return
        previous = self.config.copy()
        self.config.update(timeZone=LABELS[self.zone_label.get()], enabled=True)
        if not self.save():
            self.config.update(previous)
            return
        if self.controller:
            self.controller.zone = self.config["timeZone"]
            self.status.set("已启用：" + self.config["timeZone"] + " · Windows 系统时区未修改")
            return
        self.failed = False
        self.busy = True
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status.set("正在定位主屏任务栏时钟……")
        self.controller = TaskbarClock(
            self.config["timeZone"], self.emit, show_date=self.config["showDate"]
        )
        self.controller.start()

    def stop(self):
        if not self.controller:
            return
        previous = self.config["enabled"]
        self.config["enabled"] = False
        if not self.save():
            self.config["enabled"] = previous
            return
        self.busy = True
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="disabled")
        self.controller.stop()

    def handle(self, event):
        if event["event"] == "ready":
            self.busy = False
            self.start_button.configure(state="normal")
            self.status.set("已启用：" + self.config["timeZone"] + " · Windows 系统时区未修改")
        elif event["event"] == "failed":
            self.failed = True
            self.status.set("启用失败：" + event["error"])
        elif event["event"] == "stopped":
            self.controller = None
            self.busy = False
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
            if self.failed:
                self.config["enabled"] = False
                self.save()
            else:
                self.status.set("已关闭独立时钟，显示 Windows 原来的任务栏时间。")


class App:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.tray = TrayIcon(root, lambda action: self.events.put((None, {"event": action})))
        self.config_path = config_path()
        try:
            self.config = load_config(self.config_path)
        except (OSError, ValueError) as error:
            self.config = default_config()
            messagebox.showwarning("配置读取失败", "已使用默认北京时间。\n" + str(error))
        root.title("ClaudeBuddy · 桌面独立时区")
        root.geometry("660x505")
        root.minsize(620, 470)
        outer = ttk.Frame(root, padding=20)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="ClaudeBuddy", font=("Microsoft YaHei UI", 17, "bold")).pack(
            anchor="w"
        )
        ttk.Label(outer, text="飞书、微信和任务栏时钟可分别设置。电脑系统时区保持原样。").pack(
            anchor="w", pady=(8, 16)
        )
        notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True)
        self.panels = {}
        for key, profile in PROFILES.items():
            tab = ttk.Frame(notebook)
            notebook.add(tab, text="  " + profile["label"] + "  ")
            self.panels[key] = AppPanel(self, key, tab)
        tab = ttk.Frame(notebook)
        notebook.add(tab, text="  任务栏时钟  ")
        self.panels["taskbar"] = TaskbarPanel(self, tab)
        # Keep Feishu first; focus Weixin for a Weixin-only invocation.
        if "--weixin" in sys.argv:
            notebook.select(1)
        if "--taskbar" in sys.argv:
            notebook.select(2)
        ttk.Label(
            outer,
            text="实验版 · 关闭窗口后在托盘继续运行 · 恢复普通模式请手动操作",
            foreground="#666666",
        ).pack(anchor="w", pady=(12, 0))
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll)

    def save_config(self):
        save_config(self.config_path, self.config)

    def close(self):
        if any(p.controller or p.busy for p in self.panels.values()):
            try:
                self.tray.show()
            except OSError:
                # Keep sessions alive even if Explorer cannot host a tray icon.
                self.root.iconify()
            else:
                self.root.withdraw()
            return
        self.tray.close()
        self.root.destroy()

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.tray.remove()

    def show_tray_menu(self):
        self.tray_menu = tk.Menu(self.root, tearoff=False)
        self.tray_menu.add_command(label="打开时区设置", command=self.show)
        self.tray_menu.add_separator()
        active = any(p.controller or p.busy for p in self.panels.values())
        self.tray_menu.add_command(
            label="维护时区中 · 退出前请手动恢复" if active else "退出工具",
            command=self.close,
            state="disabled" if active else "normal",
        )
        # A native foreground owner keeps the popup dismissible when clicked away.
        self.tray.user.SetForegroundWindow(self.tray.window)
        self.tray_menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())

    def poll(self):
        while not self.events.empty():
            key, event = self.events.get()
            if key is None:
                if event["event"] == "show":
                    self.show()
                elif event["event"] == "menu":
                    self.show_tray_menu()
            else:
                self.panels[key].handle(event)
        self.root.after(100, self.poll)


def main():
    if sys.platform != "win32":
        raise SystemExit("ClaudeBuddy requires Windows.")
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
