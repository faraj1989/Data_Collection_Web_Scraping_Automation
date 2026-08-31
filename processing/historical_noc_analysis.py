"""Build chronic-offender / trend insights from MAE + NetEco Historical Alarms
exports (scrapers/mae_historical_alarms_scraper.py and
scrapers/neteco_historical_alarms_scraper.py).

Unlike enhanced_noc_analysis.py (which triages the current live snapshot),
each historical export re-exports the *entire* rolling 7-10 day window every
cycle. Every cycle this script looks at every export sitting in the MAE/NetEco
export folders and processes whichever ones it hasn't folded in yet (tracked
by content hash in a small processed-exports ledger next to the alarm
ledger) - in steady state that's just the one new file each scraper produced
since last cycle, but it also means an old export that got stranded and
recovered late (see recover_stray_historical_downloads) still gets folded in
exactly once, never double-counted. The alarm ledger itself
(HISTORICAL_LEDGER_PATH) accumulates across cycles, keyed on (Source, Site,
Name, Occurred On): new alarms are appended, previously-seen alarms get their
Cleared On/Duration updated once they clear. Chronic-offender and trend
analysis reads from this ledger, not from any single cycle's export.
"""
import argparse
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from project_config import env_int, env_path, load_env_file
from alarm_taxonomy import classify_mae_alarm, severity_max
from historical_alarm_parser import detect_source, file_fingerprint, load_historical_export
from report_formatting import format_workbook

load_env_file()
MAE_EXPORT_DIR = env_path("MAE_HISTORICAL_EXPORT_BASE_DIR", r"C:\Historical_Alarms")
NETECO_EXPORT_DIR = env_path("NETECO_HISTORICAL_EXPORT_BASE_DIR", r"C:\Historical_Alarms")
MAE_DOWNLOAD_DIR = env_path("MAE_HISTORICAL_DOWNLOAD_DIR", r"C:\Historical_Alarms\Downloads")
NETECO_DOWNLOAD_DIR = env_path("NETECO_HISTORICAL_DOWNLOAD_DIR", r"C:\Historical_Alarms\Downloads")
OUTPUT_DIR = env_path("HISTORICAL_ANALYSIS_OUTPUT_DIR", r"C:\Historical_Alarms_Analysis")
SHARED_FOLDER = env_path("HISTORICAL_SHARED_FOLDER", OUTPUT_DIR / "Shared")
LEDGER_PATH = env_path("HISTORICAL_LEDGER_PATH", OUTPUT_DIR / "alarm_ledger.csv")
CHRONIC_THRESHOLD = env_int("HISTORICAL_CHRONIC_THRESHOLD", 5)
INTERVAL_SECONDS = env_int("HISTORICAL_ANALYSIS_INTERVAL_SECONDS", 600)
PROCESSED_EXPORTS_LEDGER_FILENAME = "historical_processed_exports_ledger.json"
RECOVERABLE_EXTENSIONS = {".csv", ".zip", ".xlsx", ".xlsm"}
# The ledger accumulates forever (that's the point - chronic-offender tracking
# needs history beyond any single export's rolling window), but dumping every
# raw row into Excel every cycle would get slower and larger indefinitely.
# The aggregate sheets always read the FULL ledger; only these two raw sheets
# are capped to a recent window for performance.
RAW_SHEET_LOOKBACK_DAYS = env_int("HISTORICAL_RAW_SHEET_LOOKBACK_DAYS", 30)

LEDGER_COLUMNS = [
    "Source", "Site", "Name", "NE Type", "Category", "Priority", "Severity",
    "Alarm ID", "Correlation Flag", "Occurred On", "Cleared On",
    "Alarm Duration Seconds", "Device", "Manage Domain", "Location Info",
    "First Seen", "Last Seen",
]


def parse_args():
    parser = argparse.ArgumentParser(description="Build historical alarm insights from MAE + NetEco exports")
    parser.add_argument("--once", action="store_true",
                         help="Build a single report and exit instead of looping continuously")
    parser.add_argument("--output", default="", help="Optional full path of the workbook to create")
    return parser.parse_args()


