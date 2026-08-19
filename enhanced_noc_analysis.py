"""Create an evidence-based NOC Excel report from MAE and both NetEco exports."""
import argparse
import shutil
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from project_config import env_int, env_path, load_env_file


load_env_file()
BASE_DIR = env_path("NOC_BASE_DIR", r"C:\Current_Alarms")
SHARED_FOLDER = env_path("NOC_SHARED_FOLDER", BASE_DIR / "Shared Current Alarms")
INTERVAL_SECONDS = env_int("NOC_ANALYSIS_INTERVAL_SECONDS", 300)

SERVICE_OUTAGE = (
    "NE Is Disconnected", "NodeB Unavailable", "GSM Cell out of Service", "UMTS Cell Unavailable",
    "Cell Unavailable", "Local Cell Unusable", "GSM Local Cell Unusable", "RF Out of Service",
)
TRANSPORT_TERMS = ("SCTP", "S1ap", "X2 Interface", "Link Down", "OML", "CSL", "Ping Failure",
                   "User Plane", "SDH/SONET", "VLAN", "ALD Maintenance Link")
POWER_TERMS = ("DC Input Power", "External Power Supply", "Power Failure")
RADIO_HARDWARE_TERMS = ("BBU", "CPRI", "RF Unit", "RHUB", "Board ", "Optical Module", "Inter-BBU")
RADIO_QUALITY_TERMS = ("VSWR", "RTWP", "RSSI", "RX Channel", "TX Channel", "Radio Link Failure",
                       "Interference Noise")
CAPACITY_TERMS = ("Overload", "congestion", "Resources Used", "Traffic Exceeding", "KPI entity")
LICENSE_TERMS = ("License", "Licensed Feature", "software service fee")
MAINTENANCE_TERMS = ("backup", "Maintenance", "Task execution", "Data Store", "Data Configuration")
SECURITY_TERMS = ("Attack", "Blacklist", "Security", "Insecure", "Weak Algorithms", "Login Attempts",
                  "Changes a User's Password")
CRITICAL_ENERGY_TERMS = (
    "LLVD", "BLVD", "Bus Bar Undervoltage", "DC Under Voltage", "DC Ultra Under Voltage",
    "DC Ultra Undervoltage", "Remaining Capacity Percent Under 30", "Remaining Capacity Percentage Under 30",
    "Overdischarge", "Lithium Battery Protection", "Battery Undervoltage", "Battery Undervoltage Protection",
)
COMMUNICATION_TERMS = ("Communication Between NMS And NE Is Abnormal", "Communication Failure")
SEVERITY_ORDER = {"Critical": 4, "Major": 3, "Minor": 2, "Warning": 1}


def parse_args():
    parser = argparse.ArgumentParser(description="Build an enhanced site-centric NOC report")
    parser.add_argument("--date-folder", default="", help="Dated NOC folder; defaults to the latest YYYY-MM-DD folder")
    parser.add_argument("--output", default="", help="Optional full path of the workbook to create")
    parser.add_argument("--once", action="store_true",
                         help="Build a single report and exit instead of looping continuously")
    return parser.parse_args()


def log(message):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def ensure_dir(path):
    Path(path).mkdir(parents=True, exist_ok=True)
    return Path(path)


def latest_date_folder(base_dir: Path) -> Path:
    folders = [p for p in base_dir.iterdir() if p.is_dir()]
    dated = [p for p in folders if len(p.name) == 10 and p.name[4] == "-" and p.name[7] == "-"]
    if not dated:
        raise FileNotFoundError(f"No dated report folders found under {base_dir}")
    return max(dated, key=lambda p: p.stat().st_mtime)


