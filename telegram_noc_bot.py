import os
import json
import re
import tempfile
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import Conflict
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters
from project_config import env_path, env_str

# ================= CONFIGURATION =================
BASE_DIR = env_path("NOC_BASE_DIR", r"c:\Current_Alarms")
TOKEN_FILE = Path(__file__).with_name("TelegramBot_info.txt")
MAX_MESSAGE_CHARS = 3900
NO_POWER_TEXT = "Check TX/Link (No Power Alarm)"
POWER_ALARMS = ("Mains Failure", "BLVD", "LLVD")
LOCK_PATH = Path(tempfile.gettempdir()) / "telegram_noc_bot.lock"
REPORT_NAME_RE = re.compile(r"^Final_NOC_Report_(\d{4}-\d{2}-\d{2})_(\d{4})\.xlsx$")
TOKEN_RE = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b")
# =================================================

LOG_DIR = Path(__file__).with_name("logs")
LOG_PATH = LOG_DIR / "telegram_noc_bot_runtime.log"
LOG_DIR.mkdir(parents=True, exist_ok=True)


class SecretRedactionFilter(logging.Filter):
    """Prevent bot tokens from being persisted if a dependency logs request URLs."""
    def filter(self, record):
        message = record.getMessage()
        redacted = TOKEN_RE.sub("<redacted-token>", message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)
for handler in logging.getLogger().handlers:
    handler.addFilter(SecretRedactionFilter())
# HTTP request URLs include the token; they do not belong in normal runtime logs.
logging.getLogger("httpx").setLevel(logging.WARNING)

_REPORT_CACHE = {}


def read_bot_token():
    env_token = env_str("TELEGRAM_BOT_TOKEN").strip()
    if env_token:
        return env_token

    if not TOKEN_FILE.exists():
        return ""

    match = TOKEN_RE.search(TOKEN_FILE.read_text(encoding="utf-8", errors="ignore"))
    return match.group(0) if match else ""


TOKEN = read_bot_token()

# Simplified Menu
MENU_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("📊 Summary", callback_data="summary")],
    [InlineKeyboardButton("🔍 Search Site", callback_data="search_site")],
    [InlineKeyboardButton("📄 Send Report", callback_data="report")],
])


def acquire_single_instance_lock():
    lock_file = LOCK_PATH.open("a+")
    try:
        if os.name == "nt":
            import msvcrt
            lock_file.seek(0)
            try:
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                lock_file.close()
                return None
        else:
            import fcntl
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                lock_file.close()
                return None

        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(f"pid={os.getpid()}\nstarted={datetime.now().isoformat(timespec='seconds')}\n")
        lock_file.flush()
        return lock_file
    except Exception:
        lock_file.close()
        raise


def clean_value(value, default="-"):
    if pd.isna(value):
        return default
    text = str(value).replace("\t", " ").strip()
    return text if text else default


def date_folder_key(path):
    try:
        return datetime.strptime(path.name, "%Y-%m-%d")
    except ValueError:
        return datetime.fromtimestamp(path.stat().st_mtime)


def report_timestamp(path):
    match = REPORT_NAME_RE.match(path.name)
    if not match:
        return None
    try:
        return datetime.strptime(" ".join(match.groups()), "%Y-%m-%d %H%M")
    except ValueError:
        return None


def report_sort_key(path):
    name_time = report_timestamp(path)
    if name_time:
        return name_time, datetime.fromtimestamp(path.stat().st_mtime)
    return datetime.min, datetime.fromtimestamp(path.stat().st_mtime)


def latest_report_path():
    if not BASE_DIR.exists():
        return None

    date_folders = [
        d for d in BASE_DIR.iterdir()
        if d.is_dir() and d.name[:4].isdigit() and len(d.name) == 10
    ]
    if date_folders:
        latest_folder = max(date_folders, key=date_folder_key)
        files = [
            p for p in latest_folder.glob("Final_NOC_Report_*.xlsx")
            if p.is_file() and not p.name.startswith("~$")
        ]
        if files:
            return max(files, key=report_sort_key)

    files = [
        p for p in BASE_DIR.rglob("Final_NOC_Report_*.xlsx")
        if p.is_file() and not p.name.startswith("~$")
    ]
    return max(files, key=report_sort_key) if files else None


def file_time(path):
    if not path:
        return "-"
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")


def load_report():
    path = latest_report_path()
    if not path:
        return None, {}, f"No Excel report found under {BASE_DIR}."

    try:
        stat = path.stat()
        cache_key = (str(path), stat.st_mtime_ns, stat.st_size)
        if cache_key not in _REPORT_CACHE:
            _REPORT_CACHE.clear()
            _REPORT_CACHE[cache_key] = pd.read_excel(path, sheet_name=None)
        sheets = {name: df.copy() for name, df in _REPORT_CACHE[cache_key].items()}
        return path, sheets, None
    except Exception as exc:
        logger.exception("Could not read Excel report: %s", path)
        return path, {}, f"Could not read Excel report: {exc}"


