import argparse
import os
import zipfile
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from project_config import env_int, env_path_str, env_str, load_env_file

PROJECT_ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process monthly interference exports and archive band summaries")
    parser.add_argument("--base-dir", type=str, default=None, help="Base folder for subscriber raw data")
    parser.add_argument("--date", type=str, default=None, help="Date folder in YYYYMMDD format")
    parser.add_argument("--output-dir", type=str, default=None, help="Output folder for interference reports")
    parser.add_argument("--archive-dir", type=str, default=None, help="Archive folder for saved historical workbooks")
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
        from ftplib import FTP_TLS, error_temp, error_reply
        import socket

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


def load_interference_csv(file_path: Path) -> Optional[pd.DataFrame]:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as exc:
        print(f"❌ Could not read {file_path}: {exc}")
        return None

    header_idx = None
    for idx, line in enumerate(lines):
        if line.strip().startswith("Date") or line.strip().startswith("Time"):
            header_idx = idx
            break
    if header_idx is None:
        return None

    data_lines = lines[header_idx:]
    if len(data_lines) > 1:
        data_lines = data_lines[:-1]
    return pd.read_csv(StringIO("".join(data_lines)))


def find_interference_files(date_folder: Path) -> Dict[str, Optional[Path]]:
    unzipped_root = date_folder / "unzipped"
    files = {"2G": None, "3G": None, "4G": None}
    if not unzipped_root.exists():
        return files

    for root, _, filenames in os.walk(unzipped_root):
        for filename in filenames:
            lower = filename.lower()
            path = Path(root) / filename
            if filename.startswith("2G Monthly HQ interference_") and filename.endswith(".csv"):
                files["2G"] = path
            elif "(3g)" in lower and "interference" in lower and filename.endswith(".csv"):
                files["3G"] = path
            elif "(4g)" in lower and "interference" in lower and filename.endswith(".csv"):
                files["4G"] = path
    return files


def map_2g_band(band_name: str) -> Optional[int]:
    if pd.isna(band_name):
        return None
    mapping = {
        "DCS1800": 1800,
        "GSM900": 900,
    }
    return mapping.get(str(band_name).strip(), None)


