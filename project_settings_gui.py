import os
import subprocess
import sys
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from project_config import ENV_PATH, PROJECT_ROOT, load_env_file, parse_env_file

SETTINGS = [
    {
        "section": "NOC Reports",
        "fields": [
            ("NOC_BASE_DIR", "Current alarms base folder", r"C:\Current_Alarms", "dir", False),
            ("NOC_SHARED_FOLDER", "Shared report folder", r"C:\Current_Alarms\Shared Current Alarms", "dir", False),
            ("MERGE_INTERVAL_SECONDS", "Merge interval seconds", "600", "text", False),
        ],
    },
    {
        "section": "MAE Scraper",
        "fields": [
            ("MAE_URL", "MAE URL", "", "text", False),
            ("MAE_USERNAME", "MAE username", "", "text", False),
            ("MAE_PASSWORD", "MAE password", "", "text", True),
            ("MAE_DOWNLOAD_DIR", "MAE download folder", str(Path.home() / "Downloads"), "dir", False),
            ("MAE_EXPORT_BASE_DIR", "MAE export base folder", r"C:\Current_Alarms", "dir", False),
            ("MAE_WAIT_TIMEOUT", "MAE wait timeout seconds", "45", "text", False),
            ("MAE_INTERVAL_SECONDS", "MAE interval seconds", "300", "text", False),
        ],
    },
    {
        "section": "NetEco Scraper",
        "fields": [
            ("NETECO_URL", "NetEco URL", "", "text", False),
            ("NETECO_USERNAME", "NetEco username", "", "text", False),
            ("NETECO_PASSWORD", "NetEco password", "", "text", True),
            ("NETECO_DOWNLOAD_DIR", "NetEco download folder", str(Path.home() / "Downloads"), "dir", False),
            ("NETECO_EXPORT_BASE_DIR", "NetEco export base folder", r"C:\Current_Alarms", "dir", False),
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
            ("SMARTCARE_DOWNLOAD_DIR", "SmartCare download folder", str(Path.home() / "Downloads"), "dir", False),
            ("SMARTCARE_OUTPUT_DIR", "SmartCare output folder", str(Path.home() / "Downloads" / "SmartCare_Exports"), "dir", False),
            ("SMARTCARE_EXPORT_BASE_DIR", "SmartCare export base folder", r"C:\Current_Alarms", "dir", False),
            ("SMARTCARE_EXPORT_TASK_TIMEOUT", "SmartCare export task timeout seconds", "300", "text", False),
            ("SMARTCARE_POLL_INTERVAL", "SmartCare poll interval seconds", "15", "text", False),
        ],
    },
    {
        "section": "Analysis",
        "fields": [
            ("ANALYSIS_SOURCE_DIR", "Analysis source folder", str(Path.home() / "Downloads"), "dir", False),
            ("ANALYSIS_OUTPUT_DIR", "Analysis output folder", str(Path.home() / "Downloads" / "Processed_Analysis"), "dir", False),
            ("ANALYSIS_HISTORY_FILE", "Analysis history file", str(Path.home() / "Downloads" / "Processed_Analysis" / "Comprehensive_Analysis_Historical.xlsx"), "file", False),
            ("ANALYSIS_SCRIPT_PATH", "Analysis script", "download_analysis_pipeline.py", "file", False),
        ],
    },
    {
        "section": "Subscribers FTPS",
        "fields": [
            ("SUBSCRIBERS_RAW_DIR", "Subscribers raw data folder", str(PROJECT_ROOT / "Subscribers" / "Raw Data"), "dir", False),
            ("FTP_HOST", "FTPS host", "", "text", False),
            ("FTP_PORT", "FTPS port", "21", "text", False),
            ("FTP_USERNAME", "FTPS username", "", "text", False),
            ("FTP_PASSWORD", "FTPS password", "", "text", True),
            ("FTP_REMOTE_PATH", "FTPS remote path", "/ftproot/New", "text", False),
            ("FTP_FILE_PATTERN", "FTPS file pattern", "*{yyyymmdd}*.zip", "text", False),
            ("FTP_TIMEOUT_SECONDS", "FTPS timeout seconds", "30", "text", False),
        ],
    },
    {
        "section": "Script Paths",
        "fields": [
            ("TELEGRAM_NOC_BOT_SCRIPT_PATH", "Telegram NOC Bot script", "telegram_noc_bot.py", "file", False),
            ("MERGE_REPORTS_SCRIPT_PATH", "Merge Reports script", "Processing & Merging Script 31-5 with sharing.py", "file", False),
            ("NETECO_SCRAPER_SCRIPT_PATH", "NetEco Scraper script", "neteco_continuous 15-5-2026.py", "file", False),
            ("MAE_SCRAPER_SCRIPT_PATH", "MAE Scraper script", "mae_scraper 31-5-26.py", "file", False),
            ("SMARTCARE_CEM_SCRIPT_PATH", "SmartCare CEM script", "SmartCare CEM/SmartCare CEM v11.py", "file", False),
            ("SUBSCRIBERS_FTPS_SCRIPT_PATH", "Subscribers FTPS script", "subscriers with 2G interference with ftp 31-5-26_v2.py", "file", False),
        ],
    },
    {
        "section": "Telegram Bot",
        "fields": [
            ("TELEGRAM_BOT_TOKEN", "Telegram bot token", "", "text", True),
        ],
    },
]