def normalize_site_name(value):
    """Remove suffixes like (FTTS), (FN), etc."""
    if pd.isna(value):
        return ""
    value = str(value)
    for suffix in ["(FTTS)", "(FN)", "(FN)", "(FTTS)", "_NEW"]:
        value = value.replace(suffix, "")
    return value.strip()


def clean_summary_df(df):
    df = df.copy()
    if df.empty:
        return df

    unnamed_cols = [c for c in df.columns if str(c).startswith("Unnamed:")]
    df.drop(columns=unnamed_cols, inplace=True, errors="ignore")
    df.dropna(how="all", inplace=True)

    if "Site Name" in df.columns:
        df["Site Name"] = df["Site Name"].map(normalize_site_name)

    return df


def get_summary_stats():
    """Extract statistics including MAE and NetEco sheets."""
    path, sheets, error = load_report()
    if error or not path:
        return None, error

    summary = clean_summary_df(sheets.get("Current Alarms Summary", pd.DataFrame()))
    neteco = sheets.get("NetEco Current Alarms", pd.DataFrame()).copy()
    mae = sheets.get("MAE Current Alarms", pd.DataFrame()).copy()

    # Clean site names in all sheets
    for df in [neteco, mae]:
        if not df.empty and "Site Name" in df.columns:
            df["Site Name"] = df["Site Name"].map(normalize_site_name)

    if summary.empty:
        return path, "Summary sheet is empty."

    # Extract metrics - convert to integers
    metrics = {}
    if "Metric Description" in summary.columns and "Value" in summary.columns:
        for _, row in summary[["Metric Description", "Value"]].dropna(how="all").iterrows():
            desc = clean_value(row.get("Metric Description"), "")
            val = row.get("Value")
            # Convert to integer if it's a number
            try:
                if isinstance(val, (int, float)):
                    val = int(val)
                else:
                    val = clean_value(val)
            except (ValueError, TypeError):
                val = clean_value(val)
            if desc:
                metrics[desc] = val

    disconnected_count = summary['Site Name'].nunique() if 'Site Name' in summary.columns else 0

    mains_failure_count = 0
    if "Power Reason (NOC)" in summary.columns:
        mains_failure_count = summary[
            summary["Power Reason (NOC)"].astype(str).str.contains("Mains Failure", na=False)
        ]['Site Name'].nunique()

    no_power_sites = []
    if "Power Reason (NOC)" in summary.columns and "Site Name" in summary.columns:
        no_power_mask = summary["Power Reason (NOC)"].fillna("").eq(NO_POWER_TEXT)
        no_power_sites = summary[no_power_mask]["Site Name"].drop_duplicates().tolist()

    return path, {
        'report_time': file_time(path),
        'disconnected_count': disconnected_count,
        'mains_failure_count': mains_failure_count,
        'no_power_sites': no_power_sites,
        'metrics': metrics,
        'summary': summary,
        'neteco': neteco,
        'mae': mae
    }


def format_summary_message(stats):
    """Format the summary message - clean and concise."""
    if isinstance(stats, str):
        return stats

    lines = [
        "📊 **NOC Report Summary**",
        "=" * 30,
        f"📅 Updated: {stats['report_time']}",
        "",
        f"🔴 **NE Is Disconnected:** {stats['disconnected_count']} sites",
        f"⚡ **Mains Failure:** {stats['mains_failure_count']} sites",
    ]

    if stats.get('metrics'):
        lines.append("")
        for desc, val in stats['metrics'].items():
            lines.append(f"• {desc}: {val}")

    no_power = stats.get('no_power_sites', [])
    if no_power:
        lines.append("")
        lines.append(f"🟡 **No Power Alarm (Check TX/Link):** {len(no_power)} sites")
        for site in no_power[:20]:
            lines.append(f"  - {site}")
        if len(no_power) > 20:
            lines.append(f"  ...and {len(no_power) - 20} more")

    return "\n".join(lines)


# =========================================================
# SEARCH SITE - CHECKS MAE FIRST, THEN NETECO
# =========================================================

