import os
import socket
import subprocess
import sys
import tkinter as tk
from datetime import datetime, timedelta
from ftplib import FTP_TLS
from pathlib import Path
from tkinter import filedialog, messagebox, ttk, scrolledtext
import ssl
import traceback
import zipfile
import logging
import paramiko

from project_config import ENV_PATH, PROJECT_ROOT, load_env_file, parse_env_file

# =============================================================
# SFTP HANDLER (your working code)
# =============================================================
logger = logging.getLogger(__name__)


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
        """Establish SFTP connection."""
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
        """List files in remote directory."""
        try:
            files = self.sftp.listdir()
            if pattern:
                import fnmatch
                files = [f for f in files if fnmatch.fnmatch(f, pattern)]
            return files
        except Exception as e:
            logger.error(f"Failed to list files: {e}")
            raise

    def download_file(self, remote_filename, local_path):
        """Download a single file."""
        try:
            local_file = Path(local_path) / remote_filename
            self.sftp.get(remote_filename, str(local_file))
            logger.info(f"Downloaded: {remote_filename} -> {local_file}")
            return local_file
        except Exception as e:
            logger.error(f"Failed to download {remote_filename}: {e}")
            raise

    def download_and_extract_zip(self, remote_filename, extract_to):
        """Download a ZIP file and extract it."""
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
        """Close SFTP connection."""
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
# SETTINGS DEFINITION
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
            ("NOC_BASE_DIR", "Current alarms base folder", data_path("Current_Alarms"), "dir", False),
            ("NOC_SHARED_FOLDER", "Shared report folder", data_path("Current_Alarms/Shared Current Alarms"), "dir",
             False),
            ("MERGE_INTERVAL_SECONDS", "Merge interval seconds", "600", "text", False),
        ],
    },
    {
        "section": "MAE Scraper",
        "fields": [
            ("MAE_URL", "MAE URL", "", "text", False),
            ("MAE_USERNAME", "MAE username", "", "text", False),
            ("MAE_PASSWORD", "MAE password", "", "text", True),
            ("MAE_DOWNLOAD_DIR", "MAE download folder", data_path("Downloads"), "dir", False),
            ("MAE_EXPORT_BASE_DIR", "MAE export base folder", data_path("Current_Alarms"), "dir", False),
            ("MAE_WAIT_TIMEOUT", "MAE wait timeout seconds", "45", "text", False),
            ("MAE_INTERVAL_SECONDS", "MAE interval seconds", "300", "text", False),
        ],
    },
    {
        "section": "NetEco Scraper",
        "fields": [
            ("NETECO_URL", "NetEco URL", "", "text", False),
            ("NETECO_ALL_CURRENT_ALARMS_URL", "NetEco All Current Alarms URL",
             "https://10.171.68.2:31943/eviewwebsite/index.html#path=/fmAlarmApp/fmAlarmView&templateId=120&fmPage=true&_t=1787017955421",
             "text", False),
            ("NETECO_USERNAME", "NetEco username", "", "text", False),
            ("NETECO_PASSWORD", "NetEco password", "", "text", True),
            ("NETECO_DOWNLOAD_DIR", "NetEco download folder", data_path("Downloads"), "dir", False),
            ("NETECO_EXPORT_BASE_DIR", "NetEco export base folder", data_path("Current_Alarms"), "dir", False),
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
            ("SMARTCARE_DOWNLOAD_DIR", "SmartCare download folder", data_path("Downloads"), "dir", False),
            ("SMARTCARE_OUTPUT_DIR", "SmartCare output folder", data_path("SmartCare_Exports"), "dir", False),
            ("SMARTCARE_EXPORT_BASE_DIR", "SmartCare export base folder", data_path("Current_Alarms"), "dir", False),
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
            ("ANALYSIS_SOURCE_DIR", "Analysis source folder", data_path("SmartCare_Exports"), "dir", False),
            ("ANALYSIS_OUTPUT_DIR", "Analysis output folder", data_path("Processed_Analysis"), "dir", False),
            ("ANALYSIS_HISTORY_FILE", "Analysis history file",
             data_path("Processed_Analysis/Comprehensive_Analysis_Historical.xlsx"), "file", False),
            ("ANALYSIS_SCRIPT_PATH", "Analysis script", "download_analysis_pipeline.py", "file", False),
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
            # FTPS specific
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
             data_path("Subscribers/Raw Data/Interference_Output"), "dir", False),
        ],
    },
    {
        "section": "PS Traffic per site",
        "fields": [
            ("PS_TRAFFIC_FTP_PREFIX", "PS Traffic ZIP prefix", "PS Daily Traffic_2G_3G_4G_", "text", False),
            ("PS_TRAFFIC_SOURCE_DIR", "PS Traffic source folder", data_path("Subscribers/Raw Data"), "dir", False),
            ("PS_TRAFFIC_OUTPUT_DIR", "PS Traffic output folder", data_path("PS_Traffic_Output"), "dir", False),
            ("PS_TRAFFIC_FILE_2G_TOKEN", "2G CSV token", "(PS Traffic 2G)", "text", False),
            ("PS_TRAFFIC_FILE_3G_TOKEN", "3G CSV token", "(PS Traffic 3G)", "text", False),
            ("PS_TRAFFIC_FILE_4G_TOKEN", "4G CSV token", "(PS Traffic 4G)", "text", False),
        ],
    },
    {
        "section": "Subscribers Calculation",
        "fields": [
            ("SUBSCRIBERS_INPUT_DIR", "Subscriber input folder", data_path("Subscribers/Raw Data"), "dir", False),
            ("SUBSCRIBERS_OUTPUT_DIR", "Subscriber calculation output folder",
             data_path("Subscribers/Raw Data/Subscribers_Output"), "dir", False),
            ("SUBSCRIBERS_HISTORY_FILE", "Subscriber history file",
             data_path("Subscribers/Raw Data/Subscribers_History.xlsx"), "file", False),
            ("SUBSCRIBERS_SCRIPT_PATH", "Subscriber calculation script",
             "subscriers with 2G interference with ftp andd weekly backup report 3-8-2026.py", "file", False),
        ],
    },
    {
        "section": "Script Paths",
        "fields": [
            ("TELEGRAM_NOC_BOT_SCRIPT_PATH", "Telegram NOC Bot script", "telegram_noc_bot.py", "file", False),
            ("MERGE_REPORTS_SCRIPT_PATH", "Merge Reports script", "merge_noc_reports.py",
             "file", False),
            ("NETECO_SCRAPER_SCRIPT_PATH", "NetEco Scraper script", "neteco_scraper.py", "file", False),
            ("MAE_SCRAPER_SCRIPT_PATH", "MAE Scraper script", "mae_scraper.py", "file", False),
            ("SMARTCARE_CEM_SCRIPT_PATH", "SmartCare CEM script", "SmartCare CEM/SmartCare CEM v11.py", "file", False),
            ("ANALYSIS_SCRIPT_PATH", "Comprehensive Analysis script", "download_analysis_pipeline.py", "file", False),
            ("SUBSCRIBERS_FTP_DAILY_SCRIPT_PATH", "Subscribers FTP daily script", "subscribers_ftp_daily.py", "file",
             False),
            ("SUBSCRIBERS_INTERFERENCE_MONTHLY_SCRIPT_PATH", "Subscribers interference monthly script",
             "subscribers_interference_monthly.py", "file", False),
            ("PS_TRAFFIC_SCRIPT_PATH", "PS Traffic per site script", "ps_traffic_report.py",
             "file", False),
            ("SUBSCRIBERS_FTPS_SCRIPT_PATH", "Subscribers FTPS script",
             "subscriber_reports.py", "file", False),
        ],
    },
    {
        "section": "Telegram Bot",
        "fields": [
            ("TELEGRAM_BOT_TOKEN", "Telegram bot token", "", "text", True),
        ],
    },
]