def process_2g_interference(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["Band"] = df["Band"].apply(map_2g_band)
    total_cells = df.groupby("Band")["Cell Name"].nunique().reset_index()
    total_cells.columns = ["Band", "Total count of cells"]

    df = df[~df["Interference Band Proportion (4~5)(%)"].astype(str).str.contains("NIL", na=False)]
    df["Interference Band Proportion (4~5)(%)"] = pd.to_numeric(df["Interference Band Proportion (4~5)(%)"], errors="coerce")
    interfered = df[df["Interference Band Proportion (4~5)(%)"] > 5]
    interfered_count = interfered.groupby("Band")["Cell Name"].nunique().reset_index()
    interfered_count.columns = ["Band", "Count of Cells with External interference"]

    result = pd.merge(total_cells, interfered_count, on="Band", how="left")
    result["Count of Cells with External interference"] = result["Count of Cells with External interference"].fillna(0).astype(int)
    result["year"] = pd.to_datetime(df["Date"], errors="coerce").dt.year.min()
    result["month"] = pd.to_datetime(df["Date"], errors="coerce").dt.strftime("%b").min()
    result["Tech Type"] = "2G"
    result["Branch"] = "East"
    return result[["year", "month", "Tech Type", "Branch", "Band", "Count of Cells with External interference", "Total count of cells"]]


def process_3g_interference(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    df = df.copy()
    df = df[~df["VS.MeanRTWP"].astype(str).str.contains("/0", na=False)]
    df["VS.MeanRTWP"] = pd.to_numeric(df["VS.MeanRTWP"], errors="coerce")
    df = df.dropna(subset=["VS.MeanRTWP"])

    def map_dl_freq(freq):
        if freq in [3054, 3062, 3075]:
            return 900
        if freq in [10562, 10587]:
            return 2100
        return None

    df["Band"] = df["DL FREQ"].apply(map_dl_freq)
    df = df.dropna(subset=["Band"])
    df["Band"] = df["Band"].astype(int)
    df["Time"] = pd.to_datetime(df["Time"], errors="coerce")
    df["Date"] = df["Time"].dt.date

    total_cells = df.groupby("Band")["Cell Name"].nunique().reset_index()
    total_cells.columns = ["Band", "Total count of cells"]
    df["is_interfered_hour"] = df["VS.MeanRTWP"] > -95
    daily_summary = df.groupby(["Cell Name", "Date"], as_index=False)["is_interfered_hour"].sum()
    interfered_cells = daily_summary[daily_summary["is_interfered_hour"] >= 6]["Cell Name"].unique()
    interfered_bands = df[df["Cell Name"].isin(interfered_cells)][["Cell Name", "Band"]].drop_duplicates("Cell Name")
    interfered_count = interfered_bands.groupby("Band").size().reset_index(name="Count of Cells with External interference")
    result = pd.merge(total_cells, interfered_count, on="Band", how="left")
    result["Count of Cells with External interference"] = result["Count of Cells with External interference"].fillna(0).astype(int)
    first_time = df["Time"].min()
    result["year"] = first_time.year
    result["month"] = first_time.strftime("%b")
    result["Tech Type"] = "3G"
    result["Branch"] = "East"
    return result[["year", "month", "Tech Type", "Branch", "Band", "Count of Cells with External interference", "Total count of cells"]]


def map_4g_earfcn(value) -> Optional[int]:
    if pd.isna(value):
        return None
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    if value == 1:
        return 2100
    if value == 3:
        return 1800
    if value == 8:
        return 900
    if value == 28:
        return 700
    return None


def process_4g_interference(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    df = df.copy()
    df = df[~df["L.UL.Interference.Avg(dBm)"].astype(str).str.contains("NIL", na=False)]
    df["L.UL.Interference.Avg(dBm)" ] = pd.to_numeric(df["L.UL.Interference.Avg(dBm)"], errors="coerce")
    df = df.dropna(subset=["L.UL.Interference.Avg(dBm)"])
    freq_col = next((col for col in df.columns if "earfcn" in col.lower() or "freq" in col.lower()), None)
    if not freq_col:
        print("⚠️ No frequency column found for 4G interference records.")
        return pd.DataFrame()
    df["Band"] = df[freq_col].apply(map_4g_earfcn)
    df = df.dropna(subset=["Band"])
    df["Band"] = df["Band"].astype(int)
    df["Time"] = pd.to_datetime(df["Time"], errors="coerce")
    df["Date"] = df["Time"].dt.date

    total_cells = df.groupby("Band")["Cell Name"].nunique().reset_index()
    total_cells.columns = ["Band", "Total count of cells"]
    df["is_interfered_hour"] = df["L.UL.Interference.Avg(dBm)" ] > -100
    daily_summary = df.groupby(["Cell Name", "Date"], as_index=False)["is_interfered_hour"].sum()
    interfered_cells = daily_summary[daily_summary["is_interfered_hour"] >= 6]["Cell Name"].unique()
    interfered_bands = df[df["Cell Name"].isin(interfered_cells)][["Cell Name", "Band"]].drop_duplicates("Cell Name")
    interfered_count = interfered_bands.groupby("Band").size().reset_index(name="Count of Cells with External interference")
    result = pd.merge(total_cells, interfered_count, on="Band", how="left")
    result["Count of Cells with External interference"] = result["Count of Cells with External interference"].fillna(0).astype(int)
    first_time = df["Time"].min()
    result["year"] = first_time.year
    result["month"] = first_time.strftime("%b")
    result["Tech Type"] = "4G"
    result["Branch"] = "East"
    return result[["year", "month", "Tech Type", "Branch", "Band", "Count of Cells with External interference", "Total count of cells"]]


def save_interference_report(results: Dict[str, pd.DataFrame], output_dir: Path, date_folder: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"Subscribers_Interference_Report_{date_folder.name}.xlsx"
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for sheet_name, df in results.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    print(f"✅ Saved interference report to {output_path}")
    return output_path


def save_archive(archive_dir: Path, results: Dict[str, pd.DataFrame], date_folder: Path) -> Optional[Path]:
    archive_dir.mkdir(parents=True, exist_ok=True)
    date_range = date_folder.name
    archive_path = archive_dir / f"Subscribers_Interference_History_{date_range}.xlsx"
    with pd.ExcelWriter(archive_path, engine="openpyxl") as writer:
        for sheet_name, df in results.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    print(f"✅ Archived interference workbook to {archive_path}")
    return archive_path


def load_or_create_history_file(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_excel(path, engine="openpyxl")


def update_history(history_path: Path, results: Dict[str, pd.DataFrame]) -> Optional[Path]:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_or_create_history_file(history_path)
    if existing.empty:
        existing = pd.DataFrame()

    if results.get("2G") is not None and not results["2G"].empty:
        existing = pd.concat([existing, results["2G"]], ignore_index=True)
    if results.get("3G") is not None and not results["3G"].empty:
        existing = pd.concat([existing, results["3G"]], ignore_index=True)
    if results.get("4G") is not None and not results["4G"].empty:
        existing = pd.concat([existing, results["4G"]], ignore_index=True)

    if existing.empty:
        return history_path

    dedup_cols = ["year", "month", "Tech Type", "Branch", "Band"]
    existing = existing.drop_duplicates(subset=dedup_cols, keep="last")
    existing = existing.sort_values(dedup_cols).reset_index(drop=True)

    with pd.ExcelWriter(history_path, engine="openpyxl") as writer:
        existing.to_excel(writer, sheet_name="Interference_History", index=False)
    print(f"✅ Updated interference history at {history_path}")
    return history_path


def main() -> int:
    load_env_file()
    args = parse_args()
    base_dir = Path(args.base_dir) if args.base_dir else Path(env_path_str("SUBSCRIBERS_RAW_DIR", PROJECT_ROOT / "Subscribers" / "Raw Data"))
    if args.date:
        date_folder = base_dir / args.date
    else:
        date_folder = base_dir / datetime.now().strftime("%Y%m%d")

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

    files = find_interference_files(date_folder)
    if not any(files.values()):
        print("❌ No interference files found in the unzipped folder.")
        return 1

    results = {}
    if files["2G"]:
        print(f"📂 Found 2G interference file: {files['2G']}")
        df_2g = load_interference_csv(files["2G"])
        if df_2g is not None:
            results["2G"] = process_2g_interference(df_2g)
    if files["3G"]:
        print(f"📂 Found 3G interference file: {files['3G']}")
        df_3g = load_interference_csv(files["3G"])
        if df_3g is not None:
            results["3G"] = process_3g_interference(df_3g)
    if files["4G"]:
        print(f"📂 Found 4G interference file: {files['4G']}")
        df_4g = load_interference_csv(files["4G"])
        if df_4g is not None:
            results["4G"] = process_4g_interference(df_4g)

    output_dir = Path(args.output_dir) if args.output_dir else base_dir / "Monthly_Interference_Output"
    archive_dir = Path(args.archive_dir) if args.archive_dir else base_dir / "Historical_Archive"

    report_path = save_interference_report(results, output_dir, date_folder)
    update_history(archive_dir / f"Subscribers_Interference_History.xlsx", results)
    save_archive(archive_dir, results, date_folder)

    print(f"📍 Base folder: {base_dir}")
    print(f"📄 Report saved: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
