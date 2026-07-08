import argparse
import os
import socket
import sys
import zipfile
from datetime import datetime
from ftplib import FTP_TLS, error_temp, error_reply
from io import StringIO
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from project_config import env_int, env_path_str, env_str, load_env_file

PROJECT_ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download subscriber FTP data and build daily KPI reports")
    parser.add_argument("--base-dir", type=str, default=None, help="Base folder for subscriber raw data")
    parser.add_argument("--date", type=str, default=None, help="Date folder in YYYYMMDD format")
    parser.add_argument("--output-dir", type=str, default=None, help="Output folder for daily reports")
    parser.add_argument("--history-file", type=str, default=None, help="Excel history file path")
    parser.add_argument("--skip-download", action="store_true", help="Skip FTPS download and use existing local files")
    parser.add_argument("--ftp-host", type=str, default=None, help="Override FTPS host")
    parser.add_argument("--ftp-port", type=int, default=None, help="Override FTPS port")
    parser.add_argument("--ftp-username", type=str, default=None, help="Override FTPS username")
    parser.add_argument("--ftp-password", type=str, default=None, help="Override FTPS password")
    parser.add_argument("--ftp-remote-path", type=str, default=None, help="Override FTPS remote path")
    parser.add_argument("--ftp-file-pattern", type=str, default=None, help="Override FTPS file pattern")
    parser.add_argument("--ftp-timeout", type=int, default=None, help="Override FTPS timeout seconds")
    return parser.parse_args()


def build_ftp_config(args: argparse.Namespace) -> Dict[str, object]:
    return {
        "host": args.ftp_host or env_str("FTP_HOST"),
        "port": args.ftp_port or env_int("FTP_PORT", 21),
        "username": args.ftp_username or env_str("FTP_USERNAME"),
        "password": args.ftp_password or env_str("FTP_PASSWORD"),
        "remote_path": args.ftp_remote_path or env_str("FTP_REMOTE_PATH", "/ftproot/New"),
        "file_pattern": args.ftp_file_pattern or env_str("FTP_FILE_PATTERN", "*{yyyymmdd}*.zip"),
    }


def ftp_defaults(args: argparse.Namespace) -> Dict[str, object]:
    return {
        "timeout": args.ftp_timeout or env_int("FTP_TIMEOUT_SECONDS", 30),
    }


def download_from_ftp(config: Dict[str, object], base_local_folder: Path, timeout: int = 30) -> Optional[Path]:
    today_str = datetime.now().strftime("%Y%m%d")
    date_folder = base_local_folder / today_str
    zipped_folder = date_folder / "zipped"
    zipped_folder.mkdir(parents=True, exist_ok=True)

    if not config["host"] or not config["username"] or not config["password"]:
        print("❌ FTP credentials are not configured. Skipping download.")
        return None

    print(f"🔐 Connecting to FTPS server {config['host']}...")
    try:
        ftps = FTP_TLS()
        ftps.connect(config["host"], config["port"], timeout=timeout)
        ftps.auth()
        ftps.login(config["username"], config["password"])
        ftps.prot_p()
        ftps.cwd(config["remote_path"])

        files = ftps.nlst()
        downloaded = 0
        for file_name in files:
            if file_name.endswith(".zip") and today_str in file_name:
                local_path = zipped_folder / file_name
                if local_path.exists():
                    print(f"⏭ Skipping (already exists): {file_name}")
                    continue
                print(f"⬇ Downloading: {file_name}")
                with open(local_path, "wb") as f:
                    ftps.retrbinary(f"RETR {file_name}", f.write)
                downloaded += 1
        ftps.quit()
        print(f"✅ FTP done. Downloaded {downloaded} file(s) to {zipped_folder}")
        return date_folder

    except socket.timeout:
        print(f"❌ FTP timeout after {timeout}s – server not reachable.")
    except (ConnectionError, TimeoutError, error_temp, error_reply) as exc:
        print(f"❌ FTP error: {type(exc).__name__}: {exc}")
    except Exception as exc:
        print(f"❌ Unexpected FTP error: {exc}")

    return date_folder if date_folder.exists() else None