# --- Helper dictionaries ---
SCRIPT_PATH_KEYS = {
    "Telegram NOC Bot": "TELEGRAM_NOC_BOT_SCRIPT_PATH",
    "Merge Reports": "MERGE_REPORTS_SCRIPT_PATH",
    "NetEco Scraper": "NETECO_SCRAPER_SCRIPT_PATH",
    "MAE Scraper": "MAE_SCRAPER_SCRIPT_PATH",
    "SmartCare CEM": "SMARTCARE_CEM_SCRIPT_PATH",
    "Comprehensive Analysis": "ANALYSIS_SCRIPT_PATH",
    "Subscribers FTP Daily": "SUBSCRIBERS_FTP_DAILY_SCRIPT_PATH",
    "Subscribers Interference Monthly": "SUBSCRIBERS_INTERFERENCE_MONTHLY_SCRIPT_PATH",
    "PS Traffic Per Site": "PS_TRAFFIC_SCRIPT_PATH",
    "Subscribers FTPS": "SUBSCRIBERS_FTPS_SCRIPT_PATH",
}

SCRIPT_PATH_DEFAULTS = {
    "Telegram NOC Bot": "telegram_noc_bot.py",
    "Merge Reports": "merge_noc_reports.py",
    "NetEco Scraper": "neteco_scraper.py",
    "MAE Scraper": "mae_scraper.py",
    "SmartCare CEM": "SmartCare CEM/SmartCare CEM v11.py",
    "Comprehensive Analysis": "download_analysis_pipeline.py",
    "Subscribers FTP Daily": "subscribers_ftp_daily.py",
    "Subscribers Interference Monthly": "subscribers_interference_monthly.py",
    "PS Traffic Per Site": "ps_traffic_report.py",
    "Subscribers FTPS": "subscriber_reports.py",
}

