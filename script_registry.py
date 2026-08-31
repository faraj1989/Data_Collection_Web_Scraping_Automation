"""Single source of truth for "what scripts exist in this project" and how to
launch/detect them - no UI framework dependency.

Extracted from the now-deleted Tkinter control_panel.py so that
service_watchdog.py, scheduler_tasks.py, and the dashboard can all share one
definition without pulling in Settings-form/UI concerns they don't need.
"""
import os
import subprocess
import sys
from pathlib import Path

import psutil

from project_config import PROJECT_ROOT

VENV_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
VENV_PYTHONW = PROJECT_ROOT / ".venv" / "Scripts" / "pythonw.exe"
PYTHON_EXE = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
PYTHONW_EXE = str(VENV_PYTHONW) if VENV_PYTHONW.exists() else PYTHON_EXE
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

# ============================================================
# SCRIPT REGISTRY - single source of truth for every runnable script.
# "continuous"  -> meant to stay running; service_watchdog.py relaunches these.
# "on_demand"   -> fire, forget, no status tracking.
# ============================================================
SCRIPT_REGISTRY = [
    {"name": "MAE Scraper", "file": "scrapers/mae_scraper.py", "mode": "continuous",
     "desc": "Exports MAE Current Alarms", "required_env": ("MAE_URL", "MAE_USERNAME", "MAE_PASSWORD")},
    {"name": "MAE Historical Alarms Scraper", "file": "scrapers/mae_historical_alarms_scraper.py", "mode": "continuous",
     "desc": "Keeps the MAE Historical Alarms page open and re-exports every few minutes",
     "required_env": ("MAE_HISTORICAL_URL", "MAE_USERNAME", "MAE_PASSWORD")},
    {"name": "NetEco Scraper", "file": "scrapers/neteco_scraper.py", "mode": "continuous",
     "desc": "Exports NetEco Current Alarms (Mains/ATS filtered)",
     "required_env": ("NETECO_URL", "NETECO_USERNAME", "NETECO_PASSWORD")},
    {"name": "NetEco All Alarms Scraper", "file": "scrapers/neteco_all_alarms_scraper.py", "mode": "continuous",
     "desc": "Exports NetEco All Current Alarms (LLVD/BLVD/battery evidence)",
     "required_env": ("NETECO_URL", "NETECO_USERNAME", "NETECO_PASSWORD")},
    {"name": "NetEco Historical Alarms Scraper", "file": "scrapers/neteco_historical_alarms_scraper.py", "mode": "continuous",
     "desc": "Keeps the NetEco Historical Alarms page open and re-exports every few minutes",
     "required_env": ("NETECO_HISTORICAL_ALARMS_URL", "NETECO_URL", "NETECO_USERNAME", "NETECO_PASSWORD")},
    {"name": "NCE Active Alarms Scraper", "file": "scrapers/nce_active_alarms_scraper.py", "mode": "continuous",
     "desc": "Exports NCE Active (Current) Alarms", "required_env": ("NCE_USERNAME", "NCE_PASSWORD")},
    {"name": "NCE Historical Alarms Scraper", "file": "scrapers/nce_historical_alarms_scraper.py", "mode": "continuous",
     "desc": "Keeps the NCE Historical Alarms page open and re-exports every few minutes",
     "required_env": ("NCE_USERNAME", "NCE_PASSWORD")},
    {"name": "Main ISP State", "file": "scrapers/main_isp_state_scraper.py", "mode": "continuous",
     "desc": "Exports NCE U2000 Performance Instance data for the ISP group (Webswing-driven; see file docstring)",
     "required_env": ("NCE_USERNAME", "NCE_PASSWORD")},
    {"name": "Merge Reports", "file": "processing/merge_noc_reports.py", "mode": "continuous",
     "desc": "Merges MAE + NetEco reports", "required_env": ("NOC_BASE_DIR", "NOC_SHARED_FOLDER")},
    {"name": "Enhanced NOC Analysis", "file": "processing/enhanced_noc_analysis.py", "mode": "continuous",
     "desc": "Merges MAE + NetEco + All Alarms into P1/P2/P3 site triage", "required_env": ("NOC_BASE_DIR",)},
    {"name": "Historical NOC Analysis", "file": "processing/historical_noc_analysis.py", "mode": "continuous",
     "desc": "Builds chronic-offender / trend insights from MAE + NetEco historical alarm exports",
     "required_env": ("MAE_HISTORICAL_EXPORT_BASE_DIR", "NETECO_HISTORICAL_EXPORT_BASE_DIR")},
    {"name": "Telegram NOC Bot", "file": "bots/telegram_noc_bot.py", "mode": "continuous",
     "desc": "Telegram NOC Bot for alarms", "required_env": ("TELEGRAM_BOT_TOKEN", "NOC_BASE_DIR")},
    {"name": "SmartCare CEM", "file": "scrapers/SmartCare CEM scraper  v11.py", "mode": "on_demand",
     "desc": "SmartCare CEM export only (no analysis step)",
     "required_env": ("SMARTCARE_LOGIN_URL", "SMARTCARE_USERNAME", "SMARTCARE_PASSWORD")},
    {"name": "Comprehensive Analysis", "file": "reports/download_analysis_pipeline.py", "mode": "on_demand",
     "desc": "Re-analyzes existing SmartCare exports into the historical workbook (no new download)",
     "required_env": ()},
    {"name": "SmartCare CEM + Analysis", "file": "reports/run_smartcare_analysis_task.py", "mode": "on_demand",
     "desc": "Recovers any old unprocessed SmartCare exports and folds everything into the "
             "historical workbook - no download step (run SmartCare CEM separately first)",
     "required_env": ()},
    {"name": "Weekly Device Penetration", "file": "scrapers/weekly_device_penetration_scraper.py", "mode": "on_demand",
     "desc": "Weekly Device Penetration Rate export (same SmartCare portal/login, different dashboard)",
     "required_env": ("SMARTCARE_LOGIN_URL", "SMARTCARE_USERNAME", "SMARTCARE_PASSWORD")},
    {"name": "PS Traffic Per Site", "file": "reports/ps_traffic_report.py", "mode": "on_demand",
     "desc": "PS Traffic per site report", "required_env": ("PS_TRAFFIC_SOURCE_DIR",)},
    {"name": "Subscribers Report", "file": "reports/subscriber_reports.py", "mode": "on_demand",
     "desc": "Subscribers + 2G interference + weekly backup report",
     "required_env": ("FTP_HOST", "FTP_USERNAME", "FTP_PASSWORD")},
    {"name": "Cleanup Historical Exports", "file": "tools/cleanup_historical_exports.py", "mode": "on_demand",
     "desc": "Deletes raw historical alarm exports older than the retention window", "required_env": ()},
]
SCRIPT_BY_NAME = {entry["name"]: entry for entry in SCRIPT_REGISTRY}
CONTINUOUS_SCRIPTS = [entry for entry in SCRIPT_REGISTRY if entry["mode"] == "continuous"]
ON_DEMAND_SCRIPTS = [entry for entry in SCRIPT_REGISTRY if entry["mode"] == "on_demand"]

