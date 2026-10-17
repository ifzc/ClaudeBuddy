"""Load validated user configuration without writing into installed packages."""

import json
import sys
from pathlib import Path

from .profiles import PROFILES, ZONES


def default_config():
    return {
        "apps": {key: {"timeZone": "Asia/Shanghai"} for key in PROFILES},
        "taskbar": {"timeZone": "Asia/Shanghai", "enabled": False},
    }


def config_path():
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
    return base / "config.json"


def load_config(path):
    config = default_config()
    if not path.exists():
        return config
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict) or not isinstance(raw.get("apps", {}), dict):
        raise ValueError("config.json and apps must be JSON objects")
    for key in PROFILES:
        entry = raw.get("apps", {}).get(key, {})
        if not isinstance(entry, dict):
            raise ValueError(f"apps.{key} must be a JSON object")
        zone = entry.get("timeZone", "Asia/Shanghai")
        if not isinstance(zone, str) or zone not in ZONES:
            raise ValueError(f"Unsupported time zone in apps.{key}")
        config["apps"][key]["timeZone"] = zone
        executable = entry.get("executable")
        if executable is not None:
            if not isinstance(executable, str) or not executable.strip():
                raise ValueError(f"apps.{key}.executable must be a nonempty path string")
            config["apps"][key]["executable"] = executable
    taskbar = raw.get("taskbar", {})
    if not isinstance(taskbar, dict):
        raise ValueError("taskbar must be a JSON object")
    zone = taskbar.get("timeZone", "Asia/Shanghai")
    enabled = taskbar.get("enabled", False)
    if not isinstance(zone, str) or zone not in ZONES:
        raise ValueError("Unsupported time zone in taskbar")
    if not isinstance(enabled, bool):
        raise ValueError("taskbar.enabled must be a boolean")
    config["taskbar"] = {"timeZone": zone, "enabled": enabled}
    return config


def save_config(path, config):
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
