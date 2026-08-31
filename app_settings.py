"""The .env form schema plus read/write helpers - kept separate from
script_registry.py on purpose (mixing "what scripts exist" with "what
settings exist" into one file is part of why the old Tkinter control_panel.py
became unmanageable). Framework-free: any UI (dashboard, CLI) can build on
top of this.
"""
import os
import subprocess
from pathlib import Path

from project_config import ENV_PATH, load_env_file, parse_env_file

DEFAULT_DATA_ROOT = str(Path.home() / "Desktop" / "Libyana_Data")


def data_path(subfolder: str) -> str:
    return str(Path(DEFAULT_DATA_ROOT) / subfolder)


# ============================================================
# SETTINGS DEFINITION (.env fields, grouped into sections)
# Each field: (key, label, default, field_type, is_secret)
# field_type: "text" | "dir" | "file"
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
            ("MAE_DOWNLOAD_DIR", "MAE download folder", data_path("Input/Downloads/MAE_Current"), "dir", False),
            ("MAE_EXPORT_BASE_DIR", "MAE export base folder", data_path("Output/Current_Alarms"), "dir", False),
            ("MAE_WAIT_TIMEOUT", "MAE wait timeout seconds", "45", "text", False),
            ("MAE_INTERVAL_SECONDS", "MAE interval seconds", "300", "text", False),
            ("MAE_HISTORICAL_URL", "MAE Historical Alarms URL (last 7 days)",
             "https://10.171.68.68:31943/ossfacewebsite/index.html#Access/fmHistoryAlarm@@fmAlarmApp_historyAlarm_templateId143%26tabTitle%3DHistorical%20Alarms%20MAE%20last%207days?maeUrl=%2Feviewwebsite%2Findex.html%23path%3D%2FfmAlarmApp%2FfmHistoryAlarm%26templateId%3D143%26fmPage%3Dtrue%26_t%3D1787561843039&maeTitle=Historical%20Alarms%20-%20%5BHistorical%20Alarms%20MAE%20last%207days%5D&loadType=iframe",
             "text", False),
            ("MAE_HISTORICAL_DOWNLOAD_DIR", "MAE Historical download folder (must differ from MAE_DOWNLOAD_DIR)",
             data_path("Input/Downloads/MAE_Historical"), "dir", False),
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
            ("NETECO_DOWNLOAD_DIR", "NetEco download folder", data_path("Input/Downloads/NetEco_Current"), "dir", False),
            ("NETECO_EXPORT_BASE_DIR", "NetEco export base folder", data_path("Output/Current_Alarms"), "dir",
             False),
            ("NETECO_WAIT_TIMEOUT", "NetEco wait timeout seconds", "60", "text", False),
            ("NETECO_INTERVAL_SECONDS", "NetEco interval seconds", "300", "text", False),
            ("NETECO_DOWNLOAD_TIMEOUT_SECONDS", "Download timeout seconds", "180", "text", False),
            ("NETECO_DOWNLOAD_STABLE_SECONDS", "Download stable seconds", "5", "text", False),
            ("NETECO_RETRY_DELAY_SECONDS", "Retry delay seconds", "60", "text", False),
            ("NETECO_MAX_CONSECUTIVE_FAILURES", "Max consecutive failures", "5", "text", False),
            ("NETECO_PORT_CHECK_TIMEOUT", "Port check timeout seconds", "5", "text", False),
            ("NETECO_ALL_DOWNLOAD_DIR", "NetEco All Alarms download folder (must differ from NETECO_DOWNLOAD_DIR)",
             data_path("Input/Downloads/AllAlarms"), "dir", False),
            ("NETECO_HISTORICAL_ALARMS_URL", "NetEco Historical Alarms URL",
             "https://10.171.68.2:31943/eviewwebsite/index.html#path=/fmAlarmApp/fmHistoryAlarm&_t=1787594162",
             "text", False),
            ("NETECO_HISTORICAL_DOWNLOAD_DIR", "NetEco Historical download folder (must differ from NETECO_DOWNLOAD_DIR)",
             data_path("Input/Downloads/NetEco_Historical"), "dir", False),
            ("NETECO_HISTORICAL_EXPORT_BASE_DIR", "NetEco Historical Alarms export folder",
             data_path("Output/Historical_Alarms"), "dir", False),
            ("NETECO_HISTORICAL_INTERVAL_SECONDS", "NetEco Historical re-export interval seconds", "420", "text",
             False),
            ("NETECO_HISTORICAL_DOWNLOAD_TIMEOUT_SECONDS", "NetEco Historical download timeout seconds", "600",
             "text", False),
        ],
    },
    {
        "section": "NCE Scraper",
        "fields": [
            ("NCE_USERNAME", "NCE username", "", "text", False),
            ("NCE_PASSWORD", "NCE password", "", "text", True),
            ("NCE_WAIT_TIMEOUT", "NCE wait timeout seconds", "45", "text", False),
            ("NCE_ACTIVE_URL", "NCE Active (Current) Alarms URL",
             "https://10.171.69.101:31943/eviewwebsite/index.html?nceapp=Common_Alarm#path=/fmAlarmApp/fmAlarmView&_t=1788010819",
             "text", False),
            ("NCE_ACTIVE_DOWNLOAD_DIR", "NCE Active download folder", data_path("Input/Downloads/NCE_Active"),
             "dir", False),
            ("NCE_ACTIVE_EXPORT_BASE_DIR", "NCE Active Alarms export folder",
             data_path("Output/NCE_Current_Alarms"), "dir", False),
            ("NCE_ACTIVE_INTERVAL_SECONDS", "NCE Active re-export interval seconds", "300", "text", False),
            ("NCE_ACTIVE_DOWNLOAD_TIMEOUT", "NCE Active download timeout seconds", "600", "text", False),
            ("NCE_HISTORICAL_URL", "NCE Historical Alarms URL",
             "https://10.171.69.101:31943/eviewwebsite/index.html#path=/fmAlarmApp/fmHistoryAlarm&templateId=15&fmPage=true&_t=1788008434371",
             "text", False),
            ("NCE_HISTORICAL_DOWNLOAD_DIR", "NCE Historical download folder (must differ from NCE_ACTIVE_DOWNLOAD_DIR)",
             data_path("Input/Downloads/NCE_Historical"), "dir", False),
            ("NCE_HISTORICAL_EXPORT_BASE_DIR", "NCE Historical Alarms export folder",
             data_path("Output/NCE_Historical_Alarms"), "dir", False),
            ("NCE_HISTORICAL_INTERVAL_SECONDS", "NCE Historical re-export interval seconds", "300", "text", False),
            ("NCE_HISTORICAL_DOWNLOAD_TIMEOUT", "NCE Historical download timeout seconds", "600", "text", False),
        ],
    },
    {
        "section": "Historical Alarms Analysis",
        "fields": [
            ("HISTORICAL_ANALYSIS_INTERVAL_SECONDS", "Historical analysis loop interval seconds", "600", "text",
             False),
            ("HISTORICAL_ANALYSIS_OUTPUT_DIR", "Historical analysis output folder",
             data_path("Output/Historical_Alarms_Analysis"), "dir", False),
            ("HISTORICAL_SHARED_FOLDER", "Historical analysis shared/live report folder",
             data_path("Output/Historical_Alarms_Analysis/Shared"), "dir", False),
            ("HISTORICAL_LEDGER_PATH", "Historical alarm ledger file (chronic-offender tracking)",
             data_path("Output/Historical_Alarms_Analysis/alarm_ledger.csv"), "file", False),
            ("HISTORICAL_CHRONIC_THRESHOLD", "Chronic offender threshold (occurrences)", "5", "text", False),
            ("HISTORICAL_RAW_EXPORT_RETENTION_DAYS", "Raw historical export retention (days)", "3", "text", False),
            ("HISTORICAL_RAW_SHEET_LOOKBACK_DAYS", "Raw sheet lookback window in the report (days)", "30", "text",
             False),
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
            ("SMARTCARE_DOWNLOAD_DIR", "SmartCare download folder", data_path("Input/Downloads/SmartCare"), "dir", False),
            ("SMARTCARE_OUTPUT_DIR", "SmartCare output folder", data_path("Output/SmartCare_Exports"), "dir", False),
            ("SMARTCARE_EXPORT_BASE_DIR", "SmartCare export base folder", data_path("Output/Current_Alarms"), "dir",
             False),
            ("SMARTCARE_EXPORT_TASK_TIMEOUT", "SmartCare export task timeout seconds", "300", "text", False),
            ("SMARTCARE_POLL_INTERVAL", "SmartCare poll interval seconds", "15", "text", False),
        ],
    },
    {
        "section": "Weekly Device Penetration",
        "fields": [
            ("WEEKLY_DEVICE_PENETRATION_LOGIN_URL", "Login URL (blank = fall back to SmartCare login URL)", "",
             "text", False),
            ("WEEKLY_DEVICE_PENETRATION_TARGET_DASHBOARD_URL", "Target dashboard URL",
             "https://10.171.200.52:38443/portal-web/portal/homepage.html#SEQ.MBB_TRAFFIC_ANALYSIS.21560",
             "text", False),
            ("WEEKLY_DEVICE_PENETRATION_EXPORT_TASK_URL", "Export task URL (blank = fall back to SmartCare export task URL)",
             "", "text", False),
            ("WEEKLY_DEVICE_PENETRATION_USERNAME", "Username (blank = fall back to SmartCare username)", "", "text", False),
            ("WEEKLY_DEVICE_PENETRATION_PASSWORD", "Password (blank = fall back to SmartCare password)", "", "text", True),
            ("WEEKLY_DEVICE_PENETRATION_DOWNLOAD_DIR", "Download folder",
             data_path("Input/Downloads/Weekly_Device_Penetration"), "dir", False),
            ("WEEKLY_DEVICE_PENETRATION_OUTPUT_DIR", "Output folder",
             data_path("Output/Weekly_Device_Penetration_Exports"), "dir", False),
            ("WEEKLY_DEVICE_PENETRATION_EXPORT_TASK_TIMEOUT", "Export task timeout seconds", "300", "text", False),
            ("WEEKLY_DEVICE_PENETRATION_POLL_INTERVAL", "Poll interval seconds", "15", "text", False),
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

INTEGER_FIELDS = {
    "MERGE_INTERVAL_SECONDS", "NOC_ANALYSIS_INTERVAL_SECONDS",
    "MAE_WAIT_TIMEOUT", "MAE_INTERVAL_SECONDS", "MAE_HISTORICAL_DOWNLOAD_TIMEOUT", "MAE_HISTORICAL_INTERVAL_SECONDS",
    "SMARTCARE_EXPORT_TASK_TIMEOUT", "SMARTCARE_POLL_INTERVAL",
    "WEEKLY_DEVICE_PENETRATION_EXPORT_TASK_TIMEOUT", "WEEKLY_DEVICE_PENETRATION_POLL_INTERVAL",
    "NETECO_WAIT_TIMEOUT", "NETECO_INTERVAL_SECONDS", "NETECO_DOWNLOAD_TIMEOUT_SECONDS",
    "NETECO_DOWNLOAD_STABLE_SECONDS", "NETECO_RETRY_DELAY_SECONDS", "NETECO_MAX_CONSECUTIVE_FAILURES",
    "NETECO_PORT_CHECK_TIMEOUT", "FTP_PORT", "FTP_TIMEOUT_SECONDS",
    "NETECO_HISTORICAL_INTERVAL_SECONDS", "NETECO_HISTORICAL_DOWNLOAD_TIMEOUT_SECONDS",
    "NCE_WAIT_TIMEOUT", "NCE_ACTIVE_INTERVAL_SECONDS", "NCE_ACTIVE_DOWNLOAD_TIMEOUT",
    "NCE_HISTORICAL_INTERVAL_SECONDS", "NCE_HISTORICAL_DOWNLOAD_TIMEOUT",
    "HISTORICAL_ANALYSIS_INTERVAL_SECONDS", "HISTORICAL_CHRONIC_THRESHOLD", "HISTORICAL_RAW_EXPORT_RETENTION_DAYS",
    "HISTORICAL_RAW_SHEET_LOOKBACK_DAYS",
}

FIELD_BY_KEY = {key: (label, default, field_type, is_secret)
                for section in SETTINGS
                for key, label, default, field_type, is_secret in section["fields"]}


def read_env_file():
    """Current .env values, with SETTINGS defaults filled in for anything missing."""
    load_env_file()
    values = parse_env_file()
    for section in SETTINGS:
        for key, _label, default, _field_type, _secret in section["fields"]:
            values.setdefault(key, os.getenv(key, default))
    return values


def quote_env_value(value):
    value = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{value}"'


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


def validate_values(values, required_keys=()):
    errors = []
    for key in required_keys:
        if not values.get(key):
            errors.append(f"{key} is required.")
    for key in INTEGER_FIELDS:
        value = values.get(key, "")
        if value and not str(value).isdigit():
            errors.append(f"{key} must be a whole number.")
    return errors


def write_env_file(values):
    """Persist `values` (a dict of key -> string) back to .env, preserving the
    SETTINGS section grouping/comments. Missing keys fall back to their
    SETTINGS default rather than raising, since callers (e.g. a dashboard
    form) may only pass a subset of keys."""
    dir_keys = [key for section in SETTINGS for key, _label, _default, field_type, _secret in section["fields"]
                if field_type == "dir"]
    for key in dir_keys:
        path = values.get(key)
        if path:
            try:
                Path(path).mkdir(parents=True, exist_ok=True)
            except OSError:
                pass

    lines = ["# Libyana Automation project settings",
             "# This file contains secrets and is intentionally ignored by Git.", ""]
    for section in SETTINGS:
        lines.append(f"# {section['section']}")
        for key, _label, default, _field_type, _secret in section["fields"]:
            lines.append(f"{key}={quote_env_value(values.get(key, default))}")
        lines.append("")

    prepare_env_file_for_write()
    ENV_PATH.write_text("\n".join(lines), encoding="utf-8")
    hide_env_file()
    load_env_file(override=True)
    os.environ.update(values)