# Old dated/renamed filenames still occasionally left in a .env from before the
# stable-entry-point wrappers existed; keep resolving them to the new names.
LEGACY_ENTRY_POINTS = {
    "mae_scraper_newerBrowserversion149.py": "scrapers/mae_scraper.py",
    "neteco_continuous 15-5-2026.py": "scrapers/neteco_scraper.py",
    "neteco_continuous all alrams.py": "scrapers/neteco_all_alarms_scraper.py",
    "Processing & Merging Script 31-5 with sharing.py": "processing/merge_noc_reports.py",
    "subscriers with 2G interference with ftp andd weekly backup report 3-8-2026.py": "reports/subscriber_reports.py",
    "PS Traffic per site/PS Traffic per site v3 .py": "reports/ps_traffic_report.py",
    # Pre-reorg flat names (before scripts moved into function folders)
    "mae_scraper.py": "scrapers/mae_scraper.py",
    "neteco_scraper.py": "scrapers/neteco_scraper.py",
    "neteco_all_alarms_scraper.py": "scrapers/neteco_all_alarms_scraper.py",
    "merge_noc_reports.py": "processing/merge_noc_reports.py",
    "enhanced_noc_analysis.py": "processing/enhanced_noc_analysis.py",
    "telegram_noc_bot.py": "bots/telegram_noc_bot.py",
    "SmartCare CEM/SmartCare CEM v11.py": "scrapers/SmartCare CEM scraper  v11.py",
    "reports/SmartCare CEM v11.py": "scrapers/SmartCare CEM scraper  v11.py",
    "download_analysis_pipeline.py": "reports/download_analysis_pipeline.py",
    "ps_traffic_report.py": "reports/ps_traffic_report.py",
    "subscriber_reports.py": "reports/subscriber_reports.py",
    "run_smartcare_analysis_task.py": "reports/run_smartcare_analysis_task.py",
}


