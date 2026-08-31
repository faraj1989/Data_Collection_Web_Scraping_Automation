"""Headless watchdog that keeps the continuous automation scripts running.

This has no window and needs no interaction: point Windows Task Scheduler or
the Startup folder at it once (see "Start Automation Watchdog.bat") and it
checks every CHECK_INTERVAL_SECONDS whether each managed script is alive,
relaunching any that crashed or were never started - forever, until the
machine reboots or the watchdog process itself is stopped.

The set of managed scripts comes from script_registry.py's SCRIPT_REGISTRY
(the single source of truth for "what scripts exist in this project"), so the
watchdog can never drift out of sync with what the rest of the tooling manages.
"""
import os
import subprocess
import sys
import time
from datetime import datetime

from script_registry import (
    CONTINUOUS_SCRIPTS,
    LOG_DIR,
    PROJECT_ROOT,
    PYTHON_EXE,
    is_process_running,
    resolve_script_path,
)

CHECK_INTERVAL_SECONDS = 60


def log(message):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}", flush=True)


def start(entry):
    script_path = resolve_script_path(entry["name"])
    if not script_path or not script_path.exists():
        log(f"ERROR: script not found, skipping: {entry['name']} ({script_path})")
        return

    log_file = LOG_DIR / f"{entry['name'].replace(' ', '_')}_{datetime.now():%Y%m%d_%H%M%S}.log"
    child_env = os.environ.copy()
    child_env["PYTHONUTF8"] = "1"
    child_env["PYTHONIOENCODING"] = "utf-8"
    child_env["PYTHONUNBUFFERED"] = "1"

    with open(log_file, "w", encoding="utf-8", errors="replace") as f:
        f.write(f"=== {entry['name']} started by watchdog at {datetime.now()} ===\n")
        f.write(f"Script: {script_path}\n{'=' * 60}\n\n")
        f.flush()
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        subprocess.Popen(
            [PYTHON_EXE, str(script_path)],
            cwd=str(PROJECT_ROOT),
            stdout=f,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=child_env,
            creationflags=creationflags,
            start_new_session=True,
        )
    log(f"Started {entry['name']} (log: {log_file.name})")


def main():
    log("Watchdog starting. Managing: " + ", ".join(e["name"] for e in CONTINUOUS_SCRIPTS))
    log(f"Check interval: {CHECK_INTERVAL_SECONDS}s")
    while True:
        for entry in CONTINUOUS_SCRIPTS:
            if is_process_running(entry["file"]):
                continue
            log(f"{entry['name']} is not running - starting it.")
            start(entry)
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