def extract_zips(date_folder: Path) -> None:
    zipped_folder = date_folder / "zipped"
    unzipped_root = date_folder / "unzipped"
    if not zipped_folder.exists():
        print(f"⚠️ No 'zipped' folder found in {date_folder}")
        return
    unzipped_root.mkdir(parents=True, exist_ok=True)

    for zip_path in zipped_folder.glob("*.zip"):
        if not zipfile.is_zipfile(zip_path):
            print(f"❌ Not a valid ZIP file: {zip_path.name}")
            continue
        extract_path = unzipped_root / zip_path.stem
        if extract_path.exists() and any(extract_path.iterdir()):
            print(f"⏭ Already extracted: {zip_path.name}")
            continue
        try:
            print(f"📦 Extracting: {zip_path.name} → {extract_path}")
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(extract_path)
            print(f"✅ Extracted: {zip_path.name}")
        except zipfile.BadZipFile:
            print(f"❌ Corrupted ZIP skipped: {zip_path.name}")
        except PermissionError:
            print(f"🔒 Permission denied: {zip_path.name}")
        except Exception as exc:
            print(f"⚠️ Unexpected error extracting {zip_path.name}: {exc}")


def load_clean_csv(file_path: Path) -> Optional[pd.DataFrame]:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as exc:
        print(f"❌ Could not read {file_path}: {exc}")
        return None

    header_index = None
    for idx, line in enumerate(lines):
        if line.strip().startswith("Time,"):
            header_index = idx
            break
    if header_index is None:
        return None

    clean_lines = []
    for line in lines[header_index:]:
        if line.strip().startswith("Total"):
            break
        clean_lines.append(line)

    if not clean_lines:
        return None

    df = pd.read_csv(StringIO("".join(clean_lines)))
    df.replace("NIL", pd.NA, inplace=True)
    return df


def load_all_csvs(unzipped_folder: Path) -> Dict[str, pd.DataFrame]:
    dataframes = {}
    if not unzipped_folder.exists():
        return dataframes
    for root, _, files in os.walk(unzipped_folder):
        for file_name in files:
            if not file_name.lower().endswith(".csv"):
                continue
            file_path = Path(root) / file_name
            df = load_clean_csv(file_path)
            if df is not None:
                dataframes[Path(root).name] = df
    return dataframes


def find_cs(dataframes: Dict[str, pd.DataFrame]) -> Optional[pd.DataFrame]:
    candidates = [name for name in dataframes.keys() if name.lower().startswith("cs roaming")]
    return dataframes.get(candidates[0]) if candidates else None


def find_ps_roaming(dataframes: Dict[str, pd.DataFrame]) -> Optional[pd.DataFrame]:
    candidates = [name for name in dataframes.keys() if name.lower().startswith("ps roaming users")]
    return dataframes.get(candidates[0]) if candidates else None


def find_msc(dataframes: Dict[str, pd.DataFrame]) -> Optional[pd.DataFrame]:
    candidates = [name for name in dataframes.keys() if "msc server kpi" in name.lower()]
    return dataframes.get(candidates[0]) if candidates else None


def find_ps_users(dataframes: Dict[str, pd.DataFrame]) -> Optional[pd.DataFrame]:
    candidates = [name for name in dataframes.keys() if "ps users" in name.lower() or "2g_3g_4g" in name.lower()]
    return dataframes.get(candidates[0]) if candidates else None


def prep(df: pd.DataFrame, col: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["year", "Week", col])
    df = df.copy()
    df["Time"] = pd.to_datetime(df["Time"], errors="coerce")
    df["year"] = df["Time"].dt.year
    df["Week"] = df["Time"].dt.isocalendar().week.apply(lambda x: f"W{int(x):02d}")
    return df[["year", "Week", col]]


