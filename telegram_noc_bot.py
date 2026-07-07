import os
import json
import re
import tempfile
import logging
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd
from openpyxl import Workbook, load_workbook
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
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
INTERACTION_LOG_PATH = LOG_DIR / "telegram_noc_bot_interactions.log"
INTERACTION_EXCEL_PATH = LOG_DIR / "telegram_noc_bot_interactions.xlsx"
PHONE_BOOK_PATH = LOG_DIR / "telegram_noc_bot_contacts.json"
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)
interaction_logger = logging.getLogger("telegram_interactions")
interaction_logger.setLevel(logging.INFO)
interaction_logger.propagate = False
if not interaction_logger.handlers:
    interaction_handler = logging.FileHandler(INTERACTION_LOG_PATH, encoding="utf-8")
    interaction_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    interaction_logger.addHandler(interaction_handler)
_REPORT_CACHE = {}
INTERACTION_EXCEL_HEADERS = (
    "Timestamp",
    "Event",
    "User ID",
    "Username",
    "Full Name",
    "Mobile Number",
    "Chat ID",
    "Chat Type",
    "Detail",
)


def read_bot_token():
    env_token = env_str("TELEGRAM_BOT_TOKEN").strip()
    if env_token:
        return env_token

    if not TOKEN_FILE.exists():
        return ""

    match = TOKEN_RE.search(TOKEN_FILE.read_text(encoding="utf-8", errors="ignore"))
    return match.group(0) if match else ""


TOKEN = read_bot_token()

MENU_KEYBOARD = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("Summary", callback_data="summary"),
            InlineKeyboardButton("Search Site", callback_data="search_site"),
        ],
        [
            InlineKeyboardButton("Disconnected Sites", callback_data="disconnected"),
            InlineKeyboardButton("Power Alarms", callback_data="power"),
        ],
        [
            InlineKeyboardButton("No Power Alarm", callback_data="nopower"),
            InlineKeyboardButton("NetEco Alarms", callback_data="neteco"),
        ],
        [
            InlineKeyboardButton("MAE Alarms", callback_data="mae"),
            InlineKeyboardButton("Send Report", callback_data="report"),
        ],
    ]
)

CONTACT_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("Share mobile number", request_contact=True)]],
    resize_keyboard=True,
    one_time_keyboard=True,
)


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


def safe_log_text(value, max_chars=600):
    text = clean_value(value, default="")
    text = TOKEN_RE.sub("[REDACTED_TOKEN]", text)
    text = " ".join(text.split())
    if len(text) > max_chars:
        return text[: max_chars - 3] + "..."
    return text