def latest_file(folder: Path, pattern: str) -> Path:
    files = list(folder.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No {pattern} file found in {folder}")
    return max(files, key=lambda p: p.stat().st_mtime)


def load_export(path: Path) -> pd.DataFrame:
    data = pd.read_csv(path, skiprows=7)
    data = data.iloc[:, 1:].copy()  # NetEco/MAE export metadata column
    for column in data.select_dtypes(include=["object", "string"]):
        data[column] = data[column].astype(str).str.strip().replace({"-": pd.NA, "": pd.NA})
    return data


def normalize_site(series: pd.Series) -> pd.Series:
    return (series.astype(str).str.replace("(FN)", "", regex=False).str.strip()
            .replace({"-": pd.NA, "nan": pd.NA, "": pd.NA}))


def has_term(names, terms) -> bool:
    return any(any(term.lower() in str(name).lower() for term in terms) for name in names)


def classify_mae_alarm(name: str) -> tuple[str, str]:
    text = str(name or "")
    if text in SERVICE_OUTAGE:
        return "Service Outage", "P1" if text in {"NE Is Disconnected", "NodeB Unavailable"} else "P2"
    if has_term([text], SECURITY_TERMS):
        return "Security / Core Protection", "P3"
    if has_term([text], LICENSE_TERMS):
        return "License / Entitlement", "P3"
    if has_term([text], POWER_TERMS):
        return "RAN Power", "P2"
    if has_term([text], TRANSPORT_TERMS):
        return "Transport / Connectivity", "P2"
    if has_term([text], RADIO_HARDWARE_TERMS):
        return "RAN Hardware", "P2"
    if has_term([text], RADIO_QUALITY_TERMS):
        return "Radio Quality", "P3"
    if has_term([text], CAPACITY_TERMS):
        return "Capacity / Performance", "P3"
    if has_term([text], MAINTENANCE_TERMS):
        return "Maintenance / Management", "P3"
    if "Clock" in text:
        return "Synchronization", "P2"
    if any(term in text for term in ("OpenStack", "Server", "Pool", "S-CSCF", "ASBC", "DIMM")):
        return "Core / IT Platform", "P2"
    return "Other / Review", "P3"


def severity_max(values) -> str:
    values = [value for value in values if pd.notna(value)]
    return max(values, key=lambda value: SEVERITY_ORDER.get(str(value), 0), default="-")


def join_unique(values) -> str:
    return " | ".join(sorted({str(value) for value in values if pd.notna(value) and str(value) != "-"}))


def build_triage(mae: pd.DataFrame, power: pd.DataFrame, neteco_all: pd.DataFrame) -> pd.DataFrame:
    mae = mae.copy()
    mae["Site"] = normalize_site(mae["MO Name"])
    mae[["MAE Category", "MAE Priority"]] = mae["Name"].apply(lambda value: pd.Series(classify_mae_alarm(value)))
    mae["Last Occurred Parsed"] = pd.to_datetime(mae["Last Occurred (NT)"], errors="coerce")
    mae["First Occurred Parsed"] = (
        pd.to_datetime(mae["First Occurred (NT)"], errors="coerce")
        if "First Occurred (NT)" in mae.columns else pd.NaT
    )

    power = power.copy()
    power["Site"] = normalize_site(power["Site Name"])
    power["Last Occurred Parsed"] = pd.to_datetime(power["Last Occurred"], errors="coerce")
    power["First Occurred Parsed"] = (
        pd.to_datetime(power["First Occurred"], errors="coerce")
        if "First Occurred" in power.columns else pd.NaT
    )

    neteco_all = neteco_all.copy().drop_duplicates(subset=["Site Name", "Name", "Alarm ID"])
    neteco_all["Site"] = normalize_site(neteco_all["Site Name"])
    neteco_all["Last Occurred Parsed"] = pd.to_datetime(neteco_all["Last Occurred"], errors="coerce")

    mae_groups = mae.dropna(subset=["Site"]).groupby("Site")
    power_groups = power.dropna(subset=["Site"]).groupby("Site")
    all_groups = neteco_all.dropna(subset=["Site"]).groupby("Site")
    relevant_sites = set(mae.loc[mae["MAE Priority"].isin(["P1", "P2"]), "Site"].dropna())
    relevant_sites.update(power["Site"].dropna())

    records = []
    for site in sorted(relevant_sites):
        mae_site = mae_groups.get_group(site) if site in mae_groups.groups else pd.DataFrame()
        power_site = power_groups.get_group(site) if site in power_groups.groups else pd.DataFrame()
        all_site = all_groups.get_group(site) if site in all_groups.groups else pd.DataFrame()
        mae_names = set(mae_site.get("Name", pd.Series(dtype=str)).dropna())
        all_names = set(all_site.get("Name", pd.Series(dtype=str)).dropna())
        ne_disconnected = "NE Is Disconnected" in mae_names
        mains_failure = "Mains Failure" in set(power_site.get("Name", pd.Series(dtype=str)).dropna())
        energy_critical = has_term(all_names, CRITICAL_ENERGY_TERMS)
        comm_abnormal = has_term(all_names, COMMUNICATION_TERMS)

        if ne_disconnected and mains_failure and energy_critical:
            priority, cause, confidence, owner = "P1", "Confirmed power outage with DC/battery depletion", "High", "Energy + Field + NOC"
        elif ne_disconnected and mains_failure:
            priority, cause, confidence, owner = "P2", "Confirmed mains outage; DC/battery state not evidenced", "High", "Energy + Field"
        elif ne_disconnected and energy_critical:
            priority, cause, confidence, owner = "P2", "Suspected DC/energy-system failure", "Medium", "Energy + Field"
        elif ne_disconnected and comm_abnormal:
            priority, cause, confidence, owner = "P2", "Suspected transport/NMS communication failure", "Medium", "Transmission + NOC"
        elif ne_disconnected:
            priority, cause, confidence, owner = "P2", "NE/transport outage; root cause pending", "Low", "NOC investigation"
        elif mains_failure and energy_critical:
            priority, cause, confidence, owner = "P3", "Power risk with critical DC/battery condition; no NE outage yet", "High", "Energy"
        elif mains_failure:
            priority, cause, confidence, owner = "P3", "Mains failure; service currently retained", "High", "Energy"
        else:
            priority = min(mae_site.get("MAE Priority", pd.Series(["P3"])).tolist(), default="P3")
            cause, confidence, owner = "MAE technical alarm; inspect classified category", "Medium", "NOC / RAN"

        first_times = pd.concat([mae_site.get("First Occurred Parsed", pd.Series(dtype="datetime64[ns]")),
                                 power_site.get("First Occurred Parsed", pd.Series(dtype="datetime64[ns]"))])
        last_times = pd.concat([mae_site.get("Last Occurred Parsed", pd.Series(dtype="datetime64[ns]")),
                                power_site.get("Last Occurred Parsed", pd.Series(dtype="datetime64[ns]")),
                                all_site.get("Last Occurred Parsed", pd.Series(dtype="datetime64[ns]"))])
        first_time, last_time = first_times.min(), last_times.max()
        duration = "-" if pd.isna(first_time) or pd.isna(last_time) else round((last_time - first_time).total_seconds() / 60, 1)
        records.append({
            "Priority": priority, "Site": site, "Service Impact": "NE Is Disconnected" if ne_disconnected else join_unique(mae_site.get("MAE Category", [])),
            "Primary Root Cause": cause, "Confidence": confidence, "Owner Team": owner,
            "MAE Severity": severity_max(mae_site.get("Severity", [])), "MAE Alarm Categories": join_unique(mae_site.get("MAE Category", [])),
            "MAE Active Alarms": join_unique(mae_site.get("Name", [])), "Mains Failure": "Yes" if mains_failure else "No",
            "NetEco Power Alarms": join_unique(power_site.get("Name", [])), "Critical DC/Battery Evidence": "Yes" if energy_critical else "No",
            "NetEco All Evidence": join_unique(all_site.get("Name", [])), "First Occurred": first_time,
            "Last Occurred": last_time, "Duration Minutes": duration,
            "Recommended Action": "Escalate immediately; verify grid, genset, batteries, and recovery" if priority == "P1" else "Investigate and assign to owner team",
        })
    result = pd.DataFrame(records)
    # Convert datetime columns to string format to avoid Excel corruption
    result["First Occurred"] = result["First Occurred"].dt.strftime("%Y-%m-%d %H:%M:%S").where(result["First Occurred"].notna(), "-")
    result["Last Occurred"] = result["Last Occurred"].dt.strftime("%Y-%m-%d %H:%M:%S").where(result["Last Occurred"].notna(), "-")
    return result.sort_values(["Priority", "Last Occurred", "Site"], ascending=[True, False, True])


def format_workbook(path: Path):
    workbook = load_workbook(path)
    priority_fills = {"P1": "C00000", "P2": "F4B183", "P3": "FFF2CC"}
    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1F4E78")
        for row in range(2, sheet.max_row + 1):
            if sheet.title == "NOC Site Triage":
                value = sheet.cell(row, 1).value
                if value in priority_fills:
                    sheet.cell(row, 1).fill = PatternFill("solid", fgColor=priority_fills[value])
                    sheet.cell(row, 1).font = Font(bold=True)
        for column in range(1, sheet.max_column + 1):
            values = [len(str(sheet.cell(row, column).value or "")) for row in range(1, min(sheet.max_row, 200) + 1)]
            sheet.column_dimensions[get_column_letter(column)].width = min(max(values, default=10) + 2, 55)
    workbook.save(path)


def build_report(folder: Path, output: Path = None) -> Path:
    mae_file = latest_file(folder, "CurrentAlarms_MAE_*.csv")
    power_file = latest_file(folder, "CurrentAlarms_NetEco_*.csv")
    all_file = latest_file(folder, "NetEco_All_Current_Alarm_*.csv")
    mae, power, neteco_all = load_export(mae_file), load_export(power_file), load_export(all_file)
    triage = build_triage(mae, power, neteco_all)

    mae["Site"] = normalize_site(mae["MO Name"])
    mae[["NOC Category", "NOC Priority"]] = mae["Name"].apply(lambda value: pd.Series(classify_mae_alarm(value)))
    mae_summary = (mae.groupby(["NOC Category", "NOC Priority", "Name", "Severity"], dropna=False)
                   .agg(Active_Alarms=("Name", "size"), Affected_Sites=("Site", "nunique"))
                   .reset_index().sort_values(["NOC Priority", "Affected_Sites"], ascending=[True, False]))
    dashboard = pd.DataFrame({"Metric": ["Report generated", "MAE active alarms", "MAE affected MOs", "MAE NE Is Disconnected sites",
                                            "NetEco mains-failure sites", "NetEco All unique active alarm records", "P1 sites", "P2 sites", "P3 sites"],
                              "Value": [datetime.now().strftime("%Y-%m-%d %H:%M:%S"), len(mae), mae["Site"].nunique(),
                                        mae.loc[mae["Name"].eq("NE Is Disconnected"), "Site"].nunique(),
                                        power.loc[power["Name"].eq("Mains Failure"), "Site Name"].nunique(),
                                        len(neteco_all.drop_duplicates(subset=["Site Name", "Name", "Alarm ID"])),
                                        (triage["Priority"] == "P1").sum(), (triage["Priority"] == "P2").sum(), (triage["Priority"] == "P3").sum()]})
    policy = pd.DataFrame({"Rule": ["P1", "P2", "P2", "P3", "MAE primary impact"],
                           "Definition": ["NE Is Disconnected + Mains Failure + critical DC/battery evidence", "NE Is Disconnected + Mains Failure", "NE Is Disconnected without power evidence; investigate transport/NMS/NE", "Mains/energy alarm with service retained", "NE Is Disconnected; NodeB Unavailable; Cell Unavailable / out of service"]})
    output = output or folder / f"Enhanced_NOC_Analysis_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        dashboard.to_excel(writer, sheet_name="Dashboard", index=False)
        triage.to_excel(writer, sheet_name="NOC Site Triage", index=False)
        triage[triage["Priority"] == "P1"].to_excel(writer, sheet_name="P1 Power Battery Critical", index=False)
        triage[(triage["Priority"] == "P2") & triage["Service Impact"].eq("NE Is Disconnected")].to_excel(writer, sheet_name="P2 Service Outages", index=False)
        triage[triage["Priority"] == "P3"].to_excel(writer, sheet_name="P3 Power Risk", index=False)
        mae_summary.to_excel(writer, sheet_name="MAE Alarm Summary", index=False)
        mae.to_excel(writer, sheet_name="MAE Alarm Classification", index=False)
        power.to_excel(writer, sheet_name="NetEco Power Raw", index=False)
        neteco_all.drop_duplicates(subset=["Site Name", "Name", "Alarm ID"]).to_excel(writer, sheet_name="NetEco All Raw", index=False)
        policy.to_excel(writer, sheet_name="Alarm Policy", index=False)
    format_workbook(output)
    return output


def run_once(date_folder="", output=""):
    folder = Path(date_folder).expanduser().resolve() if date_folder else latest_date_folder(BASE_DIR)
    output_path = Path(output).expanduser().resolve() if output else None
    log(f"Processing folder: {folder}")
    saved = build_report(folder, output_path)
    log(f"Enhanced NOC report saved: {saved}")

    try:
        shared_dir = ensure_dir(SHARED_FOLDER)
        shutil.copy2(saved, shared_dir / "Live_Enhanced_NOC_Analysis.xlsx")
        log(f"Shared live report updated: {shared_dir / 'Live_Enhanced_NOC_Analysis.xlsx'}")
    except Exception as exc:
        log(f"WARNING: Could not update shared file, it might be open: {exc}")

    return saved


def main():
    args = parse_args()

    if args.once or args.date_folder or args.output:
        run_once(args.date_folder, args.output)
        return

    log("Enhanced NOC analysis loop is running.")
    log(f"Input base folder: {BASE_DIR}")
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