def process_cs(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["Time"] = pd.to_datetime(df["Time"], errors="coerce")
    df["weeknumber"] = df["Time"].dt.isocalendar().week
    df["index"] = df["index"].astype(str)
    df = df[df["index"].str.contains("21891", na=False)]
    df["weekday"] = df["Time"].dt.weekday
    df = df[df["weekday"] == 3]
    grouped = df.groupby(["Time", "weeknumber"], as_index=False).agg({
        "Number of Power-on Mobile Phones(entries)": "sum",
        "Number of Registered Subscribers(entries)": "sum",
    })
    if grouped.empty:
        return pd.DataFrame()
    peak = grouped.loc[grouped.groupby("weeknumber")["Number of Power-on Mobile Phones(entries)"].idxmax()]
    return peak


def process_ps_roaming(df: Optional[pd.DataFrame]) -> (pd.DataFrame, pd.DataFrame):
    if df is None or df.empty:
        return pd.DataFrame(), pd.DataFrame()
    df = df.copy()
    df["Time"] = pd.to_datetime(df["Time"], errors="coerce")
    df = df[(df["Mobile country code"] == 606) & (df["Mobile network code"] == 1)]
    df["weeknumber"] = df["Time"].dt.isocalendar().week
    df["weekday"] = df["Time"].dt.weekday
    df = df[df["weekday"] == 3]
    grouped = df.groupby(["Time", "weeknumber"], as_index=False).agg({
        "Iu mode attached Max user number per PLMN(number)": "sum",
        "S1 Mode Maximum Attached Users per PLMN(number)": "sum",
    })
    if grouped.empty:
        return pd.DataFrame(), pd.DataFrame()
    peak_iu = grouped.loc[grouped.groupby("weeknumber")["Iu mode attached Max user number per PLMN(number)"].idxmax()]
    peak_s1 = grouped.loc[grouped.groupby("weeknumber")["S1 Mode Maximum Attached Users per PLMN(number)"].idxmax()]
    return peak_iu, peak_s1


def process_msc(df: Optional[pd.DataFrame]) -> (pd.DataFrame, pd.DataFrame):
    if df is None or df.empty:
        return pd.DataFrame(), pd.DataFrame()
    df = df.copy()
    df["Time"] = pd.to_datetime(df["Time"], errors="coerce")
    df.replace("NIL", 0, inplace=True)
    df["Number of 2G Subscribers in VLR(entries)"] = pd.to_numeric(df["Number of 2G Subscribers in VLR(entries)"], errors="coerce").fillna(0)
    df["Number of 3G Subscribers in VLR(entries)"] = pd.to_numeric(df["Number of 3G Subscribers in VLR(entries)"], errors="coerce").fillna(0)
    df["weeknumber"] = df["Time"].dt.isocalendar().week
    df["weekday"] = df["Time"].dt.weekday
    df = df[df["weekday"] == 3]
    grouped = df.groupby(["Time", "weeknumber"], as_index=False).agg({
        "Number of 2G Subscribers in VLR(entries)": "sum",
        "Number of 3G Subscribers in VLR(entries)": "sum",
    })
    if grouped.empty:
        return pd.DataFrame(), pd.DataFrame()
    peak_2g = grouped.loc[grouped.groupby("weeknumber")["Number of 2G Subscribers in VLR(entries)"].idxmax()]
    peak_3g = grouped.loc[grouped.groupby("weeknumber")["Number of 3G Subscribers in VLR(entries)"].idxmax()]
    return peak_2g, peak_3g


def process_ps_users(df: Optional[pd.DataFrame]) -> (pd.DataFrame, pd.DataFrame, pd.DataFrame):
    if df is None or df.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    df = df.copy()
    df["Time"] = pd.to_datetime(df["Time"], errors="coerce")
    df["weeknumber"] = df["Time"].dt.isocalendar().week
    df["weekday"] = df["Time"].dt.weekday
    df = df[df["weekday"] == 3]
    if df.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    peak_gb = df.loc[df.groupby("weeknumber")["Gb mode maximum attached users(number)"].idxmax()]
    peak_iu = df.loc[df.groupby("weeknumber")["Iu mode maximum attached users(number)"].idxmax()]
    peak_4g = df.loc[df.groupby("weeknumber")["Maximum attached users(number)"].idxmax()]
    return peak_gb, peak_iu, peak_4g


def build_final_dataframe(dataframes: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    peak_cs = process_cs(find_cs(dataframes))
    peak_iu, peak_s1 = process_ps_roaming(find_ps_roaming(dataframes))
    peak_2g, peak_3g = process_msc(find_msc(dataframes))
    peak_gb, peak_iu_users, peak_4g = process_ps_users(find_ps_users(dataframes))

    if peak_cs.empty and peak_gb.empty and peak_iu_users.empty and peak_2g.empty and peak_3g.empty and peak_4g.empty and peak_iu.empty and peak_s1.empty:
        return pd.DataFrame()

    if not peak_cs.empty:
        final_df = prep(peak_cs, "Number of Registered Subscribers(entries)")
        final_df = final_df.rename(columns={
            "Number of Registered Subscribers(entries)": "Number of Registered Subscribers (Almadar in Libyana Metwork)"
        })
        final_df["Branch"] = "East"
    else:
        final_df = pd.DataFrame(columns=["year", "Week", "Branch"])
        final_df["Branch"] = "East"

    if not peak_gb.empty:
        final_df = final_df.merge(
            prep(peak_gb, "Gb mode maximum attached users(number)"),
            on=["year", "Week"], how="outer"
        ).rename(columns={
            "Gb mode maximum attached users(number)": "Maximum number of attached subscribers(GSM In SGSN)"
        })

    if not peak_iu_users.empty:
        final_df = final_df.merge(
            prep(peak_iu_users, "Iu mode maximum attached users(number)"),
            on=["year", "Week"], how="outer"
        ).rename(columns={
            "Iu mode maximum attached users(number)": "Maximum number of attached subscribers(UMTS in SGSN )"
        })

    if not peak_2g.empty:
        final_df = final_df.merge(
            prep(peak_2g, "Number of 2G Subscribers in VLR(entries)"),
            on=["year", "Week"], how="outer"
        ).rename(columns={
            "Number of 2G Subscribers in VLR(entries)": "Number of subscribers in VLR (Connected to BSC)"
        })

    if not peak_3g.empty:
        final_df = final_df.merge(
            prep(peak_3g, "Number of 3G Subscribers in VLR(entries)"),
            on=["year", "Week"], how="outer"
        ).rename(columns={
            "Number of 3G Subscribers in VLR(entries)": "Number of subscribers in VLR (Connected to RNC)"
        })

    if not peak_4g.empty:
        final_df = final_df.merge(
            prep(peak_4g, "Maximum attached users(number)"),
            on=["year", "Week"], how="outer"
        ).rename(columns={
            "Maximum attached users(number)": "Max Number of EPS Attach subscribers in MME"
        })

    if not peak_iu.empty and not peak_s1.empty:
        ps_iu_tmp = prep(peak_iu, "Iu mode attached Max user number per PLMN(number)")
        ps_s1_tmp = prep(peak_s1, "S1 Mode Maximum Attached Users per PLMN(number)")
        ps_merge = ps_iu_tmp.merge(ps_s1_tmp, on=["year", "Week"], how="outer")
        ps_merge["Number of Registered Subscribers (Almadar in Libyana PS Network) for(3G,4G)"] = (
            "3G=" + ps_merge["Iu mode attached Max user number per PLMN(number)"].astype(str)
            + ",4G=" + ps_merge["S1 Mode Maximum Attached Users per PLMN(number)"].astype(str)
        )
        ps_merge = ps_merge[["year", "Week", "Number of Registered Subscribers (Almadar in Libyana PS Network) for(3G,4G)"]]
        final_df = final_df.merge(ps_merge, on=["year", "Week"], how="outer")
    else:
        final_df["Number of Registered Subscribers (Almadar in Libyana PS Network) for(3G,4G)"] = ""

    expected_cols = [
        "year", "Week", "Branch",
        "Maximum number of attached subscribers(GSM In SGSN)",
        "Maximum number of attached subscribers(UMTS in SGSN )",
        "Number of subscribers in VLR (Connected to BSC)",
        "Number of subscribers in VLR (Connected to RNC)",
        "Max Number of EPS Attach subscribers in MME",
        "Number of Registered Subscribers (Almadar in Libyana Metwork)",
        "Number of Registered Subscribers (Almadar in Libyana PS Network) for(3G,4G)"
    ]
    for col in expected_cols:
        if col not in final_df.columns:
            final_df[col] = 0 if col != "Number of Registered Subscribers (Almadar in Libyana PS Network) for(3G,4G)" else ""

    final_df = final_df[expected_cols]
    final_df = final_df.sort_values(["year", "Week"]).reset_index(drop=True)
    return final_df


def save_daily_report(final_df: pd.DataFrame, output_dir: Path, date_folder: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"Subscribers_FTP_Daily_Report_{date_folder.name}.xlsx"
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        final_df.to_excel(writer, sheet_name="Subscribers_KPIs", index=False)
    print(f"✅ Saved daily KPI report to {output_path}")
    return output_path


def save_history(history_path: Path, final_df: pd.DataFrame) -> Path:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    existing = pd.read_excel(history_path, engine="openpyxl") if history_path.exists() else pd.DataFrame()
    if existing.empty:
        merged = final_df.copy()
    else:
        merged = pd.concat([existing, final_df], ignore_index=True)
        merged = merged.drop_duplicates(subset=["year", "Week", "Branch"], keep="last")
    merged = merged.sort_values(["year", "Week"]).reset_index(drop=True)
    with pd.ExcelWriter(history_path, engine="openpyxl") as writer:
        merged.to_excel(writer, sheet_name="Subscribers_FTP_History", index=False)
    print(f"✅ Updated history file at {history_path}")
    return history_path


def find_latest_date_folder(base_dir: Path) -> Optional[Path]:
    if not base_dir.exists():
        return None
    date_folders = [p for p in base_dir.iterdir() if p.is_dir() and p.name.isdigit() and len(p.name) == 8]
    if not date_folders:
        return None
    return max(date_folders)


def main() -> int:
    load_env_file()
    args = parse_args()

    base_dir = Path(args.base_dir) if args.base_dir else Path(env_path_str("SUBSCRIBERS_RAW_DIR", PROJECT_ROOT / "Subscribers" / "Raw Data"))
    output_dir = Path(args.output_dir) if args.output_dir else base_dir / "Daily_Output"
    history_file = Path(args.history_file) if args.history_file else output_dir / "Subscribers_FTP_Daily_History.xlsx"

    if args.date:
        date_folder = base_dir / args.date
    else:
        today_str = datetime.now().strftime("%Y%m%d")
        date_folder = base_dir / today_str

    if not args.skip_download:
        ftp_config = build_ftp_config(args)
        ftp_options = ftp_defaults(args)
        downloaded_folder = download_from_ftp(ftp_config, base_dir, timeout=ftp_options["timeout"])
        if downloaded_folder:
            date_folder = downloaded_folder

    if not date_folder.exists():
        print(f"❌ Date folder does not exist: {date_folder}")
        return 1

    extract_zips(date_folder)
    unzipped_folder = date_folder / "unzipped"
    if not unzipped_folder.exists():
        print(f"❌ No unzipped folder found at {unzipped_folder}")
        return 1

    dataframes = load_all_csvs(unzipped_folder)
    if not dataframes:
        print("❌ No CSV files loaded from unzipped folder.")
        return 1

    final_df = build_final_dataframe(dataframes)
    if final_df.empty:
        print("❌ No KPI data could be processed.")
        return 1

    output_path = save_daily_report(final_df, output_dir, date_folder)
    save_history(history_file, final_df)
    print(f"📍 Base folder: {base_dir}")
    print(f"📦 Processed date folder: {date_folder}")
    print(f"📄 Report saved: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