def load_phone_book():
    if not PHONE_BOOK_PATH.exists():
        return {}
    try:
        return json.loads(PHONE_BOOK_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not read phone book: %s", PHONE_BOOK_PATH)
        return {}


def save_phone_book(phone_book):
    PHONE_BOOK_PATH.write_text(json.dumps(phone_book, ensure_ascii=False, indent=2), encoding="utf-8")


def remember_phone_number(user_id, phone_number):
    if not user_id or not phone_number:
        return
    phone_book = load_phone_book()
    phone_book[str(user_id)] = safe_log_text(phone_number, 80)
    save_phone_book(phone_book)


def phone_for_user(user_id):
    if not user_id:
        return ""
    return load_phone_book().get(str(user_id), "")


def update_actor_fields(update):
    user = update.effective_user if isinstance(update, Update) else None
    chat = update.effective_chat if isinstance(update, Update) else None

    fields = {
        "user_id": "-",
        "username": "",
        "full_name": "",
        "phone_number": "",
        "chat_id": "-",
        "chat_type": "",
    }

    if user:
        fields["user_id"] = str(user.id)
        if user.username:
            fields["username"] = f"@{safe_log_text(user.username, 80)}"
        fields["full_name"] = safe_log_text(user.full_name, 120)
        fields["phone_number"] = phone_for_user(user.id)

    if chat:
        fields["chat_id"] = str(chat.id)
        fields["chat_type"] = str(chat.type)

    return fields


def update_actor_text(update):
    fields = update_actor_fields(update)
    return (
        f"user_id={fields['user_id']} "
        f"username={fields['username'] or '-'} "
        f"name={fields['full_name'] or '-'} "
        f"phone={fields['phone_number'] or '-'} "
        f"chat_id={fields['chat_id']} "
        f"chat_type={fields['chat_type'] or '-'}"
    )


def excel_safe_value(value):
    text = safe_log_text(value, 1000)
    if text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def ensure_interaction_excel_headers(worksheet):
    if worksheet.max_row < 1:
        worksheet.append(INTERACTION_EXCEL_HEADERS)
        return

    current_headers = [cell.value for cell in worksheet[1]]
    if not any(current_headers):
        worksheet.append(INTERACTION_EXCEL_HEADERS)
        return

    if "Mobile Number" not in current_headers:
        worksheet.insert_cols(6)
        worksheet.cell(row=1, column=6, value="Mobile Number")


def append_interaction_excel(timestamp, event, actor, detail):
    if INTERACTION_EXCEL_PATH.exists():
        workbook = load_workbook(INTERACTION_EXCEL_PATH)
        worksheet = workbook.active
        ensure_interaction_excel_headers(worksheet)
    else:
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "Interactions"
        worksheet.append(INTERACTION_EXCEL_HEADERS)

    worksheet.append(
        [
            timestamp,
            event,
            actor["user_id"],
            actor["username"],
            actor["full_name"],
            actor["phone_number"],
            actor["chat_id"],
            actor["chat_type"],
            excel_safe_value(detail),
        ]
    )
    workbook.save(INTERACTION_EXCEL_PATH)


def log_interaction(update, event, detail=""):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    actor = update_actor_fields(update)
    safe_detail = safe_log_text(detail)
    interaction_logger.info(
        "event=%s %s detail=%s",
        event,
        update_actor_text(update),
        safe_detail,
    )
    try:
        append_interaction_excel(timestamp, event, actor, safe_detail)
    except PermissionError:
        logger.warning("Could not write interaction Excel log because it is open: %s", INTERACTION_EXCEL_PATH)
    except Exception as exc:
        logger.warning("Could not write interaction Excel log %s: %s", INTERACTION_EXCEL_PATH, exc)


def log_message_request(update, event):
    message = update.effective_message
    text = message.text if message else ""
    log_interaction(update, event, text)


def log_response(update, event, detail):
    log_interaction(update, event, detail)


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


def report_time_text(path):
    timestamp = report_timestamp(path)
    if not timestamp:
        return "-"
    return timestamp.strftime("%Y-%m-%d %H:%M")


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
        logger.info("Loaded report %s with sheets %s", path.name, list(sheets.keys()))
        return path, sheets, None
    except Exception as exc:
        logger.exception("Could not read Excel report: %s", path)
        return path, {}, f"Could not read Excel report: {exc}"


def normalize_site_name(value):
    return clean_value(value).replace("(FN)", "").strip()


def clean_summary_df(df):
    df = df.copy()
    if df.empty:
        for col in ["Site Name", "MO Name", "Alarm Name", "MAE Disconnect Time", "Power Reason (NOC)", "Mains Failure Time"]:
            if col not in df.columns:
                df[col] = "-"
        return df

    unnamed_cols = [c for c in df.columns if str(c).startswith("Unnamed:")]
    df.drop(columns=unnamed_cols, inplace=True, errors="ignore")
    df.dropna(how="all", inplace=True)

    if "Cleared Name" in df.columns and "MAE Disconnect Time" not in df.columns:
        df.rename(columns={"Cleared Name": "MAE Disconnect Time"}, inplace=True)
    if "Last Occurred" in df.columns and "MAE Disconnect Time" not in df.columns:
        df.rename(columns={"Last Occurred": "MAE Disconnect Time"}, inplace=True)

    for col in ["Site Name", "MO Name", "Alarm Name", "MAE Disconnect Time", "Power Reason (NOC)", "Mains Failure Time"]:
        if col not in df.columns:
            df[col] = "-"

    df = df[df["Site Name"].notna()].copy()
    df["Site Name"] = df["Site Name"].map(normalize_site_name)
    df["MO Name"] = df["MO Name"].map(clean_value)
    return df


def report_data():
    path, sheets, error = load_report()
    if error:
        return path, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), error

    summary = clean_summary_df(sheets.get("Current Alarms Summary", pd.DataFrame()))
    neteco = sheets.get("NetEco Current Alarms", pd.DataFrame()).copy()
    mae = sheets.get("MAE Current Alarms", pd.DataFrame()).copy()

    for df in [neteco, mae]:
        if not df.empty and "Site Name" in df.columns:
            df["Site Name"] = df["Site Name"].map(normalize_site_name)

    return path, summary, neteco, mae, None