def log(message):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def ensure_dir(path):
    Path(path).mkdir(parents=True, exist_ok=True)
    return Path(path)


def find_all_exports(base_dir: Path, filename_glob: str):
    """Historical scrapers write into <base_dir>/<YYYY-MM-DD>/<file>, but
    tolerate a flat layout too. Returns every match (oldest first) - which
    ones are actually new is decided later by the processed-exports ledger,
    not by file discovery."""
    if not base_dir.exists():
        return []
    candidates = list(base_dir.glob(f"*/{filename_glob}")) + list(base_dir.glob(filename_glob))
    seen = set()
    unique = []
    for path in candidates:
        key = path.resolve()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return sorted(unique, key=lambda p: p.stat().st_mtime)


def load_processed_exports_ledger(ledger_path: Path) -> dict:
    tracker_path = ledger_path.parent / PROCESSED_EXPORTS_LEDGER_FILENAME
    if not tracker_path.exists():
        return {}
    try:
        return json.loads(tracker_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_processed_exports_ledger(ledger_path: Path, tracker: dict) -> None:
    tracker_path = ledger_path.parent / PROCESSED_EXPORTS_LEDGER_FILENAME
    tracker_path.parent.mkdir(parents=True, exist_ok=True)
    tracker_path.write_text(json.dumps(tracker, indent=2), encoding="utf-8")


def recover_stray_historical_downloads(search_dirs, mae_target_dir: Path, neteco_target_dir: Path, log) -> list:
    """Sweep raw download folder(s) for MAE/NetEco historical exports that
    never reached their export folder - most often because the current/
    historical download folders briefly collided (see .env.example), leaving
    a stray file whose generic browser-download name doesn't say which
    scraper produced it. Identifies MAE vs NetEco by header shape (see
    historical_alarm_parser.detect_source) and files each into today's dated
    subfolder of the right export base dir, so the normal discovery/ledger
    flow below picks it up like any other export."""
    recovered = []
    today_name = datetime.now().strftime("%Y-%m-%d")
    seen_dirs = set()

    for search_dir in search_dirs:
        search_dir = Path(search_dir)
        if not search_dir.exists():
            continue
        resolved = search_dir.resolve()
        if resolved in seen_dirs:
            continue
        seen_dirs.add(resolved)

        for candidate in list(search_dir.iterdir()):
            if not candidate.is_file() or candidate.suffix.lower() not in RECOVERABLE_EXTENSIONS:
                continue
            name_lower = candidate.name.lower()
            if "historicalalarms" not in name_lower and "neteco_historical_alarm" not in name_lower:
                continue

            source = detect_source(candidate)
            if source == "MAE":
                target_dir = mae_target_dir / today_name
                new_name = f"HistoricalAlarms_MAE_recovered_{candidate.stem}{candidate.suffix}"
            elif source == "NetEco":
                target_dir = neteco_target_dir / today_name
                new_name = f"NetEco_Historical_Alarm_recovered_{candidate.stem}{candidate.suffix}"
            else:
                log(f"WARNING: could not tell if this is a MAE or NetEco export, leaving in place: {candidate}")
                continue

            target_dir.mkdir(parents=True, exist_ok=True)
            destination = target_dir / new_name
            if destination.exists():
                destination = destination.with_name(
                    f"{destination.stem}_{datetime.now():%H%M%S}{destination.suffix}"
                )

            log(f"Recovering stray {source} historical export: {candidate} -> {destination}")
            shutil.move(str(candidate), str(destination))
            recovered.append(destination)

    return recovered


STRING_LEDGER_COLUMNS = ["Source", "Site", "Name", "NE Type", "Category", "Priority", "Severity",
                         "Alarm ID", "Correlation Flag", "Device", "Manage Domain", "Location Info"]


def load_ledger(path: Path) -> pd.DataFrame:
    if path.exists():
        try:
            return pd.read_csv(
                path,
                parse_dates=["Occurred On", "Cleared On", "First Seen", "Last Seen"],
                dtype={col: "string" for col in STRING_LEDGER_COLUMNS},
            )
        except (pd.errors.EmptyDataError, ValueError):
            pass
    return pd.DataFrame(columns=LEDGER_COLUMNS)


def save_ledger(ledger: pd.DataFrame, path: Path):
    ensure_dir(path.parent)
    ledger.to_csv(path, index=False)


def upsert_ledger(ledger: pd.DataFrame, new_rows: pd.DataFrame) -> pd.DataFrame:
    if new_rows.empty:
        return ledger

    now = pd.Timestamp.now()
    existing_index = {
        (row.Source, row.Site, row.Name, row["Occurred On"]): idx
        for idx, row in ledger.iterrows()
    }

    ledger = ledger.copy()
    new_records = []
    for _, row in new_rows.iterrows():
        key = (row["Source"], row["Site"], row["Name"], row["Occurred On"])
        idx = existing_index.get(key)
        if idx is not None:
            ledger.at[idx, "Cleared On"] = row["Cleared On"]
            ledger.at[idx, "Alarm Duration Seconds"] = row["Alarm Duration Seconds"]
            ledger.at[idx, "Severity"] = row["Severity"]
            ledger.at[idx, "Correlation Flag"] = row["Correlation Flag"]
            ledger.at[idx, "Last Seen"] = now
        else:
            record = {col: row.get(col) for col in LEDGER_COLUMNS if col not in ("First Seen", "Last Seen")}
            record["First Seen"] = now
            record["Last Seen"] = now
            new_records.append(record)
            existing_index[key] = None  # dedupe within the same batch

    if new_records:
        ledger = pd.concat([ledger, pd.DataFrame(new_records, columns=LEDGER_COLUMNS)], ignore_index=True)
    return ledger


def reclassify_ledger(ledger: pd.DataFrame):
    """Recompute Category/Priority for every row from the current taxonomy,
    in place. Classification is not baked in permanently at insert time -
    every cycle re-derives it, so a future fix/addition to
    alarm_taxonomy.classify_mae_alarm applies retroactively to alarms already
    in the ledger, not just newly-ingested ones. Classifies each distinct
    alarm Name once (not once per row) since the same handful of names repeat
    across tens of thousands of ledger rows."""
    if ledger.empty:
        return
    unique_names = ledger["Name"].dropna().unique()
    classification = {name: classify_mae_alarm(name) for name in unique_names}
    ledger["Category"] = ledger["Name"].map(lambda n: classification.get(n, ("Other / Review", "P3"))[0])
    ledger["Priority"] = ledger["Name"].map(lambda n: classification.get(n, ("Other / Review", "P3"))[1])


def build_category_rollup(ledger: pd.DataFrame) -> pd.DataFrame:
    columns = ["Category", "Priority", "Alarm Count", "Affected Sites", "Avg Duration (min)", "Max Severity"]
    if ledger.empty:
        return pd.DataFrame(columns=columns)
    grouped = ledger.groupby(["Category", "Priority"], dropna=False)
    out = grouped.agg(**{
        "Alarm Count": ("Name", "size"),
        "Affected Sites": ("Site", "nunique"),
    }).reset_index()
    avg_duration = grouped["Alarm Duration Seconds"].mean() / 60
    out["Avg Duration (min)"] = out.set_index(["Category", "Priority"]).index.map(avg_duration).round(1)
    out["Max Severity"] = [
        severity_max(ledger.loc[(ledger["Category"] == c) & (ledger["Priority"] == p), "Severity"])
        for c, p in zip(out["Category"], out["Priority"])
    ]
    return out.sort_values(["Priority", "Alarm Count"], ascending=[True, False])


def build_top_alarms(ledger: pd.DataFrame, top_n=50) -> pd.DataFrame:
    columns = ["Name", "Category", "Priority", "Max Severity", "Occurrences", "Affected Sites",
               "Avg Duration (min)", "Total Duration (hrs)", "First Occurred", "Last Occurred"]
    if ledger.empty:
        return pd.DataFrame(columns=columns)
    grouped = ledger.groupby("Name")
    out = grouped.agg(
        Category=("Category", "first"), Priority=("Priority", "first"),
        Occurrences=("Name", "size"), **{"Affected Sites": ("Site", "nunique")},
        **{"First Occurred": ("Occurred On", "min"), "Last Occurred": ("Occurred On", "max")},
    ).reset_index()
    out["Avg Duration (min)"] = (grouped["Alarm Duration Seconds"].mean() / 60).round(1).values
    out["Total Duration (hrs)"] = (grouped["Alarm Duration Seconds"].sum() / 3600).round(1).values
    out["Max Severity"] = [severity_max(ledger.loc[ledger["Name"] == n, "Severity"]) for n in out["Name"]]
    return out[columns].sort_values("Occurrences", ascending=False).head(top_n)


def build_chronic_offenders(ledger: pd.DataFrame, threshold: int) -> pd.DataFrame:
    columns = ["Site", "Name", "Category", "Occurrences", "Avg Duration (min)",
               "Total Downtime (hrs)", "First Occurred", "Last Occurred"]
    if ledger.empty:
        return pd.DataFrame(columns=columns)
    grouped = ledger.groupby(["Site", "Name"])
    out = grouped.agg(
        Category=("Category", "first"), Occurrences=("Name", "size"),
        **{"First Occurred": ("Occurred On", "min"), "Last Occurred": ("Occurred On", "max")},
    ).reset_index()
    out["Avg Duration (min)"] = (grouped["Alarm Duration Seconds"].mean() / 60).round(1).values
    out["Total Downtime (hrs)"] = (grouped["Alarm Duration Seconds"].sum() / 3600).round(1).values
    out = out[out["Occurrences"] >= threshold]
    return out[columns].sort_values("Occurrences", ascending=False)


def build_site_downtime(ledger: pd.DataFrame) -> pd.DataFrame:
    columns = ["Site", "Outage Events", "Total Outage Minutes", "Avg Outage Minutes",
               "Longest Outage Minutes", "Last Outage Occurred"]
    outage = ledger[ledger["Category"] == "Service Outage"] if not ledger.empty else ledger
    if outage.empty:
        return pd.DataFrame(columns=columns)
    grouped = outage.groupby("Site")
    out = grouped.agg(
        **{"Outage Events": ("Name", "size"), "Last Outage Occurred": ("Occurred On", "max")},
    ).reset_index()
    out["Total Outage Minutes"] = (grouped["Alarm Duration Seconds"].sum() / 60).round(1).values
    out["Avg Outage Minutes"] = (grouped["Alarm Duration Seconds"].mean() / 60).round(1).values
    out["Longest Outage Minutes"] = (grouped["Alarm Duration Seconds"].max() / 60).round(1).values
    return out[columns].sort_values("Total Outage Minutes", ascending=False)


def build_daily_trend(ledger: pd.DataFrame) -> pd.DataFrame:
    columns = ["Date", "Total Alarms", "Critical", "Major", "Minor", "Warning",
               "P1", "P2", "P3", "Service Outage Count"]
    if ledger.empty:
        return pd.DataFrame(columns=columns)
    working = ledger.copy()
    working["Date"] = working["Occurred On"].dt.strftime("%Y-%m-%d")
    rows = []
    for date, group in working.groupby("Date"):
        rows.append({
            "Date": date,
            "Total Alarms": len(group),
            "Critical": int((group["Severity"] == "Critical").sum()),
            "Major": int((group["Severity"] == "Major").sum()),
            "Minor": int((group["Severity"] == "Minor").sum()),
            "Warning": int((group["Severity"] == "Warning").sum()),
            "P1": int((group["Priority"] == "P1").sum()),
            "P2": int((group["Priority"] == "P2").sum()),
            "P3": int((group["Priority"] == "P3").sum()),
            "Service Outage Count": int((group["Category"] == "Service Outage").sum()),
        })
    return pd.DataFrame(rows, columns=columns).sort_values("Date")


def build_security_incidents(ledger: pd.DataFrame) -> pd.DataFrame:
    columns = ["Occurred On", "Site", "Name", "Severity", "Alarm Duration Seconds", "Source"]
    renamed = ["Occurred On", "Site", "Name", "Severity", "Duration (sec)", "Source System"]
    security = ledger[ledger["Category"] == "Security / Core Protection"] if not ledger.empty else ledger
    if security.empty:
        return pd.DataFrame(columns=renamed)
    out = security[columns].rename(columns=dict(zip(columns, renamed)))
    return out.sort_values("Occurred On", ascending=False)


def build_dashboard(ledger: pd.DataFrame, newly_processed_mae, newly_processed_neteco, chronic_count,
                     chronic_threshold, total_outage_minutes, security_count) -> pd.DataFrame:
    is_root_or_standalone = ledger["Correlation Flag"] != "Correlative alarm" if not ledger.empty else pd.Series(dtype=bool)
    metrics = [
        ("Report generated", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ("New MAE export(s) folded in this run", len(newly_processed_mae)),
        ("New NetEco export(s) folded in this run", len(newly_processed_neteco)),
        ("Latest MAE export used", newly_processed_mae[-1].name if newly_processed_mae else "-"),
        ("Latest NetEco export used", newly_processed_neteco[-1].name if newly_processed_neteco else "-"),
        ("Total alarm records in ledger", len(ledger)),
        ("Root-cause events (excl. correlated symptoms)", int(is_root_or_standalone.sum()) if not ledger.empty else 0),
        ("Critical severity count", int((ledger["Severity"] == "Critical").sum()) if not ledger.empty else 0),
        ("Major severity count", int((ledger["Severity"] == "Major").sum()) if not ledger.empty else 0),
        ("P1 count", int((ledger["Priority"] == "P1").sum()) if not ledger.empty else 0),
        ("P2 count", int((ledger["Priority"] == "P2").sum()) if not ledger.empty else 0),
        ("P3 count", int((ledger["Priority"] == "P3").sum()) if not ledger.empty else 0),
        ("Unique sites in ledger", int(ledger["Site"].nunique()) if not ledger.empty else 0),
        (f"Chronic offender pairs (>= {chronic_threshold} occurrences)", chronic_count),
        ("Total estimated outage minutes (Service Outage category)", round(total_outage_minutes, 1)),
        ("Security incident count", security_count),
    ]
    return pd.DataFrame(metrics, columns=["Metric", "Value"])


def build_methodology(chronic_threshold) -> pd.DataFrame:
    return pd.DataFrame({"Note": [
        f"Chronic Offenders = same Site+Alarm Name pair recurring >= {chronic_threshold} times "
        "in the persistent ledger (HISTORICAL_CHRONIC_THRESHOLD).",
        f"All aggregate sheets (Dashboard, Daily Trend, Category Rollup, Top Offending Alarms, "
        f"Chronic Offenders, Site Downtime Summary, Security Incidents) read the FULL ledger, "
        f"however far back it goes. Only the two raw per-alarm sheets are capped to the last "
        f"{RAW_SHEET_LOOKBACK_DAYS} days (HISTORICAL_RAW_SHEET_LOOKBACK_DAYS) to keep this "
        f"workbook a manageable size - the ledger CSV itself keeps everything.",
        "The ledger accumulates across every scraper cycle (append/update keyed on "
        "Source+Site+Name+Occurred On), so it can see patterns beyond any single export's "
        "rolling 7-10 day window - the raw exports alone cannot.",
        "Correlation Flag comes directly from the MAE/NetEco export: 'Root alarm' = the "
        "triggering fault, 'Correlative alarm' = a symptom linked to a root alarm, "
        "'-' = standalone/not correlated. All alarms are counted in the frequency/chronic "
        "sheets (they reflect real customer-facing impact); the Dashboard sheet separately "
        "reports the root-cause-only event count for comparison.",
        "Site Downtime Summary only sums alarms classified as 'Service Outage' (NE Is "
        "Disconnected, NodeB Unavailable, Cell Unavailable, GSM Cell out of Service, etc.) - "
        "not every alarm category.",
        "Category/Priority classification is shared with the current-alarm triage report "
        "(processing/alarm_taxonomy.py) so both reports agree on what matters.",
    ]})


def build_historical_report(mae_exports, neteco_exports, ledger_path: Path, chronic_threshold: int,
                             output_path: Path) -> Path:
    """mae_exports/neteco_exports are every export currently on disk for that
    source (see find_all_exports); only the ones not already in the
    processed-exports ledger (by content hash) actually get parsed, so an
    export that was already folded into the alarm ledger - including one
    recovered late from a stray download - is never double-counted."""
    processed_tracker = load_processed_exports_ledger(ledger_path)
    frames = []
    newly_processed_mae = []
    newly_processed_neteco = []

    for export_path, source, bucket in (
        *((p, "MAE", newly_processed_mae) for p in mae_exports),
        *((p, "NetEco", newly_processed_neteco) for p in neteco_exports),
    ):
        fingerprint = file_fingerprint(export_path)
        if fingerprint in processed_tracker:
            continue
        log(f"Folding in new {source} export: {export_path.name}")
        frames.append(load_historical_export(export_path, source))
        processed_tracker[fingerprint] = {
            "source": source,
            "source_name": export_path.name,
            "processed_at": datetime.now().isoformat(timespec="seconds"),
        }
        bucket.append(export_path)

    combined = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()

    ledger = load_ledger(ledger_path)
    ledger = upsert_ledger(ledger, combined)
    for column in ("Occurred On", "Cleared On", "First Seen", "Last Seen"):
        ledger[column] = pd.to_datetime(ledger[column], errors="coerce")
    ledger["Alarm Duration Seconds"] = pd.to_numeric(ledger["Alarm Duration Seconds"], errors="coerce")
    reclassify_ledger(ledger)
    save_ledger(ledger, ledger_path)
    save_processed_exports_ledger(ledger_path, processed_tracker)

    category_rollup = build_category_rollup(ledger)
    top_alarms = build_top_alarms(ledger)
    chronic = build_chronic_offenders(ledger, chronic_threshold)
    site_downtime = build_site_downtime(ledger)
    daily_trend = build_daily_trend(ledger)
    security = build_security_incidents(ledger)
    dashboard = build_dashboard(
        ledger, newly_processed_mae, newly_processed_neteco, len(chronic), chronic_threshold,
        site_downtime["Total Outage Minutes"].sum() if not site_downtime.empty else 0.0,
        len(security),
    )
    methodology = build_methodology(chronic_threshold)

    recent_cutoff = pd.Timestamp.now() - pd.Timedelta(days=RAW_SHEET_LOOKBACK_DAYS)
    recent_ledger = ledger[ledger["Occurred On"] >= recent_cutoff] if not ledger.empty else ledger

    ensure_dir(output_path.parent)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        dashboard.to_excel(writer, sheet_name="Dashboard", index=False)
        daily_trend.to_excel(writer, sheet_name="Daily Trend", index=False)
        category_rollup.to_excel(writer, sheet_name="Category Rollup", index=False)
        top_alarms.to_excel(writer, sheet_name="Top Offending Alarms", index=False)
        chronic.to_excel(writer, sheet_name="Chronic Offenders", index=False)
        site_downtime.to_excel(writer, sheet_name="Site Downtime Summary", index=False)
        security.to_excel(writer, sheet_name="Security Incidents", index=False)
        recent_ledger[recent_ledger["Source"] == "MAE"].to_excel(writer, sheet_name="MAE Raw (Classified)",
                                                                  index=False)
        recent_ledger[recent_ledger["Source"] == "NetEco"].to_excel(writer, sheet_name="NetEco Raw (Classified)",
                                                                     index=False)
        methodology.to_excel(writer, sheet_name="Methodology", index=False)

    priority_columns = {}
    if "Priority" in category_rollup.columns:
        priority_columns["Category Rollup"] = list(category_rollup.columns).index("Priority") + 1
    if "Priority" in top_alarms.columns:
        priority_columns["Top Offending Alarms"] = list(top_alarms.columns).index("Priority") + 1
    format_workbook(output_path, priority_columns=priority_columns)

    write_snapshot(SHARED_FOLDER, dashboard, category_rollup, top_alarms, chronic, site_downtime, daily_trend,
                    security)
    return output_path


def _json_safe_records(df: pd.DataFrame):
    if df.empty:
        return []
    df = df.copy()
    for column in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[column]):
            df[column] = df[column].dt.strftime("%Y-%m-%d %H:%M:%S")
    df = df.where(pd.notna(df), None)
    return df.to_dict(orient="records")


def write_snapshot(shared_dir: Path, dashboard, category_rollup, top_alarms, chronic, site_downtime, daily_trend,
                    security):
    import json
    ensure_dir(shared_dir)
    snapshot = {
        "generated_at": datetime.now().isoformat(),
        "dashboard": _json_safe_records(dashboard),
        "category_rollup": _json_safe_records(category_rollup),
        "top_alarms": _json_safe_records(top_alarms),
        "chronic_offenders": _json_safe_records(chronic),
        "site_downtime": _json_safe_records(site_downtime),
        "daily_trend": _json_safe_records(daily_trend),
        "security_incidents": _json_safe_records(security),
    }
    snapshot_path = shared_dir / "historical_insights_snapshot.json"
    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, default=str)