def search_site_simple(site_query):
    """
    Site search that checks MAE first, then NetEco if not found.
    EXACT MATCH ONLY (case-insensitive).
    Removes suffixes like (FN), (FTTS) for matching.
    """
    path, stats = get_summary_stats()
    if isinstance(stats, str):
        return stats

    summary = stats.get('summary')
    neteco = stats.get('neteco', pd.DataFrame())
    mae = stats.get('mae', pd.DataFrame())

    # Normalize the query
    query = site_query.strip().upper()
    query_clean = normalize_site_name(query)

    # =========================================================
    # STEP 1: Search in MAE (exact match, ignoring suffixes)
    # =========================================================
    mae_match = None
    mae_site_name = None
    mae_found = False

    if not mae.empty:
        mae_copy = mae.copy()
        if "Site Name" in mae_copy.columns:
            mae_copy["Site Name Clean"] = mae_copy["Site Name"].astype(str).map(normalize_site_name)
            mae_rows = mae_copy[mae_copy["Site Name Clean"].str.upper() == query_clean]
            if not mae_rows.empty:
                mae_match = mae_rows.iloc[0]
                mae_site_name = clean_value(mae_rows.iloc[0].get('Site Name'))
                mae_found = True

        if not mae_found and "MO Name" in mae.columns:
            mae_copy["MO Name Clean"] = mae_copy["MO Name"].astype(str).map(normalize_site_name)
            mae_rows = mae_copy[mae_copy["MO Name Clean"].str.upper() == query_clean]
            if not mae_rows.empty:
                mae_match = mae_rows.iloc[0]
                mae_site_name = clean_value(mae_rows.iloc[0].get('MO Name'))
                mae_found = True

    # =========================================================
    # STEP 2: If not found in MAE, search in NetEco
    # =========================================================
    neteco_match = None
    neteco_site_name = None
    neteco_found = False

    if not mae_found and not neteco.empty and "Site Name" in neteco.columns:
        neteco_copy = neteco.copy()
        neteco_copy["Site Name Clean"] = neteco_copy["Site Name"].astype(str).map(normalize_site_name)
        neteco_rows = neteco_copy[neteco_copy["Site Name Clean"].str.upper() == query_clean]
        if not neteco_rows.empty:
            neteco_match = neteco_rows.iloc[0]
            neteco_site_name = clean_value(neteco_rows.iloc[0].get('Site Name'))
            neteco_found = True

    # =========================================================
    # STEP 3: Search in Summary
    # =========================================================
    summary_match = None
    if not summary.empty and "Site Name" in summary.columns:
        summary_copy = summary.copy()
        summary_copy["Site Name Clean"] = summary_copy["Site Name"].astype(str).map(normalize_site_name)
        summary_rows = summary_copy[summary_copy["Site Name Clean"].str.upper() == query_clean]
        if not summary_rows.empty:
            summary_match = summary_rows.iloc[0]

    # =========================================================
    # STEP 4: If no matches found anywhere
    # =========================================================
    if not mae_found and not neteco_found and summary_match is None:
        return (
            f"❌ Site '{site_query}' not found in the report.\n\n"
            f"📋 **Tip:** Make sure you typed the exact site name.\n"
            f"📋 **Example:** AGFT001, ABZD001, COAST073"
        )

    # Determine the exact site name from the report
    exact_site_name = site_query.upper()
    if mae_site_name:
        exact_site_name = mae_site_name
    elif neteco_site_name:
        exact_site_name = neteco_site_name
    elif summary_match is not None and "Site Name" in summary_match:
        exact_site_name = clean_value(summary_match.get('Site Name'))

    # =========================================================
    # STEP 5: Build response
    # =========================================================
    lines = [
        f"🔍 **Site Search Results**",
        "=" * 40,
        f"📡 **Site: {exact_site_name}**",
        f"📅 Report: {stats['report_time']}",
        "",
    ]

    # ----- MAE Status -----

    if mae_found and mae_match is not None:
        lines.append("📌 **MAE Status (Disconnected):**")
        lines.append(f"  • Alarm: {clean_value(mae_match.get('Name'))}")
        lines.append(f"  • Last Occurred: {clean_value(mae_match.get('Last Occurred'))}")
        lines.append("  • Status: 🔴 **DISCONNECTED**")
    else:
        lines.append("📌 **MAE Status:**")
        lines.append("  • Status: 🟢 **No Disconnection Alarm**")

    lines.append("")
    lines.append(f"===================")


    # ----- NetEco Status -----

    if neteco_found and neteco_match is not None:

        alarm_name = clean_value(neteco_match.get('Name'))
        lines.append("📌 **NetEco Status (Power Alarms):**")
        lines.append(f"  • Alarm: {alarm_name}")

        lines.append(f"  • Last Occurred: {clean_value(neteco_match.get('Last Occurred'))}")

        if "Mains Failure" in alarm_name:
            lines.append("  • Status: ⚡ **Mains Failure Detected**")
        elif any(power_alarm in alarm_name for power_alarm in POWER_ALARMS):
            lines.append("  • Status: ⚡ **Power Issue Detected**")
        else:
            lines.append("  • Status: ℹ️ Other Alarm")
    else:
        lines.append("📌 **NetEco Status:**")
        lines.append("  • Status: 🟢 **No Power Alarms**")

    lines.append("")

    # ----- Summary Status -----
    if summary_match is not None:
        power_reason = clean_value(summary_match.get('Power Reason (NOC)'))
        lines.append("📌 **Combined Status:**")
        lines.append(f"  • Power Reason: {power_reason}")
        lines.append(f"  • Mains Failure Time: {clean_value(summary_match.get('Mains Failure Time'))}")

        if "Mains Failure" in power_reason:
            lines.append("  • Overall: ⚡ **Mains Failure**")
        elif NO_POWER_TEXT in power_reason or "Check TX" in power_reason:
            lines.append("  • Overall: 📡 **Check TX/Link**")
        elif mae_found:
            lines.append("  • Overall: 🔴 **Disconnected**")
        else:
            lines.append("  • Overall: 🟢 **Normal**")
    else:
        if neteco_found and "Mains Failure" in clean_value(neteco_match.get('Name')):
            lines.append("📌 **Summary Status:**")
            lines.append("  • Status: ⚡ **Mains Failure Only (Not in MAE)**")
        elif neteco_found:
            lines.append("📌 **Summary Status:**")
            lines.append("  • Status: ℹ️ **In NetEco Only (Not in MAE)**")

    return "\n".join(lines)