def metrics_from_summary(summary):
    metrics = {}
    if "Metric Description" not in summary.columns or "Value" not in summary.columns:
        return metrics
    for _, row in summary[["Metric Description", "Value"]].dropna(how="all").iterrows():
        description = clean_value(row.get("Metric Description"), "")
        value = row.get("Value")
        if description:
            metrics[description] = clean_value(value)
    return metrics

def shorten_lines(lines, max_chars=MAX_MESSAGE_CHARS):
    text = "\n".join(lines)
    if len(text) <= max_chars:
        return text

    kept = []
    total = 0
    for line in lines:
        if total + len(line) + 1 > max_chars - 90:
            break
        kept.append(line)
        total += len(line) + 1
    kept.append("")
    kept.append("Result is long. Use Send Report for the full Excel file.")
    return "\n".join(kept)

def site_matches(df, query):
    if df.empty or "Site Name" not in df.columns:
        return df.iloc[0:0] if not df.empty else df
    query = normalize_site_name(query).lower()
    sites = df["Site Name"].astype(str).str.lower()
    exact = df[sites == query]
    if not exact.empty:
        return exact
    contains = df[sites.str.contains(query, na=False, regex=False)]
    if not contains.empty:
        return contains
    if "MO Name" in df.columns:
        mo_names = df["MO Name"].astype(str).str.lower()
        exact_mo = df[mo_names == query]
        if not exact_mo.empty:
            return exact_mo
        mo_contains = df[mo_names.str.contains(query, na=False, regex=False)]
        if not mo_contains.empty:
            return mo_contains
    return contains

def summary_text():
    path, summary, neteco, mae, error = report_data()
    if error:
        return error
    if summary.empty:
        return f"Report found, but summary sheet is empty: {path.name}"

    metrics = metrics_from_summary(summary)
    power_pattern = "|".join(re.escape(alarm) for alarm in POWER_ALARMS)
    power_mask = summary["Power Reason (NOC)"].astype(str).str.contains(power_pattern, na=False, regex=True)
    no_power_mask = summary["Power Reason (NOC)"].fillna("").eq(NO_POWER_TEXT)

    lines = [
        f"NOC report: {path.name}",
        f"Report snapshot: {report_time_text(path)}",
        f"Report updated: {file_time(path)}",
        "",
        f"Disconnected sites: {summary['Site Name'].nunique()}",
        f"With power alarm: {summary.loc[power_mask, 'Site Name'].nunique()}",
        f"No power alarm / check TX: {summary.loc[no_power_mask, 'Site Name'].nunique()}",
        f"NetEco alarm rows: {len(neteco)}",
        f"MAE alarm rows: {len(mae)}",
    ]

    if metrics:
        lines.append("")
        lines.append("Metrics from Excel:")
        for description, value in metrics.items():
            lines.append(f"- {description}: {value}")

    return "\n".join(lines)

def site_status_text(site_name):
    path, summary, neteco, mae, error = report_data()
    if error:
        return error

    rows = site_matches(summary, site_name)
    neteco_rows = site_matches(neteco, site_name)
    mae_rows = site_matches(mae, site_name)

    if rows.empty and neteco_rows.empty and mae_rows.empty:
        return f"Site '{site_name}' was not found in the latest report."

    if rows["Site Name"].nunique() > 1:
        lines = [f"Matched {rows['Site Name'].nunique()} disconnected sites:"]
        for site in rows["Site Name"].drop_duplicates().head(40):
            lines.append(f"- {site}")
        return shorten_lines(lines)

    lines = [f"Report: {path.name}"]

    if not rows.empty:
        row = rows.iloc[0]
        power_reason = clean_value(row.get("Power Reason (NOC)"))
        mains_time = clean_value(row.get("Mains Failure Time"))
        lines.extend(
            [
                f"Site: {clean_value(row.get('Site Name'))}",
                f"MO Name: {clean_value(row.get('MO Name'))}",
                f"Alarm name: {clean_value(row.get('Alarm Name'))}",
                f"MAE disconnect time: {clean_value(row.get('MAE Disconnect Time'))}",
                f"Power reason: {power_reason}",
                f"Mains failure time: {mains_time if mains_time != '-' else 'Not recorded'}",
            ]
        )
    else:
        lines.append(f"Site: {normalize_site_name(site_name)}")
        lines.append("Status: not listed in Current Alarms Summary.")

    if not neteco_rows.empty:
        lines.append("")
        lines.append("NetEco Current Alarms:")
        for _, alarm in neteco_rows.head(10).iterrows():
            lines.append(
                f"- {clean_value(alarm.get('Severity'))} | "
                f"{clean_value(alarm.get('Name'))} | "
                f"{clean_value(alarm.get('Last Occurred'))}"
            )

    if not mae_rows.empty:
        lines.append("")
        lines.append("MAE Current Alarms:")
        for _, alarm in mae_rows.head(10).iterrows():
            lines.append(
                f"- {clean_value(alarm.get('Severity'))} | "
                f"{clean_value(alarm.get('Name'))} | "
                f"{clean_value(alarm.get('Last Occurred'))}"
            )

    return shorten_lines(lines)