SCRIPT_PATH_KEYS = {
    "Telegram NOC Bot": "TELEGRAM_NOC_BOT_SCRIPT_PATH",
    "Merge Reports": "MERGE_REPORTS_SCRIPT_PATH",
    "NetEco Scraper": "NETECO_SCRAPER_SCRIPT_PATH",
    "MAE Scraper": "MAE_SCRAPER_SCRIPT_PATH",
    "SmartCare CEM": "SMARTCARE_CEM_SCRIPT_PATH",
    "Comprehensive Analysis": "ANALYSIS_SCRIPT_PATH",
    "Subscribers FTPS": "SUBSCRIBERS_FTPS_SCRIPT_PATH",
}

SCRIPT_PATH_DEFAULTS = {
    "Telegram NOC Bot": "telegram_noc_bot.py",
    "Merge Reports": "Processing & Merging Script 31-5 with sharing.py",
    "NetEco Scraper": "neteco_continuous 15-5-2026.py",
    "MAE Scraper": "mae_scraper 31-5-26.py",
    "SmartCare CEM": "SmartCare CEM/SmartCare CEM v11.py",
    "Comprehensive Analysis": "download_analysis_pipeline.py",
    "Subscribers FTPS": "subscriers with 2G interference with ftp 31-5-26_v2.py",
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


class SettingsApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("NAE NET Eco Project Settings")
        self.geometry("980x760")
        self.minsize(820, 620)
        self.variables = {}
        self.show_secrets = tk.BooleanVar(value=False)

        self._build_ui()
        self.load_values()

    def _build_ui(self):
        header = ttk.Frame(self, padding=(14, 12))
        header.pack(fill="x")
        ttk.Label(header, text="Project Settings", font=("Segoe UI", 16, "bold")).pack(side="left")
        ttk.Label(header, text=f"Saved to: {ENV_PATH}", foreground="#555").pack(side="right")

        container = ttk.Frame(self)
        container.pack(fill="both", expand=True, padx=14)

        canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        self.form = ttk.Frame(canvas)
        self.form.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.form, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        row = 0
        for section in SETTINGS:
            label = ttk.Label(self.form, text=section["section"], font=("Segoe UI", 12, "bold"))
            label.grid(row=row, column=0, sticky="w", pady=(16, 6), padx=(2, 8))
            row += 1
            for key, label_text, _default, field_type, is_secret in section["fields"]:
                ttk.Label(self.form, text=label_text).grid(row=row, column=0, sticky="w", padx=(2, 8), pady=3)
                var = tk.StringVar()
                entry = ttk.Entry(self.form, textvariable=var, width=86, show="*" if is_secret else "")
                entry.grid(row=row, column=1, sticky="ew", pady=3)
                self.variables[key] = (var, entry, is_secret)
                if field_type == "dir":
                    ttk.Button(self.form, text="Browse", command=lambda v=var: self.choose_dir(v)).grid(
                        row=row, column=2, padx=(6, 2), pady=3
                    )
                elif field_type == "file":
                    ttk.Button(self.form, text="Browse", command=lambda v=var: self.choose_file(v)).grid(
                        row=row, column=2, padx=(6, 2), pady=3
                    )
                row += 1

        self.form.columnconfigure(1, weight=1)

        footer = ttk.Frame(self, padding=14)
        footer.pack(fill="x")
        ttk.Checkbutton(
            footer,
            text="Show passwords/tokens",
            variable=self.show_secrets,
            command=self.toggle_secret_visibility,
        ).pack(side="left")
        ttk.Button(footer, text="Reload", command=self.load_values).pack(side="right", padx=(8, 0))
        ttk.Button(footer, text="Save Settings", command=self.save_values).pack(side="right", padx=(8, 0))

        runner = ttk.LabelFrame(self, text="Run Script", padding=10)
        runner.pack(fill="x", padx=14, pady=(0, 14))
        self.script_choice = tk.StringVar(value="Telegram NOC Bot")
        ttk.Combobox(runner, textvariable=self.script_choice, values=list(SCRIPTS), state="readonly", width=28).pack(
            side="left"
        )
        ttk.Button(runner, text="Run in new window", command=self.run_script).pack(side="left", padx=8)
        ttk.Button(runner, text="Run Continuous Set", command=self.run_continuous_scripts).pack(side="left", padx=8)
        ttk.Label(runner, text="Settings are saved before launch.", foreground="#555").pack(side="left", padx=8)

        analysis_runner = ttk.LabelFrame(self, text="Comprehensive Analysis", padding=10)
        analysis_runner.pack(fill="x", padx=14, pady=(0, 14))
        ttk.Button(analysis_runner, text="Run Latest Analysis", command=self.run_analysis).pack(side="left", padx=8)
        ttk.Button(analysis_runner, text="Run SmartCare + Update History", command=self.run_full_smartcare_analysis).pack(side="left", padx=8)
        ttk.Button(analysis_runner, text="Schedule Sunday 02:00", command=self.schedule_weekly_task).pack(side="left", padx=8)
        ttk.Button(analysis_runner, text="Open Output Folder", command=self.open_analysis_output).pack(side="left", padx=8)
        ttk.Label(analysis_runner, text="Uses latest Comprehensive_Analysis file in source folder. Weekly schedule can be created.", foreground="#555").pack(side="left", padx=8)

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

    def run_analysis(self):
        values = self.current_values()
        if not self.save_values(show_message=False):
            return

        if not self.ensure_smartcare_ran_yesterday(values):
            return

        script_path = resolve_script_path("Comprehensive Analysis", values)
        if not script_path or not script_path.exists():
            messagebox.showerror("Missing script", f"Comprehensive analysis script not found: {script_path or '<not set>'}")
            return

        source_dir = Path(values.get("ANALYSIS_SOURCE_DIR") or str(Path.home() / "Downloads"))
        output_dir = Path(values.get("ANALYSIS_OUTPUT_DIR") or str(Path.home() / "Downloads" / "Processed_Analysis"))

        if not source_dir.exists():
            messagebox.showerror("Missing folder", f"Source folder does not exist:\n{source_dir}")
            return

        output_dir.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update(values)
        creationflags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0

        history_file = Path(values.get("ANALYSIS_HISTORY_FILE") or str(output_dir / "Comprehensive_Analysis_Historical.xlsx"))
        subprocess.Popen(
            [
                sys.executable,
                str(script_path),
                "--source-dir",
                str(source_dir),
                "--output-dir",
                str(output_dir),
                "--history-file",
                str(history_file),
            ],
            cwd=PROJECT_ROOT,
            env=env,
            creationflags=creationflags,
        )
        messagebox.showinfo("Started", f"Started Comprehensive Analysis using:\n{script_path}")

    def run_full_smartcare_analysis(self):
        values = self.current_values()
        if not self.save_values(show_message=False):
            return

        wrapper_script = PROJECT_ROOT / "run_smartcare_analysis_task.py"
        if not wrapper_script.exists():
            messagebox.showerror(
                "Missing script",
                f"SmartCare analysis wrapper not found:\n{wrapper_script}\n\nPlease ensure that file exists in the project root.",
            )
            return

        smartcare_script = resolve_script_path("SmartCare CEM", values)
        analysis_script = resolve_script_path("Comprehensive Analysis", values)
        if not smartcare_script or not smartcare_script.exists():
            messagebox.showerror("Missing script", f"SmartCare CEM script not found: {smartcare_script or '<not set>'}")
            return
        if not analysis_script or not analysis_script.exists():
            messagebox.showerror("Missing script", f"Comprehensive analysis script not found: {analysis_script or '<not set>'}")
            return

        download_dir = Path(values.get("SMARTCARE_DOWNLOAD_DIR") or str(Path.home() / "Downloads"))
        smartcare_output_dir = Path(values.get("SMARTCARE_OUTPUT_DIR") or str(Path.home() / "Downloads" / "SmartCare_Exports"))
        analysis_output_dir = Path(values.get("ANALYSIS_OUTPUT_DIR") or str(Path.home() / "Downloads" / "Processed_Analysis"))
        history_file = Path(values.get("ANALYSIS_HISTORY_FILE") or str(analysis_output_dir / "Comprehensive_Analysis_Historical.xlsx"))

        if not download_dir.exists():
            messagebox.showerror("Missing folder", f"SmartCare download folder does not exist:\n{download_dir}")
            return
        if not smartcare_output_dir.exists():
            smartcare_output_dir.mkdir(parents=True, exist_ok=True)
        if not analysis_output_dir.exists():
            analysis_output_dir.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env.update(values)
        creationflags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
        cmd = [
            sys.executable,
            str(wrapper_script),
            "--smartcare-script",
            str(smartcare_script),
            "--analysis-script",
            str(analysis_script),
            "--download-dir",
            str(download_dir),
            "--smartcare-output-dir",
            str(smartcare_output_dir),
            "--analysis-output-dir",
            str(analysis_output_dir),
            "--history-file",
            str(history_file),
            "--login-attempts",
            "2",
        ]

        subprocess.Popen(cmd, cwd=PROJECT_ROOT, env=env, creationflags=creationflags)
        messagebox.showinfo("Started", f"Started full SmartCare + analysis task:\n{wrapper_script}")

    def schedule_weekly_task(self):
        if os.name != "nt":
            messagebox.showerror("Unsupported", "Scheduled task creation is only supported on Windows.")
            return

        values = self.current_values()
        if not self.save_values(show_message=False):
            return

        wrapper_script = PROJECT_ROOT / "run_smartcare_analysis_task.py"
        if not wrapper_script.exists():
            messagebox.showerror(
                "Missing script",
                f"SmartCare analysis wrapper not found:\n{wrapper_script}\n\nPlease ensure that file exists in the project root.",
            )
            return

        smartcare_script = resolve_script_path("SmartCare CEM", values)
        analysis_script = resolve_script_path("Comprehensive Analysis", values)
        if not smartcare_script or not smartcare_script.exists():
            messagebox.showerror("Missing script", f"SmartCare CEM script not found: {smartcare_script or '<not set>'}")
            return
        if not analysis_script or not analysis_script.exists():
            messagebox.showerror("Missing script", f"Comprehensive analysis script not found: {analysis_script or '<not set>'}")
            return

        download_dir = Path(values.get("SMARTCARE_DOWNLOAD_DIR") or str(Path.home() / "Downloads"))
        smartcare_output_dir = Path(values.get("SMARTCARE_OUTPUT_DIR") or str(Path.home() / "Downloads" / "SmartCare_Exports"))
        analysis_output_dir = Path(values.get("ANALYSIS_OUTPUT_DIR") or str(Path.home() / "Downloads" / "Processed_Analysis"))
        history_file = Path(values.get("ANALYSIS_HISTORY_FILE") or str(analysis_output_dir / "Comprehensive_Analysis_Historical.xlsx"))
        task_name = values.get("SCHEDULE_TASK_NAME") or "MAENETEcoSmartCareAnalysisWeekly"

        task_cmd = (
            f'"{sys.executable}" "{wrapper_script}" '
            f'--smartcare-script "{smartcare_script}" '
            f'--analysis-script "{analysis_script}" '
            f'--download-dir "{download_dir}" '
            f'--smartcare-output-dir "{smartcare_output_dir}" '
            f'--analysis-output-dir "{analysis_output_dir}" '
            f'--history-file "{history_file}" '
            f'--login-attempts 2'
        )
        schtasks_args = [
            "schtasks",
            "/Create",
            "/SC",
            "WEEKLY",
            "/D",
            "SUN",
            "/ST",
            "02:00",
            "/TN",
            task_name,
            "/TR",
            task_cmd,
            "/F",
        ]

        result = subprocess.run(schtasks_args, capture_output=True, text=True)
        if result.returncode == 0:
            messagebox.showinfo(
                "Scheduled",
                f"Scheduled weekly task '{task_name}' for Sunday at 02:00.\nYou can manage it in Task Scheduler.",
            )
        else:
            messagebox.showerror(
                "Schedule failed",
                f"Could not create scheduled task.\n{result.stdout}\n{result.stderr}",
            )

    def smartcare_ran_yesterday(self, output_dir: Path) -> bool:
        if not output_dir.exists():
            return False

        yesterday = (datetime.now() - timedelta(days=1)).date()
        for path in output_dir.iterdir():
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".xlsx", ".xls", ".csv", ".zip"}:
                continue
            try:
                modified_date = datetime.fromtimestamp(path.stat().st_mtime).date()
            except OSError:
                continue
            if modified_date == yesterday:
                return True
        return False

    def ensure_smartcare_ran_yesterday(self, values: dict) -> bool:
        download_dir = Path(values.get("SMARTCARE_DOWNLOAD_DIR") or str(Path.home() / "Downloads"))
        output_dir = Path(values.get("SMARTCARE_OUTPUT_DIR") or str(Path.home() / "Downloads" / "SmartCare_Exports"))

        if self.smartcare_ran_yesterday(output_dir):
            return True

        messagebox.showinfo(
            "SmartCare CEM",
            "SmartCare CEM did not produce yesterday's file. Running SmartCare CEM now...",
        )

        script_path = resolve_script_path("SmartCare CEM", values)
        if not script_path or not script_path.exists():
            messagebox.showerror("Missing script", f"SmartCare CEM script not found: {script_path or '<not set>'}")
            return False

        env = os.environ.copy()
        env.update(values)
        env["SMARTCARE_DOWNLOAD_DIR"] = str(download_dir)
        env["SMARTCARE_OUTPUT_DIR"] = str(output_dir)
        creationflags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0

        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(script_path),
                    "--download-dir",
                    str(download_dir),
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=PROJECT_ROOT,
                env=env,
                creationflags=creationflags,
                timeout=1200,
            )
        except subprocess.TimeoutExpired:
            messagebox.showerror(
                "SmartCare CEM",
                "SmartCare CEM did not finish within the time limit. Check the browser or logs.",
            )
            return False

        if result.returncode != 0:
            messagebox.showerror(
                "SmartCare CEM",
                f"SmartCare CEM exited with code {result.returncode}. Check logs and retry.",
            )
            return False

        return True

    def open_analysis_output(self):
        values = self.current_values()
        output_dir = Path(values.get("ANALYSIS_OUTPUT_DIR") or str(Path.home() / "Downloads" / "Processed_Analysis"))
        if not output_dir.exists():
            messagebox.showerror("Missing folder", f"Output folder does not exist:\n{output_dir}")
            return

        if os.name == "nt":
            os.startfile(output_dir)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(output_dir)])
        else:
            subprocess.Popen(["xdg-open", str(output_dir)])

    def run_script(self):
        script_name = self.script_choice.get()
        self.run_scripts([script_name])

    def run_continuous_scripts(self):
        self.run_scripts(CONTINUOUS_SCRIPTS)

    def run_scripts(self, script_names):
        script_names = tuple(script_names)
        values = self.current_values()
        errors = []
        for script_name in script_names:
            errors.extend(f"{script_name}: {error}" for error in self.validate_values(script_name))

        for key in INTEGER_FIELDS:
            value = values.get(key, "")
            if value and not value.isdigit():
                errors.append(f"{key} must be a whole number.")

        if errors:
            messagebox.showerror("Missing settings", "\n".join(errors[:16]))
            return

        if not self.save_values(show_message=False):
            return

        missing_scripts = []
        for script_name in script_names:
            script = resolve_script_path(script_name, values)
            if not script or not script.exists():
                missing_scripts.append(f"{script_name}: {script or '<not set>'}")

        if missing_scripts:
            messagebox.showerror("Missing script", "\n".join(missing_scripts))
            return

        env = os.environ.copy()
        env.update(self.current_values())
        creationflags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0

        for script_name in script_names:
            script = resolve_script_path(script_name, values)
            subprocess.Popen([sys.executable, str(script)], cwd=PROJECT_ROOT, env=env, creationflags=creationflags)

        if len(script_names) > 1:
            messagebox.showinfo("Started", "Started:\n" + "\n".join(script_names))

if __name__ == "__main__":
    SettingsApp().mainloop()
