import os
import zipfile
import warnings
import pandas as pd
from io import StringIO
from datetime import datetime
import socket
import logging
import paramiko
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from project_config import env_int, env_path_str, env_str, load_env_file

load_env_file()

# openpyxl warns on every workbook that lacks an explicit default style; harmless, just noisy.
warnings.filterwarnings(
    "ignore",
    message="Workbook contains no default style, apply openpyxl's default",
    category=UserWarning,
    module="openpyxl",
)

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
# Per-file download/extract/load chatter goes to DEBUG; console only shows summaries.
logging.getLogger("paramiko").setLevel(logging.WARNING)

# ======================================================
# CENTRALIZED DIRECTORIES (from GUI)
# ======================================================
# Data root from GUI
DATA_ROOT = os.environ.get("DATA_ROOT", r"C:\Users\user\Desktop\Libyana_Data")

# Subscribers paths
SUBSCRIBERS_RAW_DIR = os.path.join(DATA_ROOT, "Subscribers", "Raw Data")
SUBSCRIBERS_OUTPUT_DIR = os.path.join(DATA_ROOT, "Subscribers", "Raw Data", "Subscribers_Output")
INTERFERENCE_OUTPUT_DIR = os.path.join(DATA_ROOT, "Subscribers", "Raw Data", "Interference_Output")
SUBSCRIBERS_HISTORY_FILE = os.path.join(DATA_ROOT, "Subscribers", "Raw Data", "Subscribers_History.xlsx")


# Ensure directories exist
def ensure_dir(path):
    """Create directory if it doesn't exist."""
    if not path:
        return path
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)
        logging.info(f"📁 Created directory: {path}")
    return path


ensure_dir(SUBSCRIBERS_RAW_DIR)
ensure_dir(SUBSCRIBERS_OUTPUT_DIR)
ensure_dir(INTERFERENCE_OUTPUT_DIR)


# ======================================================
# SFTP HANDLER
# ======================================================
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
            logging.debug(f"✅ SFTP connected to {self.host}:{self.port}")
            return True
        except Exception as e:
            logging.error(f"❌ SFTP connection failed: {e}")
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
            logging.error(f"Failed to list files: {e}")
            raise

    def download_file(self, remote_filename, local_path):
        """Download a single file."""
        try:
            local_file = os.path.join(local_path, remote_filename)
            self.sftp.get(remote_filename, local_file)
            logging.debug(f"✅ Downloaded: {remote_filename}")
            return local_file
        except Exception as e:
            logging.error(f"Failed to download {remote_filename}: {e}")
            raise

    def close(self):
        """Close SFTP connection."""
        if self.sftp:
            self.sftp.close()
        if self.transport:
            self.transport.close()
        logging.debug("SFTP connection closed")


# ======================================================
# FTP/SFTP CONFIG
# ======================================================
ftp_config = {
    "host": env_str("FTP_HOST"),
    "port": env_int("FTP_PORT", 22),
    "username": env_str("FTP_USERNAME"),
    "password": env_str("FTP_PASSWORD"),
    "remote_path": env_str("FTP_REMOTE_PATH", "/ftproot/New"),
    "file_pattern": env_str("FTP_FILE_PATTERN", "*{yyyymmdd}*.zip")
}

FTP_TIMEOUT_SECONDS = env_int("FTP_TIMEOUT_SECONDS", 30)

if not ftp_config["host"] or not ftp_config["username"] or not ftp_config["password"]:
    raise RuntimeError("FTP_HOST, FTP_USERNAME, and FTP_PASSWORD must be configured in .env or environment variables.")