def list_summary_sites(kind, limit=45):
    _, summary, _, _, error = report_data()
    if error:
        return error
    if summary.empty:
        return "Current Alarms Summary is empty."

    if kind == "power":
        power_pattern = "|".join(re.escape(alarm) for alarm in POWER_ALARMS)
        mask = summary["Power Reason (NOC)"].astype(str).str.contains(power_pattern, na=False, regex=True)
        title = "Disconnected sites with power alarms"
    elif kind == "nopower":
        mask = summary["Power Reason (NOC)"].fillna("").eq(NO_POWER_TEXT)
        title = "Disconnected sites with no power alarm"
    else:
        mask = pd.Series([True] * len(summary), index=summary.index)
        title = "All disconnected sites"

    rows = summary[mask].copy()
    if rows.empty:
        return f"{title}: none"

    lines = [f"{title}: {rows['Site Name'].nunique()}"]
    for _, row in rows.head(limit).iterrows():
        lines.append(
            f"- {clean_value(row.get('Site Name'))} | "
            f"{clean_value(row.get('Power Reason (NOC)'))} | "
            f"{clean_value(row.get('MAE Disconnect Time'))}"
        )
    if len(rows) > limit:
        lines.append(f"...and {len(rows) - limit} more.")
    return shorten_lines(lines)

def sheet_alarm_text(sheet_name, limit=45):
    _, _, neteco, mae, error = report_data()
    if error:
        return error

    df = neteco if sheet_name == "neteco" else mae
    title = "NetEco Current Alarms" if sheet_name == "neteco" else "MAE Current Alarms"
    if df.empty:
        return f"{title} sheet is empty."

    lines = [f"{title}: {len(df)} rows"]
    for _, row in df.head(limit).iterrows():
        lines.append(
            f"- {clean_value(row.get('Site Name'))} | "
            f"{clean_value(row.get('Severity'))} | "
            f"{clean_value(row.get('Name'))} | "
            f"{clean_value(row.get('Last Occurred'))}"
        )
    if len(df) > limit:
        lines.append(f"...and {len(df) - limit} more.")
    return shorten_lines(lines)

def alarm_search_text(query, limit=45):
    _, _, neteco, mae, error = report_data()
    if error:
        return error

    query_lower = query.lower().strip()
    if not query_lower:
        return "Usage: /alarm <alarm name>, for example /alarm Mains Failure"

    lines = []
    total_matches = 0
    for title, df in [("NetEco", neteco), ("MAE", mae)]:
        if df.empty or "Name" not in df.columns:
            continue
        rows = df[df["Name"].astype(str).str.lower().str.contains(query_lower, na=False, regex=False)]
        total_matches += len(rows)
        lines.append(f"{title} alarm matches: {len(rows)}")
        for _, row in rows.head(limit).iterrows():
            lines.append(
                f"- {clean_value(row.get('Site Name'))} | "
                f"{clean_value(row.get('Severity'))} | "
                f"{clean_value(row.get('Name'))} | "
                f"{clean_value(row.get('Last Occurred'))}"
            )
    if total_matches == 0:
        return f"No alarm found for '{query}'."
    return shorten_lines(lines)