SCRIPTS = dict(SCRIPT_PATH_DEFAULTS)

CONTINUOUS_SCRIPTS = (
    "MAE Scraper",
    "NetEco Scraper",
    "Merge Reports",
    "Telegram NOC Bot",
)

REQUIRED_FOR_SCRIPT = {
    "Telegram NOC Bot": ("TELEGRAM_BOT_TOKEN", "NOC_BASE_DIR"),
    "Merge Reports": ("NOC_BASE_DIR", "NOC_SHARED_FOLDER"),
    "NetEco Scraper": ("NETECO_URL", "NETECO_USERNAME", "NETECO_PASSWORD"),
    "MAE Scraper": ("MAE_URL", "MAE_USERNAME", "MAE_PASSWORD"),
    "SmartCare CEM": ("SMARTCARE_LOGIN_URL", "SMARTCARE_USERNAME", "SMARTCARE_PASSWORD"),
    "Subscribers FTPS": ("FTP_HOST", "FTP_USERNAME", "FTP_PASSWORD"),
    "Subscribers FTP Daily": ("FTP_HOST", "FTP_USERNAME", "FTP_PASSWORD"),
    "Subscribers Interference Monthly": ("FTP_HOST", "FTP_USERNAME", "FTP_PASSWORD"),
    "PS Traffic Per Site": ("PS_TRAFFIC_SOURCE_DIR",),
}