# ======================================================
# 0. SFTP DOWNLOAD (saves into date/zipped/)
# ======================================================
def download_from_sftp(config, base_local_folder, timeout=30):
    """Download zip files using SFTP into base_local_folder/YYYYMMDD/zipped/"""
    today_str = datetime.now().strftime("%Y%m%d")
    date_folder = os.path.join(base_local_folder, today_str)
    zipped_folder = os.path.join(date_folder, "zipped")
    os.makedirs(zipped_folder, exist_ok=True)

    host = config["host"]
    port = config["port"]
    username = config["username"]
    password = config["password"]
    remote_path = config["remote_path"]

    logging.debug(f"🔐 Connecting to SFTP server {host}:{port}...")

    sftp_client = None
    downloaded = 0

    try:
        sftp_client = SFTPDownload(host, port, username, password, remote_path, timeout)
        sftp_client.connect()

        logging.debug("Retrieving directory list...")
        files = sftp_client.list_files()
        logging.debug(f"Found {len(files)} total files on remote server.")

        import fnmatch
        expected_pattern = config["file_pattern"].replace("{yyyymmdd}", today_str)
        skipped = 0
        for file in files:
            if file.lower().endswith(".zip") and fnmatch.fnmatch(file, expected_pattern):
                local_path = os.path.join(zipped_folder, file)
                if os.path.exists(local_path):
                    logging.debug(f"⏭ Skipping (already exists): {file}")
                    skipped += 1
                    continue
                logging.debug(f"⬇ Downloading: {file}")
                sftp_client.download_file(file, zipped_folder)
                downloaded += 1

        logging.info(f"✅ SFTP done. Downloaded {downloaded} file(s), skipped {skipped} existing, → {zipped_folder}")
        return date_folder

    except socket.timeout:
        logging.error(f"❌ SFTP timeout after {timeout}s – server not reachable.")
        logging.error(f"   Will use existing files in {date_folder} if any.")
    except (ConnectionError, TimeoutError) as e:
        logging.error(f"❌ Network/Connection Error: {type(e).__name__}: {e}")
        logging.error(f"   Will use existing files in {date_folder} if any.")
    except paramiko.AuthenticationException as e:
        logging.error(f"❌ Authentication failed: {e}")
        logging.error("   Check your FTP_USERNAME and FTP_PASSWORD in .env")
    except Exception as e:
        logging.error(f"❌ Unexpected SFTP error: {e}")
    finally:
        if sftp_client:
            try:
                sftp_client.close()
            except Exception:
                pass

    return date_folder if os.path.exists(date_folder) else None


# ======================================================
# 1. Extract ZIPs into date/unzipped/
# ======================================================
def extract_zips(date_folder):
    """Extract all ZIPs from date_folder/zipped/ into date_folder/unzipped/"""
    if not date_folder or not os.path.exists(date_folder):
        logging.warning(f"⚠️ Date folder does not exist: {date_folder}")
        return

    zipped_folder = os.path.join(date_folder, "zipped")
    unzipped_root = os.path.join(date_folder, "unzipped")

    if not os.path.exists(zipped_folder):
        logging.warning(f"⚠️ No 'zipped' folder found in {date_folder}")
        return

    os.makedirs(unzipped_root, exist_ok=True)

    extracted = 0
    skipped = 0
    for file_name in os.listdir(zipped_folder):
        if not file_name.lower().endswith(".zip"):
            continue
        zip_path = os.path.join(zipped_folder, file_name)
        if not zipfile.is_zipfile(zip_path):
            logging.error(f"❌ Not a valid ZIP file: {file_name}")
            continue

        extract_folder_name = os.path.splitext(file_name)[0]
        extract_path = os.path.join(unzipped_root, extract_folder_name)

        if os.path.exists(extract_path) and os.listdir(extract_path):
            logging.debug(f"⏭ Already extracted: {file_name}")
            skipped += 1
            continue

        try:
            logging.debug(f"📦 Extracting: {file_name} → {extract_path}")
            os.makedirs(extract_path, exist_ok=True)
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                root = Path(extract_path).resolve()
                for member in zip_ref.infolist():
                    target = (root / member.filename).resolve()
                    if target != root and root not in target.parents:
                        raise ValueError(f"Unsafe ZIP member path: {member.filename}")
                zip_ref.extractall(root)
            logging.debug(f"✅ Done: {file_name}")
            extracted += 1
        except zipfile.BadZipFile:
            logging.error(f"❌ Corrupted ZIP skipped: {file_name}")
        except PermissionError:
            logging.error(f"🔒 Permission denied: {file_name}")
        except Exception as e:
            logging.error(f"⚠️ Unexpected error with {file_name}: {e}")

    logging.info(f"✅ Extracted {extracted} new zip(s), skipped {skipped} already-extracted, → {unzipped_root}")