def run_once(output: str = "") -> Path:
    recovered = recover_stray_historical_downloads(
        [MAE_DOWNLOAD_DIR, NETECO_DOWNLOAD_DIR], MAE_EXPORT_DIR, NETECO_EXPORT_DIR, log
    )
    if recovered:
        log(f"Recovered {len(recovered)} stray historical export(s) from the download folder(s)")

    mae_exports = find_all_exports(MAE_EXPORT_DIR, "HistoricalAlarms_MAE_*.*")
    neteco_exports = find_all_exports(NETECO_EXPORT_DIR, "NetEco_Historical_Alarm_*.*")
    if not mae_exports and not neteco_exports:
        raise FileNotFoundError(
            f"No historical alarm exports found under {MAE_EXPORT_DIR} or {NETECO_EXPORT_DIR}"
        )

    log(f"MAE exports on disk: {len(mae_exports)}; NetEco exports on disk: {len(neteco_exports)}")

    output_path = (Path(output).expanduser().resolve() if output
                   else ensure_dir(OUTPUT_DIR) / f"Historical_Alarms_Analysis_{datetime.now():%Y%m%d_%H%M%S}.xlsx")
    saved = build_historical_report(mae_exports, neteco_exports, LEDGER_PATH, CHRONIC_THRESHOLD, output_path)
    log(f"Historical NOC analysis saved: {saved}")

    try:
        shared_dir = ensure_dir(SHARED_FOLDER)
        shutil.copy2(saved, shared_dir / "Live_Historical_Alarms_Analysis.xlsx")
        log(f"Shared live report updated: {shared_dir / 'Live_Historical_Alarms_Analysis.xlsx'}")
    except OSError as exc:
        log(f"WARNING: Could not update shared file, it might be open: {exc}")

    return saved


def main():
    args = parse_args()

    if args.once or args.output:
        run_once(args.output)
        return

    log("Historical NOC analysis loop is running.")
    log(f"MAE export dir: {MAE_EXPORT_DIR}")
    log(f"NetEco export dir: {NETECO_EXPORT_DIR}")
    log(f"Ledger: {LEDGER_PATH}")
    log(f"Loop interval: {INTERVAL_SECONDS // 60} minutes")

    while True:
        try:
            run_once()
        except Exception as exc:
            log(f"ERROR: Analysis cycle failed: {exc}")

        log(f"Sleeping for {INTERVAL_SECONDS // 60} minutes. Press Ctrl+C to stop.")
        try:
            time.sleep(INTERVAL_SECONDS)
        except KeyboardInterrupt:
            log("Analysis loop stopped by user.")
            break


if __name__ == "__main__":
    main()
