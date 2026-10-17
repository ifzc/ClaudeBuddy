"""Supported applications and their deliberately limited process scopes."""

import os
import re
from pathlib import Path

ZONES = {
    "Asia/Shanghai": "China Standard Time",
    "Asia/Tokyo": "Tokyo Standard Time",
    "America/Phoenix": "US Mountain Standard Time",
    "America/New_York": "Eastern Standard Time",
    "America/Los_Angeles": "Pacific Standard Time",
    "Europe/London": "GMT Standard Time",
    "UTC": "UTC",
}

PROFILES = {
    "feishu": {"label": "飞书", "executables": ("feishu.exe",), "gate_children": True},
    "weixin": {"label": "微信", "executables": ("weixin.exe",), "gate_children": False},
}


def child_needs_timezone(profile, path, command_line):
    # Weixin 4.x renders chats in the native main process. OCR, media,
    # utility and WeChatAppEx mini-app processes keep their original zone.
    return (
        profile == "feishu"
        and Path(path or "").name.lower() == "feishu.exe"
        and bool(re.search(r"(?:^|\s)--type=renderer(?:\s|$)", command_line))
    )


def detect_executable(profile):
    if profile == "feishu":
        return Path(os.environ.get("LOCALAPPDATA", "")) / "Feishu" / "app" / "Feishu.exe"
    if profile != "weixin":
        raise ValueError("Unknown application profile: " + profile)
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Tencent"
        / "Weixin"
        / "Weixin.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Tencent"
        / "Weixin"
        / "Weixin.exe",
    ]
    return next((path for path in candidates if path.is_file()), candidates[0])