# =========================================================
# TELEGRAM HANDLERS
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📡 **NOC Report Bot**\n\n"
        "I monitor network alarms and provide concise summaries.\n\n"
        "Use the buttons below or type a site name to search.",
        reply_markup=MENU_KEYBOARD,
        parse_mode="Markdown"
    )


async def summary_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    path, stats = get_summary_stats()
    if isinstance(stats, str):
        await query.message.reply_text(stats, reply_markup=MENU_KEYBOARD)
        return

    await query.message.reply_text(
        format_summary_message(stats),
        reply_markup=MENU_KEYBOARD,
        parse_mode="Markdown"
    )


async def search_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting_site"] = True
    await query.message.reply_text(
        "🔍 **Search Site**\n\nSend me the exact site name (e.g., `AGFT001`, `ABZD001`, or `COAST073`).\n\n"
        "📋 **The search is case-insensitive but must be an exact match.**",
        reply_markup=MENU_KEYBOARD,
        parse_mode="Markdown"
    )


async def send_report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    report_path = latest_report_path()
    if not report_path:
        await query.message.reply_text("❌ No report file found.", reply_markup=MENU_KEYBOARD)
        return

    with open(report_path, "rb") as f:
        await query.message.reply_document(
            document=f,
            filename=report_path.name,
            reply_markup=MENU_KEYBOARD,
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if context.user_data.pop("awaiting_site", False):
        result = search_site_simple(text)
        await update.message.reply_text(result, reply_markup=MENU_KEYBOARD, parse_mode="Markdown")
        return

    path, stats = get_summary_stats()
    if isinstance(stats, str):
        await update.message.reply_text(stats, reply_markup=MENU_KEYBOARD)
        return

    await update.message.reply_text(
        format_summary_message(stats),
        reply_markup=MENU_KEYBOARD,
        parse_mode="Markdown"
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ An error occurred. Please try again.",
            reply_markup=MENU_KEYBOARD
        )


# =========================================================
# MAIN
# =========================================================

def main():
    if not TOKEN:
        raise RuntimeError(
            "Telegram token is missing. Set TELEGRAM_BOT_TOKEN or keep TelegramBot_info.txt next to this script."
        )

    lock_file = acquire_single_instance_lock()
    if lock_file is None:
        print("NOC Bot is already running.", flush=True)
        return

    try:
        app = Application.builder().token(TOKEN).build()

        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("help", start))

        app.add_handler(CallbackQueryHandler(summary_callback, pattern="^summary$"))
        app.add_handler(CallbackQueryHandler(search_callback, pattern="^search_site$"))
        app.add_handler(CallbackQueryHandler(send_report_callback, pattern="^report$"))

        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        app.add_error_handler(error_handler)

        logger.info("NOC Bot is running with report base: %s", BASE_DIR)
        print("NOC Bot is running...", flush=True)
        app.run_polling()

    except Conflict as exc:
        print("Telegram polling conflict: another process is already using this bot token.", flush=True)
        raise SystemExit(1) from exc
    finally:
        lock_file.close()


if __name__ == "__main__":
    main()