def top_alarm_text(sheet_name, limit=15):
    _, _, neteco, mae, error = report_data()
    if error:
        return error
    df = neteco if sheet_name == "neteco" else mae
    title = "NetEco" if sheet_name == "neteco" else "MAE"
    if df.empty or "Name" not in df.columns:
        return f"No {title} alarms found."
    counts = Counter(df["Name"].dropna().astype(str))
    lines = [f"Top {title} alarms:"]
    for name, count in counts.most_common(limit):
        lines.append(f"- {name}: {count}")
    return "\n".join(lines)

def menu_text():
    return (
        "Choose an option from the list, or type a site name directly.\n\n"
        "Examples:\n"
        "- ABZD001\n"
        "- COAST073\n"
        "- /alarm Mains Failure\n"
        "- /site BGZ162\n"
        "- /phone"
    )

def configure_logging():
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

async def reply(update: Update, text: str):
    message = update.effective_message
    if not message:
        logger.warning("Cannot reply because update has no effective message: %s", update)
        return
    log_response(update, "bot_reply", text)
    await message.reply_text(text, reply_markup=MENU_KEYBOARD)

async def callback_reply(update: Update, text: str):
    query = update.callback_query
    await query.answer()
    if not query.message:
        logger.warning("Cannot reply because callback query has no message: %s", query)
        return
    log_response(update, "bot_callback_reply", text)
    await query.message.reply_text(text, reply_markup=MENU_KEYBOARD)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_message_request(update, "command_start")
    await reply(update, menu_text())

async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_message_request(update, "command_ping")
    await reply(update, "Bot is running.")

async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_message_request(update, "command_summary")
    await reply(update, summary_text())

async def site_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_message_request(update, "command_site")
    if not context.args:
        context.user_data["awaiting_site"] = True
        await reply(update, "Send the site name, for example ABZD001.")
        return
    await reply(update, site_status_text(" ".join(context.args)))

async def alarm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_message_request(update, "command_alarm")
    if not context.args:
        await reply(update, "Usage: /alarm <alarm name>, for example /alarm Mains Failure")
        return
    await reply(update, alarm_search_text(" ".join(context.args)))

async def topmae_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_message_request(update, "command_topmae")
    await reply(update, top_alarm_text("mae"))

async def topneteco_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_message_request(update, "command_topneteco")
    await reply(update, top_alarm_text("neteco"))

async def phone_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_message_request(update, "command_phone")
    message = update.effective_message
    if not message:
        logger.warning("Cannot request phone because update has no effective message: %s", update)
        return
    log_response(update, "bot_phone_request", "Requested user contact share.")
    await message.reply_text(
        "Tap the button below to share your mobile number with this bot.",
        reply_markup=CONTACT_KEYBOARD,
    )

