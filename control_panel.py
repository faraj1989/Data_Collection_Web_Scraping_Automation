"""Unified control panel: project settings + service start/stop/status + one-off runs.

Replaces orchestrator_gui.py and project_settings_gui.py, which each kept
their own separate, hand-maintained list of "what scripts exist in this
project" - those lists drifted out of sync more than once. SCRIPT_REGISTRY
below is now the single source of truth for both the Settings tabs and the
Services/Run Once tabs.
"""
import os
import socket
import ssl
import subprocess
import sys
import threading
import traceback
import zipfile
import logging
import tkinter as tk
from datetime import datetime, timedelta
from ftplib import FTP_TLS
from pathlib import Path
from tkinter import filedialog, messagebox, ttk, scrolledtext
    
import paramiko
import psutil

from project_config import ENV_PATH, PROJECT_ROOT, load_env_file, parse_env_file

logger = logging.getLogger(__name__)

VENV_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
PYTHON_EXE = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)


# =============================================================
# SFTP HANDLER (connectivity test only)
# =============================================================
def safe_extract_zip(archive: zipfile.ZipFile, destination: Path) -> None:
    """Extract only members whose resolved paths stay inside destination."""
    destination = destination.resolve()
    for member in archive.infolist():
        target = (destination / member.filename).resolve()
        if target != destination and destination not in target.parents:
            raise ValueError(f"Unsafe ZIP member path: {member.filename}")
    archive.extractall(destination)