INTEGER_FIELDS = {
    "MERGE_INTERVAL_SECONDS",
    "MAE_WAIT_TIMEOUT",
    "MAE_INTERVAL_SECONDS",
    "SMARTCARE_EXPORT_TASK_TIMEOUT",
    "SMARTCARE_POLL_INTERVAL",
    "NETECO_WAIT_TIMEOUT",
    "NETECO_INTERVAL_SECONDS",
    "NETECO_DOWNLOAD_TIMEOUT_SECONDS",
    "NETECO_DOWNLOAD_STABLE_SECONDS",
    "NETECO_RETRY_DELAY_SECONDS",
    "NETECO_MAX_CONSECUTIVE_FAILURES",
    "NETECO_PORT_CHECK_TIMEOUT",
    "FTP_PORT",
    "FTP_TIMEOUT_SECONDS",
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
    if not script_name:
        return None
    if values is None:
        values = read_env_file()

    key = SCRIPT_PATH_KEYS[script_name]
    raw_path = values.get(key, SCRIPT_PATH_DEFAULTS[script_name]) or ""
    if not raw_path:
        return None

    legacy_entry_points = {
        "mae_scraper_newerBrowserversion149.py": "mae_scraper.py",
        "neteco_continuous 15-5-2026.py": "neteco_scraper.py",
        "Processing & Merging Script 31-5 with sharing.py": "merge_noc_reports.py",
        "subscriers with 2G interference with ftp andd weekly backup report 3-8-2026.py": "subscriber_reports.py",
        "PS Traffic per site/PS Traffic per site v3 .py": "ps_traffic_report.py",
    }
    raw_path = legacy_entry_points.get(raw_path.replace("\\", "/"), raw_path)
    path = Path(raw_path.strip())
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def run_attrib(*attributes):
    subprocess.run(
        ["attrib", *attributes, str(ENV_PATH)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def hide_env_file():
    if os.name == "nt" and ENV_PATH.exists():
        run_attrib("+h")


def prepare_env_file_for_write():
    if os.name == "nt" and ENV_PATH.exists():
        run_attrib("-h", "-r")


# ---------- Main GUI ----------
class SettingsApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("NAE NET Eco Project Settings")
        self.geometry("1050x850")
        self.minsize(900, 700)
        self.variables = {}
        self.show_secrets = tk.BooleanVar(value=False)
        self.ftp_status_label = None
        self.log_text = None

        self._build_ui()
        self.load_values()

    def _build_ui(self):
        header = ttk.Frame(self, padding=(14, 12))
        header.pack(fill="x")
        ttk.Label(header, text="Project Settings", font=("Segoe UI", 16, "bold")).pack(side="left")
        ttk.Label(header, text=f"Saved to: {ENV_PATH}", foreground="#555").pack(side="right")

        container = ttk.Frame(self)
        container.pack(fill="both", expand=True, padx=14, pady=(0, 0))

        notebook = ttk.Notebook(container)
        notebook.pack(fill="both", expand=True)

        tabs = {
            "General": ttk.Frame(notebook),
            "Scrapers": ttk.Frame(notebook),
            "SmartCare & Analysis": ttk.Frame(notebook),
            "Subscribers": ttk.Frame(notebook),
        }

        for tab_name, frame in tabs.items():
            notebook.add(frame, text=tab_name)
            frame.columnconfigure(1, weight=1)

        tab_row = {name: 0 for name in tabs}

        section_tab = {
            "Data Management": "General",
            "NOC Reports": "General",
            "Logging": "General",
            "Script Paths": "General",
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

        for section in SETTINGS:
            tab_name = section_tab.get(section["section"], "General")
            parent = tabs[tab_name]
            row = tab_row[tab_name]

            section_label = ttk.Label(parent, text=section["section"], font=("Segoe UI", 12, "bold"))
            section_label.grid(row=row, column=0, columnspan=3, sticky="w", pady=(16, 6), padx=(2, 8))
            row += 1

            for key, label_text, _default, field_type, is_secret in section["fields"]:
                ttk.Label(parent, text=label_text).grid(row=row, column=0, sticky="w", padx=(2, 8), pady=3)
                var = tk.StringVar()
                entry = ttk.Entry(parent, textvariable=var, width=86, show="*" if is_secret else "")
                entry.grid(row=row, column=1, sticky="ew", pady=3)
                self.variables[key] = (var, entry, is_secret)

                if field_type == "dir":
                    ttk.Button(parent, text="Browse", command=lambda v=var: self.choose_dir(v)).grid(
                        row=row, column=2, padx=(6, 2), pady=3
                    )
                elif field_type == "file":
                    ttk.Button(parent, text="Browse", command=lambda v=var: self.choose_file(v)).grid(
                        row=row, column=2, padx=(6, 2), pady=3
                    )
                row += 1

            tab_row[tab_name] = row

        # Auto-populate and Create Directories buttons
        general_frame = tabs["General"]
        data_root_row = tab_row["General"]
        action_frame = ttk.Frame(general_frame)
        action_frame.grid(row=data_root_row, column=0, columnspan=3, sticky="ew", pady=8)
        ttk.Button(action_frame, text="Auto-populate all paths from Data Root",
                   command=self.populate_paths_from_root).pack(side="left")
        ttk.Button(action_frame, text="Create All Directories",
                   command=self.create_all_directories).pack(side="left", padx=8)
        ttk.Label(action_frame, text="Creates all folders defined in settings.",
                  foreground="#555").pack(side="left", padx=8)
        tab_row["General"] = data_root_row + 1

        # Subscribers tab: FTP test with status and log
        subscriber_actions = ttk.Frame(tabs["Subscribers"], padding=(2, 8))
        subscriber_actions.grid(row=tab_row["Subscribers"], column=0, columnspan=3, sticky="ew")
        ttk.Button(subscriber_actions, text="Test FTP/SFTP Connection", command=self.test_ftp_connection).pack(
            side="left")
        self.ftp_status_label = ttk.Label(subscriber_actions, text="", foreground="#555")
        self.ftp_status_label.pack(side="left", padx=8)

        log_frame = ttk.LabelFrame(tabs["Subscribers"], text="FTP/SFTP Test Log", padding=5)
        log_frame.grid(row=tab_row["Subscribers"] + 1, column=0, columnspan=3, sticky="nsew", pady=8)
        self.log_text = scrolledtext.ScrolledText(log_frame, height=10, width=100, state="normal", font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True)
        self.log_text.insert("end", "Ready for FTP/SFTP test...\n")
        self.log_text.config(state="disabled")

        # ============================================================
        # BOTTOM CONTROLS - ALL BUTTONS HERE
        # ============================================================
        control_frame = ttk.Frame(self)
        control_frame.pack(fill="x", padx=14, pady=(8, 8))

        # Left side: Show passwords checkbox
        ttk.Checkbutton(
            control_frame,
            text="Show passwords/tokens",
            variable=self.show_secrets,
            command=self.toggle_secret_visibility,
        ).pack(side="left")

        # Right side: ALL action buttons
        ttk.Button(control_frame, text="Reload", command=self.load_values).pack(side="right", padx=(8, 0))
        ttk.Button(control_frame, text="Save Settings", command=self.save_values).pack(side="right", padx=(8, 0))
        ttk.Button(control_frame, text="🧪 Test FTP", command=self.test_ftp_connection_from_main).pack(side="right",
                                                                                                      padx=(8, 0))
        ttk.Button(control_frame, text="💾 Save & Reload Env", command=self.save_and_reload).pack(side="right",
                                                                                                 padx=(8, 0))

        # Run Scripts
        runner = ttk.LabelFrame(self, text="Run Script", padding=10)
        runner.pack(fill="x", padx=14, pady=(0, 14))
        self.script_choice = tk.StringVar(value="Telegram NOC Bot")
        ttk.Combobox(runner, textvariable=self.script_choice, values=list(SCRIPTS), state="readonly", width=28).pack(
            side="left"
        )
        ttk.Button(runner, text="Run in new window", command=self.run_script).pack(side="left", padx=8)
        ttk.Button(runner, text="Run Continuous Set", command=self.run_continuous_scripts).pack(side="left", padx=8)
        ttk.Label(runner, text="Settings are saved before launch.", foreground="#555").pack(side="left", padx=8)

        # Analysis runner
        analysis_runner = ttk.LabelFrame(self, text="Comprehensive Analysis", padding=10)
        analysis_runner.pack(fill="x", padx=14, pady=(0, 14))
        ttk.Button(analysis_runner, text="Run Latest Analysis", command=self.run_analysis).pack(side="left", padx=8)
        ttk.Button(analysis_runner, text="Run SmartCare + Update History",
                   command=self.run_full_smartcare_analysis).pack(side="left", padx=8)
        ttk.Button(analysis_runner, text="Schedule Sunday 02:00", command=self.schedule_weekly_task).pack(side="left",
                                                                                                          padx=8)
        ttk.Button(analysis_runner, text="Open Output Folder", command=self.open_analysis_output).pack(side="left",
                                                                                                       padx=8)
        ttk.Label(analysis_runner, text="Uses latest Comprehensive_Analysis file in source folder.",
                  foreground="#555").pack(side="left", padx=8)


    def save_and_reload(self):
        """Save settings and reload environment variables for all running scripts."""
        if self.save_values(show_message=True):
            # Reload environment from .env file
            from project_config import load_env_file
            load_env_file(override=True)
            # Update os.environ with current values
            values = self.current_values()
            os.environ.update(values)
            messagebox.showinfo(
                "Reloaded",
                "✅ Environment variables reloaded.\n\n"
                "All scripts will now use the new credentials.\n"
                "💡 You may need to restart any running scripts."
            )

    def create_all_directories(self):
        """Create all directories defined in settings."""
        self.append_log("=" * 60, "blue")
        self.append_log("📁 Creating all directories...", "blue")

        values = self.current_values()
        dir_keys = [
            "DATA_ROOT",
            "NOC_BASE_DIR",
            "NOC_SHARED_FOLDER",
            "MAE_DOWNLOAD_DIR",
            "MAE_EXPORT_BASE_DIR",
            "NETECO_DOWNLOAD_DIR",
            "NETECO_EXPORT_BASE_DIR",
            "SMARTCARE_DOWNLOAD_DIR",
            "SMARTCARE_OUTPUT_DIR",
            "SMARTCARE_EXPORT_BASE_DIR",
            "PROJECT_LOG_DIR",
            "ANALYSIS_SOURCE_DIR",
            "ANALYSIS_OUTPUT_DIR",
            "INTERFERENCE_OUTPUT_DIR",
            "PS_TRAFFIC_SOURCE_DIR",
            "PS_TRAFFIC_OUTPUT_DIR",
            "SUBSCRIBERS_INPUT_DIR",
            "SUBSCRIBERS_OUTPUT_DIR",
        ]

        created = 0
        for key in dir_keys:
            path = values.get(key)
            if path:
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

    def test_ftp_connection_from_main(self):
        """Test FTP/SFTP connection using current settings (from main toolbar)."""
        # First save the current settings
        if not self.save_values(show_message=False):
            return

        # Switch to the Subscribers tab
        for child in self.winfo_children():
            if isinstance(child, ttk.Frame):
                for subchild in child.winfo_children():
                    if isinstance(subchild, ttk.Notebook):
                        subchild.select(3)
                        break

        # Then run the FTP test
        self.test_ftp_connection()

    def populate_paths_from_root(self):
        """Set all folder paths to subdirectories of DATA_ROOT."""
        data_root = self.variables.get("DATA_ROOT", (tk.StringVar(), None, False))[0].get().strip()
        if not data_root:
            messagebox.showerror("Data Root", "Please set a valid Data Root folder first.")
            return

        root_path = Path(data_root)
        path_mappings = [
            ("NOC_BASE_DIR", "Current_Alarms"),
            ("NOC_SHARED_FOLDER", "Current_Alarms/Shared Current Alarms"),
            ("MAE_DOWNLOAD_DIR", "Downloads"),
            ("MAE_EXPORT_BASE_DIR", "Current_Alarms"),
            ("NETECO_DOWNLOAD_DIR", "Downloads"),
            ("NETECO_EXPORT_BASE_DIR", "Current_Alarms"),
            ("SMARTCARE_DOWNLOAD_DIR", "Downloads"),
            ("SMARTCARE_OUTPUT_DIR", "SmartCare_Exports"),
            ("SMARTCARE_EXPORT_BASE_DIR", "Current_Alarms"),
            ("PROJECT_LOG_DIR", "logs"),
            ("ANALYSIS_SOURCE_DIR", "SmartCare_Exports"),
            ("ANALYSIS_OUTPUT_DIR", "Processed_Analysis"),
            ("ANALYSIS_HISTORY_FILE", "Processed_Analysis/Comprehensive_Analysis_Historical.xlsx"),
            ("INTERFERENCE_OUTPUT_DIR", "Subscribers/Raw Data/Interference_Output"),
            ("PS_TRAFFIC_SOURCE_DIR", "Subscribers/Raw Data"),
            ("PS_TRAFFIC_OUTPUT_DIR", "PS_Traffic_Output"),
            ("SUBSCRIBERS_INPUT_DIR", "Subscribers/Raw Data"),
            ("SUBSCRIBERS_OUTPUT_DIR", "Subscribers/Raw Data/Subscribers_Output"),
            ("SUBSCRIBERS_HISTORY_FILE", "Subscribers/Raw Data/Subscribers_History.xlsx"),
        ]

        for key, rel_path in path_mappings:
            if key in self.variables:
                var, _, _ = self.variables[key]
                new_path = str(root_path / rel_path)
                var.set(new_path)

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
                initial_path = Path(initial)
                if initial_path.parent != Path("."):
                    initial_dir = str(PROJECT_ROOT / initial_path.parent)
                initial_file = initial_path.name

        file_path = filedialog.askopenfilename(
            initialdir=initial_dir,
            initialfile=initial_file,
            title="Select script file",
        )
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

        required_keys = REQUIRED_FOR_SCRIPT.get(script_name, ()) if script_name else ()
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

        # ========== CREATE ALL DIRECTORIES ==========
        dir_keys = [
            "DATA_ROOT", "NOC_BASE_DIR", "NOC_SHARED_FOLDER",
            "MAE_DOWNLOAD_DIR", "MAE_EXPORT_BASE_DIR",
            "NETECO_DOWNLOAD_DIR", "NETECO_EXPORT_BASE_DIR",
            "SMARTCARE_DOWNLOAD_DIR", "SMARTCARE_OUTPUT_DIR", "SMARTCARE_EXPORT_BASE_DIR",
            "PROJECT_LOG_DIR",
            "ANALYSIS_SOURCE_DIR", "ANALYSIS_OUTPUT_DIR",
            "INTERFERENCE_OUTPUT_DIR",
            "PS_TRAFFIC_SOURCE_DIR", "PS_TRAFFIC_OUTPUT_DIR",
            "SUBSCRIBERS_INPUT_DIR", "SUBSCRIBERS_OUTPUT_DIR",
        ]

        for key in dir_keys:
            path = values.get(key)
            if path:
                try:
                    Path(path).mkdir(parents=True, exist_ok=True)
                except Exception:
                    pass

        lines = [
            "# NAE NET Eco project settings",
            "# This file contains secrets and is intentionally ignored by Git.",
            "",
        ]
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

    def append_log(self, message, color=None):
        self.log_text.config(state="normal")
        if color:
            self.log_text.insert("end", message + "\n", color)
            self.log_text.tag_config(color, foreground=color)
        else:
            self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")
        self.update()

    # ============================================================
    # ENHANCED FTP/SFTP TEST
    # ============================================================
    def test_ftp_connection(self):
        """Test connection using either FTPS or SFTP based on protocol setting."""
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

        try:
            if protocol == "SFTP":
                self._test_sftp(host, port, username, password, remote_path, timeout)
            else:
                self._test_ftps(host, port, username, password, remote_path, timeout, values)

        except Exception as exc:
            error_tb = traceback.format_exc()
            self.ftp_status_label.config(text="✘ Connection failed", foreground="red")
            self.append_log("")
            self.append_log("❌ CONNECTION FAILED", "red")
            self.append_log(f"Exception: {type(exc).__name__}: {exc}", "red")
            for line in error_tb.splitlines():
                self.append_log("  " + line, "red")
            messagebox.showerror(
                "Test failed",
                f"❌ Connection failed:\n\n{type(exc).__name__}: {exc}\n\nSee the log panel for full details."
            )
            with open("ftp_test_error.log", "w") as f:
                f.write(error_tb)

    def _test_sftp(self, host, port, username, password, remote_path, timeout):
        """Test SFTP connection using your working SFTPDownload class."""
        self.append_log("")
        self.append_log("🔐 Testing SFTP connection...", "blue")

        sftp_client = SFTPDownload(host, port, username, password, remote_path, timeout)
        sftp_client.connect()
        self.append_log("✔ SFTP connected successfully")

        files = sftp_client.list_files()
        self.append_log(f"✔ Directory listing retrieved ({len(files)} entries)")

        sftp_client.close()
        self.append_log("✔ Connection closed")
        self.ftp_status_label.config(text="✔ SFTP Connected", foreground="green")
        self.append_log("")
        self.append_log("✅ SFTP CONNECTION SUCCESSFUL", "green")
        messagebox.showinfo(
            "Test successful",
            f"✅ SFTP connected successfully.\nDirectory: {remote_path}\nFiles/Dirs: {len(files)}"
        )

    def _test_ftps(self, host, port, username, password, remote_path, timeout, values):
        """Test FTPS connection (existing implementation)."""
        self.append_log("")
        self.append_log("🔐 Testing FTPS connection...", "blue")

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

        self.ftp_status_label.config(text="✔ FTPS Connected", foreground="green")
        self.append_log("")
        self.append_log("✅ FTPS CONNECTION SUCCESSFUL", "green")
        messagebox.showinfo(
            "Test successful",
            f"✅ FTPS connected successfully.\nDirectory: {remote_path}\nFiles/Dirs: {len(entries)}"
        )

    def run_analysis(self):
        self.run_scripts(("Comprehensive Analysis",))

    def run_full_smartcare_analysis(self):
        if not self.save_values(show_message=False):
            return
        wrapper = PROJECT_ROOT / "run_smartcare_analysis_task.py"
        if not wrapper.exists():
            messagebox.showerror("SmartCare", f"Wrapper not found:\n{wrapper}")
            return
        env = os.environ.copy()
        env.update(self.current_values())
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        subprocess.Popen([sys.executable, str(wrapper)], cwd=str(PROJECT_ROOT), env=env)
        self.append_log("Started SmartCare + analysis pipeline.", "green")

    def schedule_weekly_task(self):
        messagebox.showinfo("Scheduling", "Use Windows Task Scheduler to run run_smartcare_analysis_task.py weekly.\n"
                            "Automatic task creation is intentionally not performed from this GUI.")

    def smartcare_ran_yesterday(self, output_dir: Path) -> bool:
        if not output_dir.exists():
            return False
        yesterday = (datetime.now() - timedelta(days=1)).date()
        return any(datetime.fromtimestamp(p.stat().st_mtime).date() == yesterday
                   for p in output_dir.glob("Comprehensive_Analysis_*"))

    def ensure_smartcare_ran_yesterday(self, values: dict) -> bool:
        return self.smartcare_ran_yesterday(Path(values.get("SMARTCARE_OUTPUT_DIR", "")))

    def open_analysis_output(self):
        if not self.save_values(show_message=False):
            return
        output_dir = Path(self.current_values()["ANALYSIS_OUTPUT_DIR"])
        output_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(str(output_dir))

    def run_script(self):
        self.run_scripts((self.script_choice.get(),))

    def run_continuous_scripts(self):
        self.run_scripts(CONTINUOUS_SCRIPTS)

    def run_scripts(self, script_names):
        if not self.save_values(show_message=False):
            return
        values = self.current_values()
        env = os.environ.copy()
        env.update(values)
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        launched = []
        for script_name in script_names:
            errors = self.validate_values(script_name)
            if errors:
                messagebox.showerror("Invalid settings", "\n".join(errors))
                return
            script_path = resolve_script_path(script_name, values)
            if not script_path or not script_path.exists():
                messagebox.showerror("Script not found", f"{script_name}:\n{script_path}")
                return
            subprocess.Popen([sys.executable, str(script_path)], cwd=str(PROJECT_ROOT), env=env)
            launched.append(script_name)
        self.append_log(f"Started: {', '.join(launched)}", "green")


if __name__ == "__main__":
    SettingsApp().mainloop()