async def contact_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user
    contact = message.contact if message else None

    if not contact or not user:
        log_interaction(update, "contact_shared_invalid", "Missing contact or user data.")
        await reply(update, "Could not read the shared contact.")
        return

    if contact.user_id and contact.user_id != user.id:
        log_interaction(update, "contact_shared_rejected", contact.phone_number)
        await message.reply_text(
            "Please share your own mobile number using the button.",
            reply_markup=CONTACT_KEYBOARD,
        )
        return

    remember_phone_number(user.id, contact.phone_number)
    log_interaction(update, "contact_shared", contact.phone_number)
    await message.reply_text(
        "Mobile number saved for future interaction logs.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await reply(update, menu_text())

async def send_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_message_request(update, "command_report")
    report_path = latest_report_path()
    if not report_path:
        await reply(update, "No Excel report file found.")
        return
    message = update.effective_message
    if not message:
        logger.warning("Cannot send report because update has no effective message: %s", update)
        return
    with open(report_path, "rb") as report_file:
        await message.reply_document(
            document=report_file,
            filename=report_path.name,
            reply_markup=MENU_KEYBOARD,
        )
    log_response(update, "bot_sent_report", report_path.name)

async def send_report_from_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    report_path = latest_report_path()
    if not report_path:
        await query.message.reply_text("No Excel report file found.", reply_markup=MENU_KEYBOARD)
        return
    with open(report_path, "rb") as report_file:
        await query.message.reply_document(
            document=report_file,
            filename=report_path.name,
            reply_markup=MENU_KEYBOARD,
        )
    log_response(update, "bot_sent_report", report_path.name)

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action = query.data
    log_interaction(update, "callback", action)

    if action == "search_site":
        context.user_data["awaiting_site"] = True
        await callback_reply(update, "Send the site name, for example ABZD001.")
        return

    if action == "report":
        await send_report_from_callback(update, context)
        return

    actions = {
        "summary": summary_text,
        "disconnected": lambda: list_summary_sites("all"),
        "power": lambda: list_summary_sites("power"),
        "nopower": lambda: list_summary_sites("nopower"),
        "neteco": lambda: sheet_alarm_text("neteco"),
        "mae": lambda: sheet_alarm_text("mae"),
    }

    if action in actions:
        await callback_reply(update, actions[action]())
        return

    await query.answer("Unknown option")

async def menu_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log_message_request(update, "message_text")
    text = update.message.text.strip()
    normalized = text.lower()

    if context.user_data.pop("awaiting_site", False):
        await reply(update, site_status_text(text))
        return

    if normalized.startswith("site "):
        await reply(update, site_status_text(text[5:].strip()))
        return

    if normalized.startswith("alarm "):
        await reply(update, alarm_search_text(text[6:].strip()))
        return

    actions = {
        "summary": summary_text,
        "disconnected sites": lambda: list_summary_sites("all"),
        "power alarm": lambda: list_summary_sites("power"),
        "power alarms": lambda: list_summary_sites("power"),
        "no power alarm": lambda: list_summary_sites("nopower"),
        "neteco alarm": lambda: sheet_alarm_text("neteco"),
        "neteco alarms": lambda: sheet_alarm_text("neteco"),
        "mae alarm": lambda: sheet_alarm_text("mae"),
        "mae alarms": lambda: sheet_alarm_text("mae"),
        "menu": menu_text,
        "help": menu_text,
    }

    if normalized == "search site":
        context.user_data["awaiting_site"] = True
        await reply(update, "Send the site name, for example ABZD001.")
        return

    if normalized in {"phone", "mobile", "mobile number"}:
        await phone_command(update, context)
        return

    if normalized == "send report":
        await send_report(update, context)
        return

    if normalized in actions:
        await reply(update, actions[normalized]())
        return

    await reply(update, site_status_text(text))

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    error = context.error
    exc_info = (type(error), error, error.__traceback__) if error else None
    logger.error("Unhandled Telegram handler error. update=%s", update, exc_info=exc_info)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "An internal bot error occurred. Check logs/telegram_noc_bot_runtime.log.",
            reply_markup=MENU_KEYBOARD,
        )

def main():
    configure_logging()

    if not TOKEN:
        raise RuntimeError(
            "Telegram token is missing. Set TELEGRAM_BOT_TOKEN or keep TelegramBot_info.txt next to this script."
        )

    lock_file = acquire_single_instance_lock()
    if lock_file is None:
        print(
            "NOC Bot is already running on this computer. "
            "Stop the existing telegram_noc_bot.py process before starting another copy.",
            flush=True,
        )
        return

    try:
        app = Application.builder().token(TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("help", start))
        app.add_handler(CommandHandler("menu", start))
        app.add_handler(CommandHandler("ping", ping_command))
        app.add_handler(CommandHandler("summary", summary_command))
        app.add_handler(CommandHandler("stats", summary_command))
        app.add_handler(CommandHandler("site", site_command))
        app.add_handler(CommandHandler("alarm", alarm_command))
        app.add_handler(CommandHandler("report", send_report))
        app.add_handler(CommandHandler("topmae", topmae_command))
        app.add_handler(CommandHandler("topneteco", topneteco_command))
        app.add_handler(CommandHandler("phone", phone_command))
        app.add_handler(CallbackQueryHandler(menu_callback))
        app.add_handler(MessageHandler(filters.CONTACT, contact_message))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_message))
        app.add_error_handler(error_handler)

        logger.info("NOC Bot is running with report base: %s", BASE_DIR)
        print("NOC Bot is running...", flush=True)
        app.run_polling()
    except Conflict as exc:
        print(
            "Telegram polling conflict: another process or server is already using this bot token. "
            "Only one polling bot can run at a time.",
            flush=True,
        )
        raise SystemExit(1) from exc
    finally:
        lock_file.close()


if __name__ == "__main__":
    main()