def resolve_script_path(script_name):
    entry = SCRIPT_BY_NAME.get(script_name)
    if not entry:
        return None
    raw_path = (entry["file"] or "").replace("\\", "/")
    raw_path = LEGACY_ENTRY_POINTS.get(raw_path, raw_path)
    path = Path(raw_path.strip())
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def is_process_running(script_file):
    """Match by filename substring in cmdline.

    script_file entries use forward slashes (e.g. "scrapers/x.py") but a real
    Windows process cmdline joins path parts with backslashes, so both sides
    are normalized to forward slashes before comparing - otherwise the
    substring check never matches and every script looks "not running" even
    when it is, which would make the watchdog relaunch duplicates forever.
    """
    target = script_file.replace("\\", "/")
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = " ".join(proc.info["cmdline"] or [])
            normalized_cmdline = cmdline.replace("\\", "/")
            if target in normalized_cmdline and "python" in cmdline.lower():
                return proc.info["pid"]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def launch_detached(entry, extra_env=None):
    """Start a registry entry as a detached background process with its own
    log file under logs/. Returns the Popen handle, or None if the script
    file doesn't exist."""
    script_path = resolve_script_path(entry["name"])
    if not script_path or not script_path.exists():
        return None

    child_env = os.environ.copy()
    child_env["PYTHONUTF8"] = "1"
    child_env["PYTHONIOENCODING"] = "utf-8"
    child_env["PYTHONUNBUFFERED"] = "1"
    if extra_env:
        child_env.update(extra_env)

    from datetime import datetime
    log_file = LOG_DIR / f"{entry['name'].replace(' ', '_')}_{datetime.now():%Y%m%d_%H%M%S}.log"
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    with open(log_file, "w", encoding="utf-8", errors="replace") as f:
        f.write(f"=== {entry['name']} started at {datetime.now()} ===\nScript: {script_path}\n{'=' * 60}\n\n")
        f.flush()
        proc = subprocess.Popen(
            [PYTHON_EXE, str(script_path)], cwd=str(PROJECT_ROOT),
            stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            env=child_env, creationflags=creationflags, start_new_session=True,
        )
    return proc


def stop_process(pid):
    """Terminate a process and any children it spawned (e.g. chromedriver.exe
    under a Selenium scraper) - psutil.Process.terminate() alone only signals
    the parent, and Selenium's driver.quit() cleanup never runs on a hard
    TerminateProcess, so child processes would otherwise be orphaned."""
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    children = parent.children(recursive=True)
    for child in children:
        try:
            child.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    try:
        parent.terminate()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    _, alive = psutil.wait_procs([parent, *children], timeout=5)
    for proc in alive:
        try:
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