# ======================================================
# 2. Load & Clean a single CSV
# ======================================================
def load_clean_csv(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    header_index = None
    for i, line in enumerate(lines):
        if line.strip().startswith("Time,"):
            header_index = i
            break
    if header_index is None:
        return None
    clean_lines = []
    for line in lines[header_index:]:
        if line.strip().startswith("Total"):
            break
        clean_lines.append(line)
    df = pd.read_csv(StringIO("".join(clean_lines)))
    df.replace("NIL", pd.NA, inplace=True)
    return df


# ======================================================
# 3. Load all CSVs from unzipped folder (recursive)
# ======================================================
def load_clean_excel(file_path):
    """Load an already-clean Huawei-export .xlsx (header on row 1, no preamble)."""
    try:
        df = pd.read_excel(file_path, sheet_name=0)
    except Exception as e:
        logging.error(f"⚠️ Could not read Excel file {file_path}: {e}")
        return None
    if "Time" not in df.columns:
        return None
    df.replace("NIL", pd.NA, inplace=True)
    return df


def load_all_csvs(unzipped_folder):
    """Load CSVs and Excel exports from all subfolders of unzipped_folder"""
    dataframes = {}
    if not os.path.exists(unzipped_folder):
        return dataframes
    for root, dirs, files in os.walk(unzipped_folder):
        for file in files:
            if "Peak" in file:
                continue
            file_path = os.path.join(root, file)
            if file.endswith(".csv"):
                df = load_clean_csv(file_path)
            elif file.endswith(".xlsx"):
                df = load_clean_excel(file_path)
            else:
                continue
            if df is not None:
                key_name = os.path.basename(root)
                dataframes[key_name] = df
    return dataframes


# ======================================================
# 4. Find specific datasets by name
# ======================================================
def find_cs(dataframes):
    candidates = [name for name in dataframes.keys() if name.lower().startswith('cs roaming')]
    if candidates:
        return dataframes[candidates[0]]
    logging.error("❌ CS Roaming dataset not found. Available keys: %s", list(dataframes.keys()))
    return None


def find_ps_roaming(dataframes):
    candidates = [name for name in dataframes.keys() if name.lower().startswith('ps roaming users')]
    if candidates:
        return dataframes[candidates[0]]
    logging.error("❌ PS Roaming dataset not found. Available keys: %s", list(dataframes.keys()))
    return None


def find_msc(dataframes):
    candidates = [name for name in dataframes.keys() if "MSC Server KPI" in name]
    if candidates:
        return dataframes[candidates[0]]
    logging.error("❌ MSC dataset not found. Available keys: %s", list(dataframes.keys()))
    return None


def find_ps_users(dataframes):
    candidates = [name for name in dataframes.keys() if "PS users" in name or "2G_3G_4G" in name]
    if candidates:
        return dataframes[candidates[0]]
    logging.error("❌ PS Users dataset not found. Available keys: %s", list(dataframes.keys()))
    return None


# ======================================================
# 5. Processing functions
# ======================================================
def process_cs(df):
    if df is None:
        return pd.DataFrame()
    df["Time"] = pd.to_datetime(df["Time"], errors="coerce")
    df["index"] = df["index"].astype(str)
    df = df[df["index"].str.contains("21891", na=False)]
    df["weeknumber"] = df["Time"].dt.isocalendar().week
    df["weekday"] = df["Time"].dt.weekday
    df = df[df["weekday"] == 3]
    grouped = df.groupby(["Time", "weeknumber"], as_index=False).agg({
        "Number of Power-on Mobile Phones(entries)": "sum",
        "Number of Registered Subscribers(entries)": "sum"
    })
    if grouped.empty:
        return pd.DataFrame()
    peak = grouped.loc[grouped.groupby("weeknumber")["Number of Power-on Mobile Phones(entries)"].idxmax()]
    return peak


def process_ps_roaming(df):
    if df is None:
        return pd.DataFrame(), pd.DataFrame()
    df["Time"] = pd.to_datetime(df["Time"], errors="coerce")
    df = df[(df["Mobile country code"] == 606) & (df["Mobile network code"] == 1)]
    df["weeknumber"] = df["Time"].dt.isocalendar().week
    df["weekday"] = df["Time"].dt.weekday
    df = df[df["weekday"] == 3]
    grouped = df.groupby(["Time", "weeknumber"], as_index=False).agg({
        "Iu mode attached Max user number per PLMN(number)": "sum",
        "S1 Mode Maximum Attached Users per PLMN(number)": "sum"
    })
    if grouped.empty:
        return pd.DataFrame(), pd.DataFrame()
    peak_iu = grouped.loc[grouped.groupby("weeknumber")["Iu mode attached Max user number per PLMN(number)"].idxmax()]
    peak_s1 = grouped.loc[grouped.groupby("weeknumber")["S1 Mode Maximum Attached Users per PLMN(number)"].idxmax()]
    return peak_iu, peak_s1


def process_msc(df):
    if df is None:
        return pd.DataFrame(), pd.DataFrame()
    df["Time"] = pd.to_datetime(df["Time"], errors="coerce")
    df.replace("NIL", 0, inplace=True)
    df["Number of 2G Subscribers in VLR(entries)"] = pd.to_numeric(df["Number of 2G Subscribers in VLR(entries)"],
                                                                   errors="coerce").fillna(0)
    df["Number of 3G Subscribers in VLR(entries)"] = pd.to_numeric(df["Number of 3G Subscribers in VLR(entries)"],
                                                                   errors="coerce").fillna(0)
    df["weeknumber"] = df["Time"].dt.isocalendar().week
    df["weekday"] = df["Time"].dt.weekday
    df = df[df["weekday"] == 3]
    grouped = df.groupby(["Time", "weeknumber"], as_index=False).agg({
        "Number of 2G Subscribers in VLR(entries)": "sum",
        "Number of 3G Subscribers in VLR(entries)": "sum"
    })
    if grouped.empty:
        return pd.DataFrame(), pd.DataFrame()
    peak_2g = grouped.loc[grouped.groupby("weeknumber")["Number of 2G Subscribers in VLR(entries)"].idxmax()]
    peak_3g = grouped.loc[grouped.groupby("weeknumber")["Number of 3G Subscribers in VLR(entries)"].idxmax()]
    return peak_2g, peak_3g


def process_ps_users(df):
    if df is None:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
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


def prep(df, col):
    if df.empty:
        return pd.DataFrame(columns=["year", "Week", col])
    df["year"] = df["Time"].dt.year
    df["Week"] = df["weeknumber"].apply(lambda x: f"W{int(x):02d}")
    return df[["year", "Week", col]]


# ======================================================
# Interference processing (2G)
# ======================================================
def find_local_interference_csv(date_folder):
    if not date_folder or not os.path.exists(date_folder):
        return None
    unzipped_root = os.path.join(date_folder, "unzipped")
    if not os.path.exists(unzipped_root):
        return None
    for root, dirs, files in os.walk(unzipped_root):
        for file in files:
            if file.startswith("2G Monthly HQ interference_") and file.endswith(".csv"):
                return os.path.join(root, file)
    return None


def load_interference_csv(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    header_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith("Date"):
            header_idx = i
            break
    if header_idx is None:
        raise ValueError("No header row starting with 'Date' found.")
    data_lines = lines[header_idx:]
    if len(data_lines) > 1:
        data_lines = data_lines[:-1]
    df = pd.read_csv(StringIO("".join(data_lines)))
    return df


def process_interference(df):
    interference_col = 'Interference Band Proportion (4~5)(%)'
    band_mapping = {'DCS1800': 1800, 'GSM900': 900}
    df['Band'] = df['Band'].replace(band_mapping)

    total_cells_per_band = df.groupby('Band')['Cell Name'].nunique().reset_index()
    total_cells_per_band.columns = ['Band', 'Total count of cells']

    df_filtered = df[~df[interference_col].astype(str).str.contains('NIL', na=False)]
    df_filtered[interference_col] = pd.to_numeric(df_filtered[interference_col], errors='coerce')

    interfered_df = df_filtered[df_filtered[interference_col] > 5]
    interfered_per_band = interfered_df.groupby('Band')['Cell Name'].nunique().reset_index()
    interfered_per_band.columns = ['Band', 'Count of Cells with External interference']

    result = pd.merge(total_cells_per_band, interfered_per_band, on='Band', how='left')
    result['Count of Cells with External interference'] = result['Count of Cells with External interference'].fillna(
        0).astype(int)

    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    first_date = df['Date'].min()
    result['year'] = first_date.year
    result['month'] = first_date.strftime('%b')
    result['Tech Type'] = '2G'
    result['Branch'] = 'East'

    return result[['year', 'month', 'Tech Type', 'Branch', 'Band',
                   'Count of Cells with External interference', 'Total count of cells']]


def find_3g_interference_csv(date_folder):
    if not date_folder or not os.path.exists(date_folder):
        return None
    unzipped_root = os.path.join(date_folder, "unzipped")
    if not os.path.exists(unzipped_root):
        return None
    for root, dirs, files in os.walk(unzipped_root):
        for file in files:
            if file.lower().endswith('.csv') and '(3g)' in file.lower() and 'interference' in file.lower():
                return os.path.join(root, file)
    return None


def load_3g_interference_csv(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    header_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith('Time'):
            header_idx = i
            break
    if header_idx is None:
        raise ValueError("No header row starting with 'Time' found in 3G interference CSV.")

    data_lines = lines[header_idx:-1]
    df = pd.read_csv(StringIO(''.join(data_lines)))

    df = df[~df['VS.MeanRTWP'].astype(str).str.contains('/0', na=False)]
    df['VS.MeanRTWP'] = pd.to_numeric(df['VS.MeanRTWP'], errors='coerce')
    df = df.dropna(subset=['VS.MeanRTWP'])

    def map_dl_freq(freq):
        if freq in [3054, 3062, 3075]:
            return 900
        elif freq in [10562, 10587]:
            return 2100
        else:
            return None

    df['Band'] = df['DL FREQ'].apply(map_dl_freq)
    df = df.dropna(subset=['Band'])
    df['Band'] = df['Band'].astype(int)

    df['Time'] = pd.to_datetime(df['Time'], errors='coerce')
    df = df.dropna(subset=['Time'])
    df['Date'] = df['Time'].dt.date
    return df


def process_3g_interference(df):
    if df.empty:
        return pd.DataFrame()

    total_cells = df.groupby('Band')['Cell Name'].nunique().reset_index()
    total_cells.columns = ['Band', 'Total count of cells']

    df['is_interfered_hour'] = df['VS.MeanRTWP'] > -95

    daily_cell_summary = df.groupby(['Cell Name', 'Date'])['is_interfered_hour'].sum().reset_index()
    daily_cell_summary.rename(columns={'is_interfered_hour': 'interfered_hours_per_day'}, inplace=True)

    interfered_cells = daily_cell_summary[daily_cell_summary['interfered_hours_per_day'] >= 6]['Cell Name'].unique()

    interfered_cells_with_band = df[df['Cell Name'].isin(interfered_cells)][['Cell Name', 'Band']].drop_duplicates(
        'Cell Name')
    interfered_per_band = interfered_cells_with_band.groupby('Band').size().reset_index(
        name='Count of Cells with External interference')

    result = pd.merge(total_cells, interfered_per_band, on='Band', how='left')
    result['Count of Cells with External interference'] = result['Count of Cells with External interference'].fillna(
        0).astype(int)

    first_date = df['Time'].min()
    result['year'] = first_date.year
    result['month'] = first_date.strftime('%b')
    result['Tech Type'] = '3G'
    result['Branch'] = 'East'

    return result[['year', 'month', 'Tech Type', 'Branch', 'Band',
                   'Count of Cells with External interference', 'Total count of cells']]


def find_4g_interference_csv(date_folder):
    if not date_folder or not os.path.exists(date_folder):
        return None
    unzipped_root = os.path.join(date_folder, "unzipped")
    if not os.path.exists(unzipped_root):
        return None
    for root, dirs, files in os.walk(unzipped_root):
        for file in files:
            if file.lower().endswith('.csv') and '(4g)' in file.lower() and 'interference' in file.lower():
                return os.path.join(root, file)
    return None


def load_4g_interference_csv(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    header_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith('Time'):
            header_idx = i
            break
    if header_idx is None:
        raise ValueError("No header row starting with 'Time' found in 4G interference CSV.")

    data_lines = lines[header_idx:-1]
    df = pd.read_csv(StringIO(''.join(data_lines)))

    df = df[~df['L.UL.Interference.Avg(dBm)'].astype(str).str.contains('NIL', na=False)]
    df['L.UL.Interference.Avg(dBm)'] = pd.to_numeric(df['L.UL.Interference.Avg(dBm)'], errors='coerce')
    df = df.dropna(subset=['L.UL.Interference.Avg(dBm)'])

    freq_col = None
    for col in df.columns:
        if 'earfcn' in col.lower() or 'freq' in col.lower():
            freq_col = col
            break
    if freq_col is None:
        raise KeyError("No frequency column (EARFCN/FREQ) found in 4G interference CSV.")

    def map_earfcn(earfcn):
        if earfcn == 1:
            return 2100
        elif earfcn == 3:
            return 1800
        elif earfcn == 8:
            return 900
        elif earfcn == 28:
            return 700
        else:
            return None

    df['Band'] = df[freq_col].apply(map_earfcn)
    df = df.dropna(subset=['Band'])
    df['Band'] = df['Band'].astype(int)

    df['Time'] = pd.to_datetime(df['Time'], errors='coerce')
    df = df.dropna(subset=['Time'])
    df['Date'] = df['Time'].dt.date
    return df


def process_4g_interference(df):
    if df.empty:
        return pd.DataFrame()

    total_cells = df.groupby('Band')['Cell Name'].nunique().reset_index()
    total_cells.columns = ['Band', 'Total count of cells']

    df['is_interfered_hour'] = df['L.UL.Interference.Avg(dBm)'] > -100

    daily_cell_summary = df.groupby(['Cell Name', 'Date'])['is_interfered_hour'].sum().reset_index()
    daily_cell_summary.rename(columns={'is_interfered_hour': 'interfered_hours_per_day'}, inplace=True)

    interfered_cells = daily_cell_summary[daily_cell_summary['interfered_hours_per_day'] >= 6]['Cell Name'].unique()

    interfered_cells_with_band = df[df['Cell Name'].isin(interfered_cells)][['Cell Name', 'Band']].drop_duplicates(
        'Cell Name')
    interfered_per_band = interfered_cells_with_band.groupby('Band').size().reset_index(
        name='Count of Cells with External interference')

    result = pd.merge(total_cells, interfered_per_band, on='Band', how='left')
    result['Count of Cells with External interference'] = result['Count of Cells with External interference'].fillna(
        0).astype(int)

    first_date = df['Time'].min()
    result['year'] = first_date.year
    result['month'] = first_date.strftime('%b')
    result['Tech Type'] = '4G'
    result['Branch'] = 'East'

    return result[['year', 'month', 'Tech Type', 'Branch', 'Band',
                   'Count of Cells with External interference', 'Total count of cells']]


# ======================================================
# HISTORICAL DATA FUNCTIONS
# ======================================================
def load_historical_data(historical_file_path):
    """Load existing historical data if file exists"""
    if os.path.exists(historical_file_path):
        try:
            logging.info(f"📂 Loading historical data from {historical_file_path}")
            historical_data = pd.read_excel(historical_file_path, sheet_name=None)
            return historical_data
        except Exception as e:
            logging.warning(f"⚠️ Could not load historical file: {e}")
            return None
    return None


def merge_historical_data(new_df, historical_df, key_columns):
    """Merge new data with historical data, avoiding duplicates"""
    if historical_df is None or historical_df.empty:
        return new_df

    for col in key_columns:
        if col in historical_df.columns:
            historical_df[col] = historical_df[col].astype(str)
        if col in new_df.columns:
            new_df[col] = new_df[col].astype(str)

    combined = pd.concat([historical_df, new_df], ignore_index=True)
    combined = combined.drop_duplicates(subset=key_columns, keep='last')

    if 'year' in combined.columns and 'Week' in combined.columns:
        combined['sort_key'] = combined['year'].astype(str) + combined['Week'].str.replace('W', '').str.zfill(2)
        combined = combined.sort_values('sort_key').drop('sort_key', axis=1)
    elif 'year' in combined.columns and 'month' in combined.columns:
        month_order = {'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
                       'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12}
        if 'month' in combined.columns:
            combined['month_num'] = combined['month'].map(month_order)
            combined = combined.sort_values(['year', 'month_num']).drop('month_num', axis=1)

    return combined


def save_historical_data(historical_data, historical_file_path):
    """Save all historical data to Excel file"""
    try:
        with pd.ExcelWriter(historical_file_path, engine='openpyxl') as writer:
            for sheet_name, df in historical_data.items():
                if not df.empty:
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
        logging.info(f"✅ Historical data saved to {historical_file_path}")
        return True
    except Exception as e:
        logging.error(f"❌ Error saving historical data: {e}")
        return False


# ======================================================
# MAIN PIPELINE
# ======================================================
def main():
    # 1. Download using SFTP
    date_folder = download_from_sftp(ftp_config, SUBSCRIBERS_RAW_DIR, timeout=FTP_TIMEOUT_SECONDS)
    if not date_folder:
        logging.error("❌ Could not create/access date folder. Exiting.")
        return

    # 2. Extract ZIPs into date/unzipped/
    extract_zips(date_folder)

    # 3. Load CSVs from date/unzipped
    unzipped_folder = os.path.join(date_folder, "unzipped")
    if not os.path.exists(unzipped_folder):
        logging.error(f"⚠️ No unzipped folder found at {unzipped_folder}. Exiting.")
        return

    dataframes = load_all_csvs(unzipped_folder)
    if not dataframes:
        logging.error("❌ No CSV files found in unzipped folder. Exiting.")
        return
    logging.info(f"✅ Loaded {len(dataframes)} dataset(s) from {unzipped_folder}")

    # 4. Process KPIs
    peak_cs = process_cs(find_cs(dataframes))
    peak_iu, peak_s1 = process_ps_roaming(find_ps_roaming(dataframes))
    peak_2g, peak_3g = process_msc(find_msc(dataframes))
    peak_gb, peak_iu_users, peak_4g = process_ps_users(find_ps_users(dataframes))

    # 5. Build final_df
    if peak_cs.empty and peak_gb.empty and peak_iu_users.empty and peak_2g.empty and peak_3g.empty and peak_4g.empty and peak_iu.empty and peak_s1.empty:
        logging.error("❌ No KPI data could be processed. Exiting.")
        return

    if not peak_cs.empty:
        final_df = prep(peak_cs, "Number of Registered Subscribers(entries)")
        final_df = final_df.rename(columns={
            "Number of Registered Subscribers(entries)":
                "Number of Registered Subscribers (Almadar in Libyana Metwork)"
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
            "Gb mode maximum attached users(number)":
                "Maximum number of attached subscribers(GSM In SGSN)"
        })

    if not peak_iu_users.empty:
        final_df = final_df.merge(
            prep(peak_iu_users, "Iu mode maximum attached users(number)"),
            on=["year", "Week"], how="outer"
        ).rename(columns={
            "Iu mode maximum attached users(number)":
                "Maximum number of attached subscribers(UMTS in SGSN )"
        })

    if not peak_2g.empty:
        final_df = final_df.merge(
            prep(peak_2g, "Number of 2G Subscribers in VLR(entries)"),
            on=["year", "Week"], how="outer"
        ).rename(columns={
            "Number of 2G Subscribers in VLR(entries)":
                "Number of subscribers in VLR (Connected to BSC)"
        })

    if not peak_3g.empty:
        final_df = final_df.merge(
            prep(peak_3g, "Number of 3G Subscribers in VLR(entries)"),
            on=["year", "Week"], how="outer"
        ).rename(columns={
            "Number of 3G Subscribers in VLR(entries)":
                "Number of subscribers in VLR (Connected to RNC)"
        })

    if not peak_4g.empty:
        final_df = final_df.merge(
            prep(peak_4g, "Maximum attached users(number)"),
            on=["year", "Week"], how="outer"
        ).rename(columns={
            "Maximum attached users(number)":
                "Max Number of EPS Attach subscribers in MME"
        })

    if not peak_iu.empty and not peak_s1.empty:
        ps_iu_tmp = prep(peak_iu, "Iu mode attached Max user number per PLMN(number)")
        ps_s1_tmp = prep(peak_s1, "S1 Mode Maximum Attached Users per PLMN(number)")
        ps_merge = ps_iu_tmp.merge(ps_s1_tmp, on=["year", "Week"], how="outer")
        ps_merge["Number of Registered Subscribers (Almadar in Libyana PS Network) for(3G,4G)"] = (
                "3G=" + ps_merge["Iu mode attached Max user number per PLMN(number)"].astype(str)
                + ",4G=" + ps_merge["S1 Mode Maximum Attached Users per PLMN(number)"].astype(str)
        )
        ps_merge = ps_merge[
            ["year", "Week", "Number of Registered Subscribers (Almadar in Libyana PS Network) for(3G,4G)"]]
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
            final_df[
                col] = 0 if col != "Number of Registered Subscribers (Almadar in Libyana PS Network) for(3G,4G)" else ""

    final_df = final_df[expected_cols]
    final_df = final_df.sort_values(["year", "Week"])

    # 6. Process interference (2G, 3G, 4G)
    # Save to Interference_Output directory
    ensure_dir(INTERFERENCE_OUTPUT_DIR)

    # 7. Save historical data
    historical_data = load_historical_data(SUBSCRIBERS_HISTORY_FILE) or {}

    new_sheets = {'Subscribers_KPIs': final_df.copy()}
    interference_dfs = []

    # 2G interference
    interference_csv_path_2g = find_local_interference_csv(date_folder)
    if interference_csv_path_2g:
        logging.info(f"📂 Found 2G interference CSV: {interference_csv_path_2g}")
        df_int_2g = load_interference_csv(interference_csv_path_2g)
        result_2g = process_interference(df_int_2g)
        interference_dfs.append(result_2g)

    # 3G interference
    interference_csv_path_3g = find_3g_interference_csv(date_folder)
    if interference_csv_path_3g:
        logging.info(f"📂 Found 3G interference CSV: {interference_csv_path_3g}")
        df_int_3g = load_3g_interference_csv(interference_csv_path_3g)
        result_3g = process_3g_interference(df_int_3g)
        interference_dfs.append(result_3g)

    # 4G interference
    interference_csv_path_4g = find_4g_interference_csv(date_folder)
    if interference_csv_path_4g:
        logging.info(f"📂 Found 4G interference CSV: {interference_csv_path_4g}")
        df_int_4g = load_4g_interference_csv(interference_csv_path_4g)
        result_4g = process_4g_interference(df_int_4g)
        interference_dfs.append(result_4g)

    if interference_dfs:
        new_sheets['Interference_Summary'] = pd.concat(interference_dfs, ignore_index=True)

    # Merge and export
    final_export_sheets = {}

    # Merge KPIs
    kpi_keys = ["year", "Week", "Branch"]
    final_export_sheets['Subscribers_KPIs'] = merge_historical_data(
        new_sheets['Subscribers_KPIs'],
        historical_data.get('Subscribers_KPIs'),
        kpi_keys
    )

    # Merge Interference
    if 'Interference_Summary' in new_sheets:
        int_keys = ["year", "month", "Tech Type", "Branch", "Band"]
        final_export_sheets['Interference_Summary'] = merge_historical_data(
            new_sheets['Interference_Summary'],
            historical_data.get('Interference_Summary'),
            int_keys
        )

    save_historical_data(final_export_sheets, SUBSCRIBERS_HISTORY_FILE)
    logging.info("🚀 Automation pipeline completed successfully.")


if __name__ == "__main__":
    main()
