import queue
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk

from .configuration import config_path, default_config, load_config, save_config
from .launching import ApplicationLauncher
from .profiles import PROFILES, detect_executable
from .taskbar_clock import TaskbarClock
from .tray import TrayIcon

REPOSITORY_URL = "https://github.com/ifzc/ClaudeBuddy"

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
        self.launcher = ApplicationLauncher(key, self.emit)
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
        self.status = tk.StringVar(value="准备就绪：可随时点击启动" + self.label + "。")
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
        self.start_button = ttk.Button(buttons, text="启动" + self.label, command=self.start)
        self.start_button.pack(side="left")

    @property
    def controller(self):
        return self.launcher.controller

    def append(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def emit(self, event):
        self.owner.events.put((self.key, event))

    def start(self):
        if self.busy:
            return
        if not self.exe.is_file() or self.exe.name.lower() not in PROFILES[self.key]["executables"]:
            messagebox.showerror(
                "找不到" + self.label,
                f"请在 config.json 的 apps.{self.key}.executable 中填写完整路径。\n当前路径：{self.exe}",
            )
            return
        self.config["timeZone"] = LABELS[self.zone_label.get()]
        try:
            self.owner.save_config()
        except OSError:
            messagebox.showerror("配置保存失败", "请将整个文件夹放在有写入权限的位置再运行。")
            return
        self.busy = True
        if not self.launcher.is_running():
            self.verified.clear()
            self.failure_count = 0
        self.combo.configure(state="disabled")
        self.status.set("正在打开" + self.label + "……")
        threading.Thread(target=self.start_worker, daemon=True).start()

    def start_worker(self):
        try:
            result = self.launcher.start(str(self.exe), self.config["timeZone"])
            self.emit({"event": "ready", "result": result})
        except Exception as error:
            self.emit({"event": "failed", "error": str(error)})

    def check_process(self):
        if self.busy or not self.launcher.process_handle or self.launcher.is_running():
            return
        self.busy = True

        def release():
            self.launcher.release()
            self.emit({"event": "exited"})

        threading.Thread(target=release, daemon=True).start()

    def handle(self, event):
        kind = event["event"]
        if kind == "probe":
            self.verified.add(event["pid"])
            self.append(f"进程 {event['pid']}：{event['timeZone']}")
            self.detail.set(f"已验证 {len(self.verified)} 个界面进程。可重复点击启动以打开窗口。")
        elif kind in ("child_error", "agent_error"):
            self.failure_count += 1
            self.status.set("部分界面进程未能应用时区，可退出应用后再次启动。")
            self.append("未覆盖的界面进程：" + event["error"])
        elif kind == "ready":
            self.busy = False
            if self.controller:
                if not self.failure_count:
                    self.status.set("已启动：" + self.launcher.zone + " · 可再次点击打开窗口")
            else:
                self.combo.configure(state="readonly")
                self.status.set("已打开正在运行的" + self.label + "，沿用当前会话时区。")
                self.detail.set("退出应用后再次点击启动，会应用上方选择的时区。")
        elif kind == "exited":
            self.busy = False
            self.verified.clear()
            self.status.set(self.label + "已退出，可再次点击启动。")
            self.combo.configure(state="readonly")
        elif kind == "failed":
            self.busy = False
            self.status.set("启动失败，可再次点击重试。")
            self.append(event["error"])
            messagebox.showerror(self.label + "操作失败", event["error"])
            if not self.controller:
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
            self.status.set(
                "等待任务栏时钟恢复显示，将自动重新定位。"
                if self.controller.waiting
                else "已启用：" + self.config["timeZone"] + " · Windows 系统时区未修改"
            )
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
        elif event["event"] == "waiting":
            self.busy = False
            self.start_button.configure(state="normal")
            self.status.set("等待任务栏时钟恢复显示，将自动重新定位。")
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
        assets = Path(__file__).with_name("assets")
        root.iconbitmap(default=str(assets / "claudebuddy.ico"))
        self.brand_icon = tk.PhotoImage(file=str(assets / "claudebuddy.png")).subsample(8, 8)
        self.github_icon = tk.PhotoImage(file=str(assets / "github.png"))
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
        header = ttk.Frame(outer)
        header.pack(fill="x")
        ttk.Label(
            header,
            text=" ClaudeBuddy",
            image=self.brand_icon,
            compound="left",
            font=("Microsoft YaHei UI", 17, "bold"),
        ).pack(side="left")
        style = ttk.Style(root)
        style.layout(
            "GitHub.TButton",
            [("Button.padding", {"children": [("Button.label", {"sticky": "nswe"})]})],
        )
        self.github_button = ttk.Button(
            header,
            text="GitHub",
            image=self.github_icon,
            compound="none",
            style="GitHub.TButton",
            padding=4,
            cursor="hand2",
            command=self.open_repository,
        )
        self.github_button.pack(side="right")
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
            text="实验版 · 关闭窗口后在托盘继续运行 · 应用退出后可再次点击启动",
            foreground="#666666",
        ).pack(anchor="w", pady=(12, 0))
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll)

    def open_repository(self):
        if not webbrowser.open_new_tab(REPOSITORY_URL):
            messagebox.showerror("无法打开 GitHub", "请在浏览器中访问：\n" + REPOSITORY_URL)

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
        for panel in self.panels.values():
            if isinstance(panel, AppPanel):
                panel.launcher.release()
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
            label="维护时区中 · 应用退出后可退出工具" if active else "退出工具",
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
        for panel in self.panels.values():
            if isinstance(panel, AppPanel):
                panel.check_process()
        self.root.after(100, self.poll)


def main():
    if sys.platform != "win32":
        raise SystemExit("ClaudeBuddy requires Windows.")
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
