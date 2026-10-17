import json
import subprocess
import sys
import time
from pathlib import Path

from desktop_timezone.native_timezone import (
    Controller,
    close_process_watch,
    open_process_watch,
    watched_process_is_running,
    zone_config,
)
from desktop_timezone.profiles import ZONES

results = []
root = Path(__file__).parent
for zone, offset, january_hour, july_hour in [
    ("Asia/Shanghai", 480, 20, 20),
    ("America/Phoenix", -420, 5, 5),
    ("America/New_York", None, 7, 8),
]:
    # A Windows venv python.exe can be a redirector spawning the real interpreter;
    # use the base executable so Popen.pid is the process executing the probe.
    process = subprocess.Popen(
        [sys._base_executable, "-u", str(root / "clock_probe.py")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    before = json.loads(process.stdout.readline())
    watch = open_process_watch(process.pid)
    assert watched_process_is_running(watch)
    reports = []
    controller = Controller(zone_config(zone), report=reports.append)
    try:
        probe = controller.attach(process.pid, gate_children=False)
        process.stdin.write("sample\n")
        process.stdin.flush()
        during = json.loads(process.stdout.readline())
        assert during["key"] == ZONES[zone], {"during": during, "probe": probe, "reports": reports}
        if offset is not None:
            assert during["offsetMinutes"] == offset, during
        assert during["conversions"][0][3] == january_hour, during
        assert during["conversions"][1][3] == july_hour, during
        assert abs(during["epoch"] - time.time()) < 3, during
    finally:
        controller.close()
    process.stdin.write("sample\n")
    process.stdin.flush()
    after = json.loads(process.stdout.readline())
    assert after["key"] == before["key"], (before, after)
    assert after["conversions"] == before["conversions"], (before, after)
    process.stdin.write("quit\n")
    process.stdin.flush()
    process.wait(timeout=5)
    assert process.returncode == 0
    assert not watched_process_is_running(watch)
    close_process_watch(watch)
    results.append(
        {
            "zone": zone,
            "nativeOverride": True,
            "winterAndSummer": True,
            "utcUnchanged": True,
            "detachRestoresWindowsAPIs": True,
        }
    )

# Exercise two real sessions together: restoring one app must not restore the
# other app's selected zone. Each probe calls the actual Windows APIs.
processes = []
controllers = []
try:
    for profile, zone in [("feishu", "Asia/Shanghai"), ("weixin", "America/Phoenix")]:
        process = subprocess.Popen(
            [sys._base_executable, "-u", str(root / "clock_probe.py")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        original = json.loads(process.stdout.readline())
        processes.append((process, original))
        controller = Controller(zone_config(zone), report=lambda event: None, profile=profile)
        controllers.append(controller)
        controller.attach(process.pid, gate_children=False)
    for (process, _), zone in zip(processes, ["Asia/Shanghai", "America/Phoenix"]):
        process.stdin.write("sample\n")
        process.stdin.flush()
        assert json.loads(process.stdout.readline())["key"] == ZONES[zone]
    controllers[0].close()
    for (process, _), expected in zip(
        processes, [processes[0][1]["key"], ZONES["America/Phoenix"]]
    ):
        process.stdin.write("sample\n")
        process.stdin.flush()
        assert json.loads(process.stdout.readline())["key"] == expected
    results.append({"dualSessions": True, "differentZones": True, "independentRecovery": True})
finally:
    for controller in controllers:
        controller.close()
    for process, _ in processes:
        process.stdin.write("quit\n")
        process.stdin.flush()
        process.wait(timeout=5)

print(json.dumps({"tests": results, "passed": len(results)}, indent=2))