class SFTPDownload:
    """SFTP download handler using paramiko."""

    def __init__(self, host, port, username, password, remote_path, timeout=30):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.remote_path = remote_path
        self.timeout = timeout
        self.sftp = None
        self.transport = None

    def connect(self):
        try:
            self.transport = paramiko.Transport((self.host, self.port))
            self.transport.connect(username=self.username, password=self.password)
            self.sftp = paramiko.SFTPClient.from_transport(self.transport)
            self.sftp.chdir(self.remote_path)
            logger.info(f"SFTP connected to {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"SFTP connection failed: {e}")
            raise

    def list_files(self, pattern=None):
        try:
            files = self.sftp.listdir()
            if pattern:
                import fnmatch
                files = [f for f in files if fnmatch.fnmatch(f, pattern)]
            return files
        except Exception as e:
            logger.error(f"Failed to list files: {e}")
            raise

    def download_and_extract_zip(self, remote_filename, extract_to):
        temp_dir = Path(extract_to) / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        zip_path = temp_dir / remote_filename
        self.sftp.get(remote_filename, str(zip_path))
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            safe_extract_zip(zip_ref, Path(extract_to))
        os.remove(zip_path)
        logger.info(f"Extracted: {remote_filename} to {extract_to}")
        return extract_to

    def close(self):
        if self.sftp:
            self.sftp.close()
        if self.transport:
            self.transport.close()
        logger.info("SFTP connection closed")


# =============================================================
# CENTRALIZED DATA ROOT
# =============================================================
DEFAULT_DATA_ROOT = str(Path.home() / "Desktop" / "Libyana_Data")


def data_path(subfolder: str) -> str:
    return str(Path(DEFAULT_DATA_ROOT) / subfolder)


# ============================================================
# SETTINGS DEFINITION (.env fields, grouped into sections/tabs)
# ============================================================
SETTINGS = [
    {
        "section": "Data Management",
        "fields": [
            ("DATA_ROOT", "Central Data Root Folder (all data stored here)", DEFAULT_DATA_ROOT, "dir", False),
        ],
    },
    {
        "section": "NOC Reports",
        "fields": [
            ("NOC_BASE_DIR", "Current alarms base folder", data_path("Output/Current_Alarms"), "dir", False),
            ("NOC_SHARED_FOLDER", "Shared report folder", data_path("Output/Current_Alarms/Shared Current Alarms"),
             "dir", False),
            ("MERGE_INTERVAL_SECONDS", "Merge interval seconds", "600", "text", False),
            ("NOC_ANALYSIS_INTERVAL_SECONDS", "Enhanced NOC analysis interval seconds", "300", "text", False),
        ],
    },
    {
        "section": "MAE Scraper",
        "fields": [
            ("MAE_URL", "MAE URL", "", "text", False),
            ("MAE_USERNAME", "MAE username", "", "text", False),
            ("MAE_PASSWORD", "MAE password", "", "text", True),
            ("MAE_DOWNLOAD_DIR", "MAE download folder", data_path("Input/Downloads"), "dir", False),
            ("MAE_EXPORT_BASE_DIR", "MAE export base folder", data_path("Output/Current_Alarms"), "dir", False),
            ("MAE_WAIT_TIMEOUT", "MAE wait timeout seconds", "45", "text", False),
            ("MAE_INTERVAL_SECONDS", "MAE interval seconds", "300", "text", False),
            ("MAE_HISTORICAL_URL", "MAE Historical Alarms URL (last 7 days)",
             "https://10.171.68.68:31943/ossfacewebsite/index.html#Access/fmHistoryAlarm@@fmAlarmApp_historyAlarm_templateId143%26tabTitle%3DHistorical%20Alarms%20MAE%20last%207days?maeUrl=%2Feviewwebsite%2Findex.html%23path%3D%2FfmAlarmApp%2FfmHistoryAlarm%26templateId%3D143%26fmPage%3Dtrue%26_t%3D1787561843039&maeTitle=Historical%20Alarms%20-%20%5BHistorical%20Alarms%20MAE%20last%207days%5D&loadType=iframe",
             "text", False),
            ("MAE_HISTORICAL_EXPORT_BASE_DIR", "MAE Historical Alarms export folder",
             data_path("Output/Historical_Alarms"), "dir", False),
            ("MAE_HISTORICAL_DOWNLOAD_TIMEOUT", "MAE Historical download timeout seconds", "600", "text", False),
            ("MAE_HISTORICAL_INTERVAL_SECONDS", "MAE Historical re-export interval seconds", "300", "text", False),
        ],
    },
    {
        "section": "NetEco Scraper",
        "fields": [
            ("NETECO_URL", "NetEco URL", "", "text", False),
            ("NETECO_ALL_CURRENT_ALARMS_URL", "NetEco All Current Alarms URL (dual-tab scraper, templateId=120)",
             "https://10.171.68.2:31943/eviewwebsite/index.html#path=/fmAlarmApp/fmAlarmView&templateId=120&fmPage=true&_t=1787017955421",
             "text", False),
            ("NETECO_ALL_ALARMS_URL", "NetEco All Alarms URL (all-alarms scraper, templateId=149)",
             "https://10.171.68.2:31943/eviewwebsite/index.html#path=/fmAlarmApp/fmAlarmView&templateId=149&fmPage=true&_t=1787140556610",
             "text", False),
            ("NETECO_USERNAME", "NetEco username", "", "text", False),
            ("NETECO_PASSWORD", "NetEco password", "", "text", True),
            ("NETECO_DOWNLOAD_DIR", "NetEco download folder", data_path("Input/Downloads"), "dir", False),
            ("NETECO_EXPORT_BASE_DIR", "NetEco export base folder", data_path("Output/Current_Alarms"), "dir",
             False),
            ("NETECO_WAIT_TIMEOUT", "NetEco wait timeout seconds", "60", "text", False),
            ("NETECO_INTERVAL_SECONDS", "NetEco interval seconds", "300", "text", False),
            ("NETECO_DOWNLOAD_TIMEOUT_SECONDS", "Download timeout seconds", "180", "text", False),
            ("NETECO_DOWNLOAD_STABLE_SECONDS", "Download stable seconds", "5", "text", False),
            ("NETECO_RETRY_DELAY_SECONDS", "Retry delay seconds", "60", "text", False),
            ("NETECO_MAX_CONSECUTIVE_FAILURES", "Max consecutive failures", "5", "text", False),
            ("NETECO_PORT_CHECK_TIMEOUT", "Port check timeout seconds", "5", "text", False),
        ],
    },
    {
        "section": "SmartCare CEM",
        "fields": [
            ("SMARTCARE_LOGIN_URL", "SmartCare login URL", "", "text", False),
            ("SMARTCARE_USERNAME", "SmartCare username", "", "text", False),
            ("SMARTCARE_PASSWORD", "SmartCare password", "", "text", True),
            ("SMARTCARE_TARGET_DASHBOARD_URL", "SmartCare target dashboard URL", "", "text", False),
            ("SMARTCARE_EXPORT_TASK_URL", "SmartCare export task URL", "", "text", False),
            ("SMARTCARE_DOWNLOAD_DIR", "SmartCare download folder", data_path("Input/Downloads"), "dir", False),
            ("SMARTCARE_OUTPUT_DIR", "SmartCare output folder", data_path("Output/SmartCare_Exports"), "dir", False),
            ("SMARTCARE_EXPORT_BASE_DIR", "SmartCare export base folder", data_path("Output/Current_Alarms"), "dir",
             False),
            ("SMARTCARE_EXPORT_TASK_TIMEOUT", "SmartCare export task timeout seconds", "300", "text", False),
            ("SMARTCARE_POLL_INTERVAL", "SmartCare poll interval seconds", "15", "text", False),
        ],
    },
    {
        "section": "Logging",
        "fields": [
            ("PROJECT_LOG_DIR", "Project log folder", data_path("logs"), "dir", False),
        ],
    },
    {
        "section": "Analysis",
        "fields": [
            ("ANALYSIS_SOURCE_DIR", "Analysis source folder", data_path("Output/SmartCare_Exports"), "dir", False),
            ("ANALYSIS_OUTPUT_DIR", "Analysis output folder", data_path("Output/Processed_Analysis"), "dir", False),
            ("ANALYSIS_HISTORY_FILE", "Analysis history file",
             data_path("Output/Processed_Analysis/Comprehensive_Analysis_Historical.xlsx"), "file", False),
        ],
    },
    {
        "section": "FTP/SFTP Configuration",
        "fields": [
            ("FTP_PROTOCOL", "Protocol (FTPS or SFTP)", "SFTP", "text", False),
            ("FTP_HOST", "Server host", "", "text", False),
            ("FTP_PORT", "Server port", "22", "text", False),
            ("FTP_USERNAME", "Username", "", "text", False),
            ("FTP_PASSWORD", "Password", "", "text", True),
            ("FTP_REMOTE_PATH", "Remote path", "/", "text", False),
            ("FTP_FILE_PATTERN", "File pattern", "*.zip", "text", False),
            ("FTP_TIMEOUT_SECONDS", "Timeout seconds", "30", "text", False),
            ("FTP_PASSIVE", "Use passive mode (FTPS only)", "True", "text", False),
            ("FTP_IGNORE_CERT", "Ignore SSL certificate (FTPS only)", "False", "text", False),
        ],
    },
    {
        "section": "Monthly Interference",
        "fields": [
            ("INTERFERENCE_FTP_ROOT", "Interference FTP root", "/ftproot/New", "text", False),
            ("INTERFERENCE_2G_FILENAME_PREFIX", "2G filename start", "2G Monthly HQ interference_", "text", False),
            ("INTERFERENCE_3G_FILENAME_TOKEN", "3G filename contains", "(3g)", "text", False),
            ("INTERFERENCE_4G_FILENAME_TOKEN", "4G filename contains", "(4g)", "text", False),
            ("INTERFERENCE_FILE_TYPE", "Interference file type", ".csv", "text", False),
            ("INTERFERENCE_OUTPUT_DIR", "Interference output folder",
             data_path("Output/Subscribers/Interference_Output"), "dir", False),
        ],
    },
    {
        "section": "PS Traffic per site",
        "fields": [
            ("PS_TRAFFIC_FTP_PREFIX", "PS Traffic ZIP prefix", "PS Daily Traffic_2G_3G_4G_", "text", False),
            ("PS_TRAFFIC_SOURCE_DIR", "PS Traffic source folder", data_path("Input/FTP_RawData"), "dir", False),
            ("PS_TRAFFIC_OUTPUT_DIR", "PS Traffic output folder", data_path("Output/PS_Traffic_Output"), "dir",
             False),
            ("PS_TRAFFIC_FILE_2G_TOKEN", "2G CSV token", "(PS Traffic 2G)", "text", False),
            ("PS_TRAFFIC_FILE_3G_TOKEN", "3G CSV token", "(PS Traffic 3G)", "text", False),
            ("PS_TRAFFIC_FILE_4G_TOKEN", "4G CSV token", "(PS Traffic 4G)", "text", False),
        ],
    },
    {
        "section": "Subscribers Calculation",
        "fields": [
            ("SUBSCRIBERS_INPUT_DIR", "Subscriber input folder", data_path("Input/FTP_RawData"), "dir", False),
            ("SUBSCRIBERS_OUTPUT_DIR", "Subscriber calculation output folder",
             data_path("Output/Subscribers/Subscribers_Output"), "dir", False),
            ("SUBSCRIBERS_HISTORY_FILE", "Subscriber history file",
             data_path("Output/Subscribers/Subscribers_History.xlsx"), "file", False),
        ],
    },
    {
        "section": "Telegram Bot",
        "fields": [
            ("TELEGRAM_BOT_TOKEN", "Telegram bot token", "", "text", True),
        ],
    },
]

# ============================================================
# SCRIPT REGISTRY - single source of truth for every runnable script.
# "continuous"  -> managed on the Services tab (start/stop/status, meant to
#                  stay running; service_watchdog.py may also relaunch these).
# "on_demand"   -> managed on the Run Once tab (fire, forget, no status).
# ============================================================
SCRIPT_REGISTRY = [
    {"name": "MAE Scraper", "file": "scrapers/mae_scraper.py", "mode": "continuous",
     "desc": "Exports MAE Current Alarms", "required_env": ("MAE_URL", "MAE_USERNAME", "MAE_PASSWORD")},
    {"name": "MAE Historical Alarms Scraper", "file": "scrapers/mae_historical_alarms_scraper.py", "mode": "continuous",
     "desc": "Keeps the MAE Historical Alarms (last 7 days) page open and re-exports every few minutes",
     "required_env": ("MAE_HISTORICAL_URL", "MAE_USERNAME", "MAE_PASSWORD")},
    {"name": "NetEco Scraper", "file": "scrapers/neteco_scraper.py", "mode": "continuous",
     "desc": "Exports NetEco Current Alarms (Mains/ATS filtered)",
     "required_env": ("NETECO_URL", "NETECO_USERNAME", "NETECO_PASSWORD")},
    {"name": "NetEco All Alarms Scraper", "file": "scrapers/neteco_all_alarms_scraper.py", "mode": "continuous",
     "desc": "Exports NetEco All Current Alarms (LLVD/BLVD/battery evidence)",
     "required_env": ("NETECO_URL", "NETECO_USERNAME", "NETECO_PASSWORD")},
    {"name": "Merge Reports", "file": "processing/merge_noc_reports.py", "mode": "continuous",
     "desc": "Merges MAE + NetEco reports", "required_env": ("NOC_BASE_DIR", "NOC_SHARED_FOLDER")},
    {"name": "Enhanced NOC Analysis", "file": "processing/enhanced_noc_analysis.py", "mode": "continuous",
     "desc": "Merges MAE + NetEco + All Alarms into P1/P2/P3 site triage", "required_env": ("NOC_BASE_DIR",)},
    {"name": "Telegram NOC Bot", "file": "bots/telegram_noc_bot.py", "mode": "continuous",
     "desc": "Telegram NOC Bot for alarms", "required_env": ("TELEGRAM_BOT_TOKEN", "NOC_BASE_DIR")},
    {"name": "SmartCare CEM", "file": "reports/SmartCare CEM v11.py", "mode": "on_demand",
     "desc": "SmartCare CEM export + KPI scraping",
     "required_env": ("SMARTCARE_LOGIN_URL", "SMARTCARE_USERNAME", "SMARTCARE_PASSWORD")},
    {"name": "Comprehensive Analysis", "file": "reports/download_analysis_pipeline.py", "mode": "on_demand",
     "desc": "Builds the Comprehensive Analysis workbook from the latest SmartCare export", "required_env": ()},
    {"name": "PS Traffic Per Site", "file": "reports/ps_traffic_report.py", "mode": "on_demand",
     "desc": "PS Traffic per site report", "required_env": ("PS_TRAFFIC_SOURCE_DIR",)},
    {"name": "Subscribers Report", "file": "reports/subscriber_reports.py", "mode": "on_demand",
     "desc": "Subscribers + 2G interference + weekly backup report",
     "required_env": ("FTP_HOST", "FTP_USERNAME", "FTP_PASSWORD")},
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
    "SmartCare CEM/SmartCare CEM v11.py": "reports/SmartCare CEM v11.py",
    "download_analysis_pipeline.py": "reports/download_analysis_pipeline.py",
    "ps_traffic_report.py": "reports/ps_traffic_report.py",
    "subscriber_reports.py": "reports/subscriber_reports.py",
    "run_smartcare_analysis_task.py": "reports/run_smartcare_analysis_task.py",
}

INTEGER_FIELDS = {
    "MERGE_INTERVAL_SECONDS", "NOC_ANALYSIS_INTERVAL_SECONDS",
    "MAE_WAIT_TIMEOUT", "MAE_INTERVAL_SECONDS", "MAE_HISTORICAL_DOWNLOAD_TIMEOUT", "MAE_HISTORICAL_INTERVAL_SECONDS",
    "SMARTCARE_EXPORT_TASK_TIMEOUT", "SMARTCARE_POLL_INTERVAL",
    "NETECO_WAIT_TIMEOUT", "NETECO_INTERVAL_SECONDS", "NETECO_DOWNLOAD_TIMEOUT_SECONDS",
    "NETECO_DOWNLOAD_STABLE_SECONDS", "NETECO_RETRY_DELAY_SECONDS", "NETECO_MAX_CONSECUTIVE_FAILURES",
    "NETECO_PORT_CHECK_TIMEOUT", "FTP_PORT", "FTP_TIMEOUT_SECONDS",
}


# ---------- Utility functions ----------
def read_env_file():
    load_env_file()
    values = parse_env_file()
    for section in SETTINGS:
        for key, _, default, _, _ in section["fields"]:
            values.setdefault(key, os.getenv(key, default))
    return values


def quote_env_value(value):
    value = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{value}"'


def resolve_script_path(script_name, values=None):
    entry = SCRIPT_BY_NAME.get(script_name)
    if not entry:
        return None
    raw_path = (entry["file"] or "").replace("\\", "/")
    raw_path = LEGACY_ENTRY_POINTS.get(raw_path, raw_path)
    path = Path(raw_path.strip())
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def run_attrib(*attributes):
    subprocess.run(
        ["attrib", *attributes, str(ENV_PATH)],
        check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def hide_env_file():
    if os.name == "nt" and ENV_PATH.exists():
        run_attrib("+h")


def prepare_env_file_for_write():
    if os.name == "nt" and ENV_PATH.exists():
        run_attrib("-h", "-r")


def is_process_running(script_file):
    """Match by filename substring in cmdline, same convention as
    service_watchdog.py, so both tools agree on what's "running".

    script_file entries use forward slashes (e.g. "scrapers/x.py") but a real
    Windows process cmdline joins path parts with backslashes, so both sides
    are normalized to forward slashes before comparing - otherwise the
    substring check never matches and every script looks "not running" even
    when it is, which used to make the watchdog relaunch duplicates forever.
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


# ---------- Main GUI ----------
class ControlPanel(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Libyana Automation Control Panel")
        self.geometry("1100x850")
        self.minsize(950, 700)
        self.variables = {}
        self.show_secrets = tk.BooleanVar(value=False)
        self.ftp_status_label = None
        self.log_text = None
        self.services_tree = None
        self.run_once_choice = tk.StringVar(value=ON_DEMAND_SCRIPTS[0]["name"] if ON_DEMAND_SCRIPTS else "")

        self._build_ui()
        self.load_values()
        self.refresh_services()

    # ---------------- UI construction ----------------
    def _build_ui(self):
        header = ttk.Frame(self, padding=(14, 12))
        header.pack(fill="x")
        ttk.Label(header, text="Automation Control Panel", font=("Segoe UI", 16, "bold")).pack(side="left")
        ttk.Label(header, text=f"Settings file: {ENV_PATH}", foreground="#555").pack(side="right")

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        tabs = {
            "Services": ttk.Frame(self.notebook),
            "Run Once": ttk.Frame(self.notebook),
            "General": ttk.Frame(self.notebook),
            "Scrapers": ttk.Frame(self.notebook),
            "SmartCare & Analysis": ttk.Frame(self.notebook),
            "Subscribers": ttk.Frame(self.notebook),
        }
        for tab_name, frame in tabs.items():
            self.notebook.add(frame, text=tab_name)
        self.tabs = tabs

        self._build_services_tab(tabs["Services"])
        self._build_run_once_tab(tabs["Run Once"])
        self._build_settings_tabs(tabs)

        # Bottom controls, always visible regardless of tab
        control_frame = ttk.Frame(self)
        control_frame.pack(fill="x", padx=14, pady=(0, 10))
        ttk.Checkbutton(
            control_frame, text="Show passwords/tokens",
            variable=self.show_secrets, command=self.toggle_secret_visibility,
        ).pack(side="left")
        ttk.Button(control_frame, text="Reload", command=self.load_values).pack(side="right", padx=(8, 0))
        ttk.Button(control_frame, text="Save Settings", command=self.save_values).pack(side="right", padx=(8, 0))
        ttk.Button(control_frame, text="\U0001f4be Save & Reload Env", command=self.save_and_reload).pack(
            side="right", padx=(8, 0))

    def _build_settings_tabs(self, tabs):
        section_tab = {
            "Data Management": "General",
            "NOC Reports": "General",
            "Logging": "General",
            "Telegram Bot": "General",
            "MAE Scraper": "Scrapers",
            "NetEco Scraper": "Scrapers",
            "SmartCare CEM": "SmartCare & Analysis",
            "Analysis": "SmartCare & Analysis",
            "FTP/SFTP Configuration": "Subscribers",
            "Monthly Interference": "Subscribers",
            "PS Traffic per site": "Subscribers",
            "Subscribers Calculation": "Subscribers",
        }

        for tab_name in ("General", "Scrapers", "SmartCare & Analysis", "Subscribers"):
            tabs[tab_name].columnconfigure(1, weight=1)

        tab_row = {name: 0 for name in tabs}

        for section in SETTINGS:
            tab_name = section_tab.get(section["section"], "General")
            parent = tabs[tab_name]
            row = tab_row[tab_name]

            ttk.Label(parent, text=section["section"], font=("Segoe UI", 12, "bold")).grid(
                row=row, column=0, columnspan=3, sticky="w", pady=(16, 6), padx=(2, 8))
            row += 1

            for key, label_text, _default, field_type, is_secret in section["fields"]:
                ttk.Label(parent, text=label_text).grid(row=row, column=0, sticky="w", padx=(2, 8), pady=3)
                var = tk.StringVar()
                width = 30 if field_type == "text" and "URL" not in key and "PATH" not in key else 80
                entry = ttk.Entry(parent, textvariable=var, width=width, show="*" if is_secret else "")
                entry.grid(row=row, column=1, sticky="ew", pady=3)
                self.variables[key] = (var, entry, is_secret)

                if field_type == "dir":
                    ttk.Button(parent, text="Browse", command=lambda v=var: self.choose_dir(v)).grid(
                        row=row, column=2, padx=(6, 2), pady=3)
                elif field_type == "file":
                    ttk.Button(parent, text="Browse", command=lambda v=var: self.choose_file(v)).grid(
                        row=row, column=2, padx=(6, 2), pady=3)
                row += 1

            tab_row[tab_name] = row

        # Auto-populate / create-directories helpers on General
        general_frame = tabs["General"]
        row = tab_row["General"]
        action_frame = ttk.Frame(general_frame)
        action_frame.grid(row=row, column=0, columnspan=3, sticky="ew", pady=8)
        ttk.Button(action_frame, text="Auto-populate all paths from Data Root",
                   command=self.populate_paths_from_root).pack(side="left")
        ttk.Button(action_frame, text="Create All Directories",
                   command=self.create_all_directories).pack(side="left", padx=8)
        ttk.Label(action_frame, text="Creates all folders defined in settings.",
                  foreground="#555").pack(side="left", padx=8)

        # FTP/SFTP test panel on Subscribers
        subscriber_actions = ttk.Frame(tabs["Subscribers"], padding=(2, 8))
        subscriber_actions.grid(row=tab_row["Subscribers"], column=0, columnspan=3, sticky="ew")
        ttk.Button(subscriber_actions, text="Test FTP/SFTP Connection",
                   command=self.test_ftp_connection).pack(side="left")
        self.ftp_status_label = ttk.Label(subscriber_actions, text="", foreground="#555")
        self.ftp_status_label.pack(side="left", padx=8)

        log_frame = ttk.LabelFrame(tabs["Subscribers"], text="FTP/SFTP Test Log", padding=5)
        log_frame.grid(row=tab_row["Subscribers"] + 1, column=0, columnspan=3, sticky="nsew", pady=8)
        self.log_text = scrolledtext.ScrolledText(log_frame, height=10, width=100, state="normal",
                                                    font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True)
        self.log_text.insert("end", "Ready for FTP/SFTP test...\n")
        self.log_text.config(state="disabled")

    def _build_services_tab(self, parent):
        watchdog_frame = ttk.Frame(parent, padding=(10, 10))
        watchdog_frame.pack(fill="x")
        self.watchdog_status_label = ttk.Label(watchdog_frame, text="Watchdog: checking...", font=("Segoe UI", 10, "bold"))
        self.watchdog_status_label.pack(side="left")
        ttk.Button(watchdog_frame, text="Start Watchdog", command=self.start_watchdog).pack(side="left", padx=(12, 4))
        ttk.Button(watchdog_frame, text="Stop Watchdog", command=self.stop_watchdog).pack(side="left", padx=4)
        ttk.Label(
            watchdog_frame,
            text="If the Watchdog is running, a stopped service below may auto-restart within ~60s.\n"
                 "Stop the Watchdog first if you want a service to stay off.",
            foreground="#555", justify="left",
        ).pack(side="left", padx=12)

        columns = ("status", "name", "pid", "desc")
        self.services_tree = ttk.Treeview(parent, columns=columns, show="headings", height=10)
        self.services_tree.heading("status", text="Status")
        self.services_tree.heading("name", text="Service")
        self.services_tree.heading("pid", text="PID")
        self.services_tree.heading("desc", text="Description")
        self.services_tree.column("status", width=90, anchor="center")
        self.services_tree.column("name", width=220)
        self.services_tree.column("pid", width=80, anchor="center")
        self.services_tree.column("desc", width=520)
        self.services_tree.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        btn_frame = ttk.Frame(parent, padding=(10, 0))
        btn_frame.pack(fill="x")
        ttk.Button(btn_frame, text="▶ Start Selected", command=self.start_selected_service).pack(side="left")
        ttk.Button(btn_frame, text="■ Stop Selected", command=self.stop_selected_service).pack(side="left", padx=6)
        ttk.Button(btn_frame, text="View Latest Log", command=self.view_selected_log).pack(side="left", padx=6)
        ttk.Button(btn_frame, text="▶▶ Start All", command=self.start_all_services).pack(side="left", padx=(20, 6))
        ttk.Button(btn_frame, text="■■ Stop All", command=self.stop_all_services).pack(side="left")
        ttk.Button(btn_frame, text="Refresh", command=self.refresh_services).pack(side="right")

    def _build_run_once_tab(self, parent):
        frame = ttk.Frame(parent, padding=(14, 14))
        frame.pack(fill="x")
        ttk.Label(frame, text="Run a script once (not managed/restarted).", font=("Segoe UI", 10, "bold")).pack(
            anchor="w", pady=(0, 10))

        picker = ttk.Frame(frame)
        picker.pack(fill="x")
        ttk.Combobox(picker, textvariable=self.run_once_choice,
                     values=[e["name"] for e in ON_DEMAND_SCRIPTS], state="readonly", width=32).pack(side="left")
        ttk.Button(picker, text="Run", command=self.run_once_selected).pack(side="left", padx=8)
        ttk.Label(frame, text="Settings are saved before launch.", foreground="#555").pack(anchor="w", pady=(6, 0))

        analysis_frame = ttk.LabelFrame(frame, text="Comprehensive Analysis", padding=10)
        analysis_frame.pack(fill="x", pady=(20, 0))
        ttk.Button(analysis_frame, text="Run Latest Analysis",
                   command=lambda: self.run_once("Comprehensive Analysis")).pack(side="left", padx=4)
        ttk.Button(analysis_frame, text="Run SmartCare + Update History",
                   command=self.run_full_smartcare_analysis).pack(side="left", padx=4)
        ttk.Button(analysis_frame, text="Schedule Sunday 02:00", command=self.schedule_weekly_task).pack(
            side="left", padx=4)
        ttk.Button(analysis_frame, text="Open Output Folder", command=self.open_analysis_output).pack(
            side="left", padx=4)

    # ---------------- Services tab logic ----------------
    def refresh_services(self):
        if self.services_tree is None:
            return
        for item in self.services_tree.get_children():
            self.services_tree.delete(item)
        for entry in CONTINUOUS_SCRIPTS:
            pid = is_process_running(entry["file"])
            status = "✅ Running" if pid else "❌ Stopped"
            self.services_tree.insert("", "end", iid=entry["name"],
                                       values=(status, entry["name"], pid or "-", entry["desc"]))
        watchdog_pid = is_process_running("service_watchdog.py")
        if watchdog_pid:
            self.watchdog_status_label.config(text=f"Watchdog: ✅ Running (PID {watchdog_pid})", foreground="green")
        else:
            self.watchdog_status_label.config(text="Watchdog: ❌ Not running", foreground="red")
        self.after(5000, self.refresh_services)

    def _selected_service_entry(self):
        selection = self.services_tree.selection()
        if not selection:
            messagebox.showinfo("No selection", "Select a service in the list first.")
            return None
        return SCRIPT_BY_NAME.get(selection[0])

    def _launch_detached(self, entry, extra_env=None):
        script_path = resolve_script_path(entry["name"])
        if not script_path or not script_path.exists():
            messagebox.showerror("Script not found", f"{entry['name']}:\n{script_path}")
            return None

        values = self.current_values()
        errors = self.validate_values(entry["name"])
        if errors:
            messagebox.showerror("Missing settings", "\n".join(errors))
            return None

        child_env = os.environ.copy()
        child_env.update(values)
        child_env["PYTHONUTF8"] = "1"
        child_env["PYTHONIOENCODING"] = "utf-8"
        child_env["PYTHONUNBUFFERED"] = "1"
        if extra_env:
            child_env.update(extra_env)

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

    def start_service(self, entry):
        if is_process_running(entry["file"]):
            messagebox.showinfo("Already running", f"{entry['name']} is already running.")
            return
        if not self.save_values(show_message=False):
            return
        proc = self._launch_detached(entry)
        if proc:
            self.after(1500, self.refresh_services)

    def stop_service(self, entry):
        pid = is_process_running(entry["file"])
        if not pid:
            messagebox.showinfo("Not running", f"{entry['name']} is not running.")
            return
        try:
            psutil.Process(pid).terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            messagebox.showerror("Stop failed", f"Could not stop {entry['name']}:\n{exc}")
        self.after(1500, self.refresh_services)

    def start_selected_service(self):
        entry = self._selected_service_entry()
        if entry:
            self.start_service(entry)

    def stop_selected_service(self):
        entry = self._selected_service_entry()
        if entry:
            self.stop_service(entry)

    def start_all_services(self):
        if not self.save_values(show_message=False):
            return
        started = [e["name"] for e in CONTINUOUS_SCRIPTS
                   if not is_process_running(e["file"]) and self._launch_detached(e)]
        self.after(1500, self.refresh_services)
        if started:
            messagebox.showinfo("Started", "Started:\n" + "\n".join(started))

    def stop_all_services(self):
        if not messagebox.askyesno("Stop all", "Stop all running services?"):
            return
        for entry in CONTINUOUS_SCRIPTS:
            pid = is_process_running(entry["file"])
            if pid:
                try:
                    psutil.Process(pid).terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        self.after(1500, self.refresh_services)

    def view_selected_log(self):
        entry = self._selected_service_entry()
        if not entry:
            return
        prefix = entry["name"].replace(" ", "_")
        candidates = sorted(LOG_DIR.glob(f"{prefix}_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            messagebox.showinfo("No log", f"No log file found yet for {entry['name']}.")
            return
        os.startfile(str(candidates[0]))

    def start_watchdog(self):
        if is_process_running("service_watchdog.py"):
            messagebox.showinfo("Already running", "Watchdog is already running.")
            return
        script_path = PROJECT_ROOT / "service_watchdog.py"
        if not script_path.exists():
            messagebox.showerror("Not found", f"service_watchdog.py not found at {script_path}")
            return
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        subprocess.Popen([PYTHON_EXE, str(script_path)], cwd=str(PROJECT_ROOT), env=env,
                          creationflags=creationflags, start_new_session=True,
                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.after(1500, self.refresh_services)

    def stop_watchdog(self):
        pid = is_process_running("service_watchdog.py")
        if not pid:
            messagebox.showinfo("Not running", "Watchdog is not running.")
            return
        try:
            psutil.Process(pid).terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            messagebox.showerror("Stop failed", f"Could not stop watchdog:\n{exc}")
        self.after(1500, self.refresh_services)

    # ---------------- Run Once tab logic ----------------
    def run_once(self, script_name):
        entry = SCRIPT_BY_NAME.get(script_name)
        if not entry:
            return
        if not self.save_values(show_message=False):
            return
        proc = self._launch_detached(entry)
        if proc:
            self.append_log(f"Started (one-off): {script_name}", "green")

    def run_once_selected(self):
        self.run_once(self.run_once_choice.get())

    def run_full_smartcare_analysis(self):
        if not self.save_values(show_message=False):
            return
        wrapper = PROJECT_ROOT / "reports" / "run_smartcare_analysis_task.py"
        if not wrapper.exists():
            messagebox.showerror("SmartCare", f"Wrapper not found:\n{wrapper}")
            return
        env = os.environ.copy()
        env.update(self.current_values())
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        subprocess.Popen([sys.executable, str(wrapper)], cwd=str(PROJECT_ROOT), env=env)
        self.append_log("Started SmartCare + analysis pipeline.", "green")

    def schedule_weekly_task(self):
        messagebox.showinfo("Scheduling", "Use Windows Task Scheduler to run run_smartcare_analysis_task.py weekly.\n"
                            "Automatic task creation is intentionally not performed from this GUI.")

    def open_analysis_output(self):
        if not self.save_values(show_message=False):
            return
        output_dir = Path(self.current_values()["ANALYSIS_OUTPUT_DIR"])
        output_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(str(output_dir))

    # ---------------- Settings tab logic ----------------
    def save_and_reload(self):
        if self.save_values(show_message=True):
            load_env_file(override=True)
            os.environ.update(self.current_values())
            messagebox.showinfo(
                "Reloaded",
                "✅ Environment variables reloaded.\n\n"
                "Already-running scripts keep their old values until restarted."
            )

    def create_all_directories(self):
        self.append_log("=" * 60, "blue")
        self.append_log("\U0001f4c1 Creating all directories...", "blue")
        values = self.current_values()
        dir_keys = [
            "DATA_ROOT", "NOC_BASE_DIR", "NOC_SHARED_FOLDER",
            "MAE_DOWNLOAD_DIR", "MAE_EXPORT_BASE_DIR", "MAE_HISTORICAL_EXPORT_BASE_DIR",
            "NETECO_DOWNLOAD_DIR", "NETECO_EXPORT_BASE_DIR",
            "SMARTCARE_DOWNLOAD_DIR", "SMARTCARE_OUTPUT_DIR", "SMARTCARE_EXPORT_BASE_DIR",
            "PROJECT_LOG_DIR", "ANALYSIS_SOURCE_DIR", "ANALYSIS_OUTPUT_DIR",
            "INTERFERENCE_OUTPUT_DIR", "PS_TRAFFIC_SOURCE_DIR", "PS_TRAFFIC_OUTPUT_DIR",
            "SUBSCRIBERS_INPUT_DIR", "SUBSCRIBERS_OUTPUT_DIR",
        ]
        created = 0
        for key in dir_keys:
            path = values.get(key)
            if not path:
                continue
            try:
                p = Path(path)
                if not p.exists():
                    p.mkdir(parents=True, exist_ok=True)
                    self.append_log(f"✅ Created: {key} -> {path}", "green")
                    created += 1
                else:
                    self.append_log(f"⏭️ Already exists: {key} -> {path}", "gray")
            except Exception as e:
                self.append_log(f"❌ Failed to create {key}: {e}", "red")
        self.append_log("")
        self.append_log(f"✅ Created {created} new directories.", "green" if created > 0 else "blue")
        messagebox.showinfo("Directories", f"✅ Created {created} new directories.\nCheck the log panel for details.")

    def populate_paths_from_root(self):
        data_root = self.variables.get("DATA_ROOT", (tk.StringVar(), None, False))[0].get().strip()
        if not data_root:
            messagebox.showerror("Data Root", "Please set a valid Data Root folder first.")
            return
        root_path = Path(data_root)
        path_mappings = [
            ("NOC_BASE_DIR", "Output/Current_Alarms"),
            ("NOC_SHARED_FOLDER", "Output/Current_Alarms/Shared Current Alarms"),
            ("MAE_DOWNLOAD_DIR", "Input/Downloads"),
            ("MAE_EXPORT_BASE_DIR", "Output/Current_Alarms"),
            ("MAE_HISTORICAL_EXPORT_BASE_DIR", "Output/Historical_Alarms"),
            ("NETECO_DOWNLOAD_DIR", "Input/Downloads"),
            ("NETECO_EXPORT_BASE_DIR", "Output/Current_Alarms"),
            ("SMARTCARE_DOWNLOAD_DIR", "Input/Downloads"),
            ("SMARTCARE_OUTPUT_DIR", "Output/SmartCare_Exports"),
            ("SMARTCARE_EXPORT_BASE_DIR", "Output/Current_Alarms"),
            ("PROJECT_LOG_DIR", "logs"),
            ("ANALYSIS_SOURCE_DIR", "Output/SmartCare_Exports"),
            ("ANALYSIS_OUTPUT_DIR", "Output/Processed_Analysis"),
            ("ANALYSIS_HISTORY_FILE", "Output/Processed_Analysis/Comprehensive_Analysis_Historical.xlsx"),
            ("INTERFERENCE_OUTPUT_DIR", "Output/Subscribers/Interference_Output"),
            ("PS_TRAFFIC_SOURCE_DIR", "Input/FTP_RawData"),
            ("PS_TRAFFIC_OUTPUT_DIR", "Output/PS_Traffic_Output"),
            ("SUBSCRIBERS_INPUT_DIR", "Input/FTP_RawData"),
            ("SUBSCRIBERS_OUTPUT_DIR", "Output/Subscribers/Subscribers_Output"),
            ("SUBSCRIBERS_HISTORY_FILE", "Output/Subscribers/Subscribers_History.xlsx"),
        ]
        for key, rel_path in path_mappings:
            if key in self.variables:
                self.variables[key][0].set(str(root_path / rel_path))
        messagebox.showinfo("Paths Updated",
                            "All folder paths have been updated based on the Data Root.\nClick Save to persist.")

    def choose_dir(self, variable):
        folder = filedialog.askdirectory(initialdir=variable.get() or str(PROJECT_ROOT))
        if folder:
            variable.set(folder)

    def choose_file(self, variable):
        initial = variable.get().strip()
        initial_dir = str(PROJECT_ROOT)
        initial_file = ""
        if initial:
            initial_path = Path(initial)
            if initial_path.is_absolute():
                initial_dir = str(initial_path.parent)
                initial_file = initial_path.name
            else:
                if initial_path.parent != Path("."):
                    initial_dir = str(PROJECT_ROOT / initial_path.parent)
                initial_file = initial_path.name
        file_path = filedialog.askopenfilename(initialdir=initial_dir, initialfile=initial_file,
                                                title="Select file")
        if file_path:
            variable.set(file_path)

    def load_values(self):
        values = read_env_file()
        for key, (var, _entry, _secret) in self.variables.items():
            var.set(values.get(key, ""))

    def current_values(self):
        return {key: var.get().strip() for key, (var, _entry, _secret) in self.variables.items()}

    def validate_values(self, script_name=None):
        values = self.current_values()
        errors = []
        required_keys = SCRIPT_BY_NAME.get(script_name, {}).get("required_env", ()) if script_name else ()
        for key in required_keys:
            if not values.get(key):
                errors.append(f"{key} is required.")
        for key in INTEGER_FIELDS:
            value = values.get(key, "")
            if value and not value.isdigit():
                errors.append(f"{key} must be a whole number.")
        return errors

    def save_values(self, show_message=True):
        errors = self.validate_values()
        if errors:
            messagebox.showerror("Invalid settings", "\n".join(errors[:12]))
            return False

        values = self.current_values()

        dir_keys = [
            "DATA_ROOT", "NOC_BASE_DIR", "NOC_SHARED_FOLDER",
            "MAE_DOWNLOAD_DIR", "MAE_EXPORT_BASE_DIR", "MAE_HISTORICAL_EXPORT_BASE_DIR",
            "NETECO_DOWNLOAD_DIR", "NETECO_EXPORT_BASE_DIR",
            "SMARTCARE_DOWNLOAD_DIR", "SMARTCARE_OUTPUT_DIR", "SMARTCARE_EXPORT_BASE_DIR",
            "PROJECT_LOG_DIR", "ANALYSIS_SOURCE_DIR", "ANALYSIS_OUTPUT_DIR",
            "INTERFERENCE_OUTPUT_DIR", "PS_TRAFFIC_SOURCE_DIR", "PS_TRAFFIC_OUTPUT_DIR",
            "SUBSCRIBERS_INPUT_DIR", "SUBSCRIBERS_OUTPUT_DIR",
        ]
        for key in dir_keys:
            path = values.get(key)
            if path:
                try:
                    Path(path).mkdir(parents=True, exist_ok=True)
                except Exception:
                    pass

        lines = ["# NAE NET Eco project settings",
                 "# This file contains secrets and is intentionally ignored by Git.", ""]
        for section in SETTINGS:
            lines.append(f"# {section['section']}")
            for key, _label, _default, _field_type, _secret in section["fields"]:
                lines.append(f"{key}={quote_env_value(values[key])}")
            lines.append("")

        try:
            prepare_env_file_for_write()
            ENV_PATH.write_text("\n".join(lines), encoding="utf-8")
            hide_env_file()
        except PermissionError as exc:
            messagebox.showerror(
                "Cannot save settings",
                f"Permission denied while writing:\n{ENV_PATH}\n\nClose any program using this file and try again.\n\n{exc}",
            )
            return False

        load_env_file(override=True)
        os.environ.update(values)
        if show_message:
            messagebox.showinfo("Saved", f"Settings saved to:\n{ENV_PATH}")
        return True

    def toggle_secret_visibility(self):
        show = "" if self.show_secrets.get() else "*"
        for _key, (_var, entry, is_secret) in self.variables.items():
            if is_secret:
                entry.configure(show=show)

    # ---------------- Logging widget (thread-safe) ----------------
    def append_log(self, message, color=None):
        """Safe to call from any thread - always marshals onto the UI thread."""
        self.after(0, self._append_log_impl, message, color)

    def _append_log_impl(self, message, color):
        self.log_text.config(state="normal")
        if color:
            self.log_text.insert("end", message + "\n", color)
            self.log_text.tag_config(color, foreground=color)
        else:
            self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    # ============================================================
    # FTP/SFTP TEST - runs on a background thread so the UI never freezes
    # ============================================================
    def test_ftp_connection(self):
        if not self.save_values(show_message=False):
            return

        values = self.current_values()
        protocol = values.get("FTP_PROTOCOL", "SFTP").strip().upper()
        host = values.get("FTP_HOST", "").strip()
        if not host:
            messagebox.showerror("Test failed", "Server host is required.")
            return

        port_str = values.get("FTP_PORT", "22").strip()
        port = int(port_str) if port_str.isdigit() else 22
        username = values.get("FTP_USERNAME", "").strip()
        password = values.get("FTP_PASSWORD", "")
        remote_path = values.get("FTP_REMOTE_PATH", "/").strip()
        timeout = int(values.get("FTP_TIMEOUT_SECONDS", "30") or 30)

        self.ftp_status_label.config(text="Connecting...", foreground="blue")
        self.append_log("=" * 60, "blue")
        self.append_log(f"Test started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.append_log(f"Protocol: {protocol}")
        self.append_log(f"Host: {host}:{port}")
        self.append_log(f"Remote path: {remote_path}")

        thread = threading.Thread(
            target=self._test_ftp_worker,
            args=(protocol, host, port, username, password, remote_path, timeout, values),
            daemon=True,
        )
        thread.start()

    def _test_ftp_worker(self, protocol, host, port, username, password, remote_path, timeout, values):
        try:
            if protocol == "SFTP":
                self._test_sftp(host, port, username, password, remote_path, timeout)
            else:
                self._test_ftps(host, port, username, password, remote_path, timeout, values)
        except Exception as exc:
            error_tb = traceback.format_exc()
            self.after(0, lambda: self.ftp_status_label.config(text="✘ Connection failed", foreground="red"))
            self.append_log("")
            self.append_log("❌ CONNECTION FAILED", "red")
            self.append_log(f"Exception: {type(exc).__name__}: {exc}", "red")
            for line in error_tb.splitlines():
                self.append_log("  " + line, "red")
            self.after(0, lambda: messagebox.showerror(
                "Test failed",
                f"❌ Connection failed:\n\n{type(exc).__name__}: {exc}\n\nSee the log panel for full details."
            ))
            try:
                with open("ftp_test_error.log", "w") as f:
                    f.write(error_tb)
            except OSError:
                pass

    def _test_sftp(self, host, port, username, password, remote_path, timeout):
        self.append_log("")
        self.append_log("\U0001f510 Testing SFTP connection...", "blue")

        sftp_client = SFTPDownload(host, port, username, password, remote_path, timeout)
        sftp_client.connect()
        self.append_log("✔ SFTP connected successfully")

        files = sftp_client.list_files()
        self.append_log(f"✔ Directory listing retrieved ({len(files)} entries)")

        sftp_client.close()
        self.append_log("✔ Connection closed")
        self.after(0, lambda: self.ftp_status_label.config(text="✔ SFTP Connected", foreground="green"))
        self.append_log("")
        self.append_log("✅ SFTP CONNECTION SUCCESSFUL", "green")
        self.after(0, lambda: messagebox.showinfo(
            "Test successful",
            f"✅ SFTP connected successfully.\nDirectory: {remote_path}\nFiles/Dirs: {len(files)}"
        ))

    def _test_ftps(self, host, port, username, password, remote_path, timeout, values):
        self.append_log("")
        self.append_log("\U0001f510 Testing FTPS connection...", "blue")

        use_passive = values.get("FTP_PASSIVE", "True").strip().lower() in ("true", "1", "yes", "on")
        ignore_cert = values.get("FTP_IGNORE_CERT", "False").strip().lower() in ("true", "1", "yes", "on")

        self.append_log(f"Passive mode: {use_passive}")
        self.append_log(f"Ignore SSL: {ignore_cert}")

        ftps = FTP_TLS(context=ssl.create_default_context())
        if ignore_cert:
            ftps.context.check_hostname = False
            ftps.context.verify_mode = ssl.CERT_NONE
        ftps.connect(host, port, timeout=timeout)
        self.append_log(f"✔ Connected to {host}:{port}")

        ftps.set_pasv(use_passive)
        self.append_log(f"✔ Passive mode {'enabled' if use_passive else 'disabled'}")

        if ignore_cert:
            self.append_log("Warning: SSL certificate verification is disabled", "red")

        ftps.auth()
        self.append_log("✔ Authentication handshake OK")
        ftps.login(username, password)
        self.append_log(f"✔ Logged in as {username}")
        ftps.prot_p()
        self.append_log("✔ Secure data channel established (PROT P)")
        ftps.cwd(remote_path)
        self.append_log(f"✔ Changed to remote directory: {remote_path}")
        entries = ftps.nlst()
        self.append_log(f"✔ Directory listing retrieved ({len(entries)} entries)")
        ftps.quit()
        self.append_log("✔ Connection closed")

        self.after(0, lambda: self.ftp_status_label.config(text="✔ FTPS Connected", foreground="green"))
        self.append_log("")
        self.append_log("✅ FTPS CONNECTION SUCCESSFUL", "green")
        self.after(0, lambda: messagebox.showinfo(
            "Test successful",
            f"✅ FTPS connected successfully.\nDirectory: {remote_path}\nFiles/Dirs: {len(entries)}"
        ))


if __name__ == "__main__":
    ControlPanel().mainloop()
