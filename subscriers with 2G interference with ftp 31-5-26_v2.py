import os
import zipfile
import pandas as pd
from io import StringIO
from ftplib import FTP_TLS, error_temp, error_reply
from datetime import datetime
import socket
from project_config import env_int, env_path_str, env_str

# ======================================================
# CONFIG
# ======================================================
# Use relative path from script location
script_dir = os.path.dirname(os.path.abspath(__file__))
base_folder = env_path_str("SUBSCRIBERS_RAW_DIR", os.path.join(script_dir, "Subscribers", "Raw Data"))


ftp_config = {
    "host": env_str("FTP_HOST"),
    "port": env_int("FTP_PORT", 21),
    "username": env_str("FTP_USERNAME"),
    "password": env_str("FTP_PASSWORD"),
    "remote_path": env_str("FTP_REMOTE_PATH", "/ftproot/New"),
    "file_pattern": env_str("FTP_FILE_PATTERN", "*{yyyymmdd}*.zip")
}

FTP_TIMEOUT_SECONDS = env_int("FTP_TIMEOUT_SECONDS", 30)

if not ftp_config["host"] or not ftp_config["username"] or not ftp_config["password"]:
    raise RuntimeError("FTP_HOST, FTP_USERNAME, and FTP_PASSWORD must be configured in .env or environment variables.")


# ======================================================
# 0. FTP DOWNLOAD (saves into date/zipped/)
# ======================================================
def download_from_ftp(config, base_local_folder, timeout=30):
    """Download zip files into base_local_folder/YYYYMMDD/zipped/"""
    today_str = datetime.now().strftime("%Y%m%d")
    date_folder = os.path.join(base_local_folder, today_str)
    zipped_folder = os.path.join(date_folder, "zipped")
    os.makedirs(zipped_folder, exist_ok=True)

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
        for file in files:
            if file.endswith(".zip") and today_str in file:
                local_path = os.path.join(zipped_folder, file)
                if os.path.exists(local_path):
                    print(f"⏭ Skipping (already exists): {file}")
                    continue
                print(f"⬇ Downloading: {file}")
                with open(local_path, "wb") as f:
                    ftps.retrbinary(f"RETR {file}", f.write)
                downloaded += 1
        ftps.quit()
        print(f"✅ FTP done. Downloaded {downloaded} file(s) to {zipped_folder}")
        return date_folder

    except socket.timeout:
        print(f"❌ FTP timeout after {timeout}s – server not reachable.")
        print(f"   Will use existing files in {date_folder} if any.")
    except (ConnectionError, TimeoutError, error_temp, error_reply) as e:
        print(f"❌ FTP error: {type(e).__name__}: {e}")
        print(f"   Will use existing files in {date_folder} if any.")
    except Exception as e:
        print(f"❌ Unexpected FTP error: {e}")

    return date_folder if os.path.exists(date_folder) else None


# ======================================================
# 1. Extract ZIPs into date/unzipped/
# ======================================================
def extract_zips(date_folder):
    """Extract all ZIPs from date_folder/zipped/ into date_folder/unzipped/"""
    if not date_folder or not os.path.exists(date_folder):
        print(f"⚠️ Date folder does not exist: {date_folder}")
        return

    zipped_folder = os.path.join(date_folder, "zipped")
    unzipped_root = os.path.join(date_folder, "unzipped")

    if not os.path.exists(zipped_folder):
        print(f"⚠️ No 'zipped' folder found in {date_folder}")
        return

    os.makedirs(unzipped_root, exist_ok=True)

    for file_name in os.listdir(zipped_folder):
        if not file_name.lower().endswith(".zip"):
            continue
        zip_path = os.path.join(zipped_folder, file_name)
        if not zipfile.is_zipfile(zip_path):
            print(f"❌ Not a valid ZIP file: {file_name}")
            continue

        extract_folder_name = os.path.splitext(file_name)[0]
        extract_path = os.path.join(unzipped_root, extract_folder_name)

        if os.path.exists(extract_path) and os.listdir(extract_path):
            print(f"⏭ Already extracted: {file_name}")
            continue

        try:
            print(f"📦 Extracting: {file_name} → {extract_path}")
            os.makedirs(extract_path, exist_ok=True)
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_path)
            print(f"✅ Done: {file_name}")
        except zipfile.BadZipFile:
            print(f"❌ Corrupted ZIP skipped: {file_name}")
        except PermissionError:
            print(f"🔒 Permission denied: {file_name}")
        except Exception as e:
            print(f"⚠️ Unexpected error with {file_name}: {e}")


# ======================================================
# 2. Load & Clean a single CSV (original logic)
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
def load_all_csvs(unzipped_folder):
    """Load CSVs from all subfolders of unzipped_folder"""
    dataframes = {}
    if not os.path.exists(unzipped_folder):
        return dataframes
    for root, dirs, files in os.walk(unzipped_folder):
        for file in files:
            if file.endswith(".csv") and "Peak" not in file:
                file_path = os.path.join(root, file)
                df = load_clean_csv(file_path)
                if df is not None:
                    key_name = os.path.basename(root)
                    dataframes[key_name] = df
    return dataframes

# ======================================================
# 4. Find specific datasets by name (with debugging)
# ======================================================
def find_cs(dataframes):
    candidates = [name for name in dataframes.keys()
                  if name.lower().startswith('cs roaming')]
    if candidates:
        return dataframes[candidates[0]]
    print("❌ CS Roaming dataset not found. Available keys:", list(dataframes.keys()))
    return None

def find_ps_roaming(dataframes):
    candidates = [name for name in dataframes.keys()
                  if name.lower().startswith('ps roaming users')]
    if candidates:
        return dataframes[candidates[0]]
    print("❌ PS Roaming dataset not found. Available keys:", list(dataframes.keys()))
    return None

def find_msc(dataframes):
    candidates = [name for name in dataframes.keys()
                  if "MSC Server KPI" in name]
    if candidates:
        return dataframes[candidates[0]]
    print("❌ MSC dataset not found. Available keys:", list(dataframes.keys()))
    return None

def find_ps_users(dataframes):
    candidates = [name for name in dataframes.keys()
                  if "PS users" in name or "2G_3G_4G" in name]
    if candidates:
        return dataframes[candidates[0]]
    print("❌ PS Users dataset not found. Available keys:", list(dataframes.keys()))
    return None

# ======================================================
# 5. Processing functions (with None guards)
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
    """Search for 2G interference CSV inside date_folder/unzipped/"""
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

    # Map 2G band names to frequency numbers
    band_mapping = {
        'DCS1800': 1800,
        'GSM900': 900,
        # Add more if needed
    }
    df['Band'] = df['Band'].replace(band_mapping)

    total_cells_per_band = df.groupby('Band')['Cell Name'].nunique().reset_index()
    total_cells_per_band.columns = ['Band', 'Total count of cells']

    df_filtered = df[~df[interference_col].astype(str).str.contains('NIL', na=False)]
    df_filtered[interference_col] = pd.to_numeric(df_filtered[interference_col], errors='coerce')

    interfered_df = df_filtered[df_filtered[interference_col] > 5]
    interfered_per_band = interfered_df.groupby('Band')['Cell Name'].nunique().reset_index()
    interfered_per_band.columns = ['Band', 'Count of Cells with External interference']

    result = pd.merge(total_cells_per_band, interfered_per_band, on='Band', how='left')
    result['Count of Cells with External interference'] = result['Count of Cells with External interference'].fillna(0).astype(int)

    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    first_date = df['Date'].min()
    result['year'] = first_date.year
    result['month'] = first_date.strftime('%b')
    result['Tech Type'] = '2G'
    result['Branch'] = 'East'

    return result[['year', 'month', 'Tech Type', 'Branch', 'Band',
                   'Count of Cells with External interference', 'Total count of cells']]
# ======================================================
# Interference processing (3G)
# ======================================================
def find_3g_interference_csv(date_folder):
    """Search for 3G interference CSV inside date_folder/unzipped/"""
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
    """Load and clean 3G interference CSV:
       - Skip rows until header starting with 'Time'
       - Remove last row (footer)
       - Drop rows where VS.MeanRTWP contains '/0'
    """
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

    interfered_cells_with_band = df[df['Cell Name'].isin(interfered_cells)][['Cell Name', 'Band']].drop_duplicates('Cell Name')
    interfered_per_band = interfered_cells_with_band.groupby('Band').size().reset_index(name='Count of Cells with External interference')

    result = pd.merge(total_cells, interfered_per_band, on='Band', how='left')
    result['Count of Cells with External interference'] = result['Count of Cells with External interference'].fillna(0).astype(int)

    first_date = df['Time'].min()
    result['year'] = first_date.year
    result['month'] = first_date.strftime('%b')
    result['Tech Type'] = '3G'
    result['Branch'] = 'East'

    return result[['year', 'month', 'Tech Type', 'Branch', 'Band',
                   'Count of Cells with External interference', 'Total count of cells']]

# ======================================================
# Interference processing (4G) - CORRECTED
# ======================================================
def find_4g_interference_csv(date_folder):
    """Search for 4G interference CSV inside date_folder/unzipped/"""
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
    """Load and clean 4G interference CSV with CORRECT EARFCN mapping."""
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
        if earfcn==1 :
            return 2100   # Band 1
        elif earfcn ==3:
            return 1800   # Band 3
        elif earfcn==8:
            return 900    # Band 8
        elif earfcn==28:
            return 700    # Band 28
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
    """
    Compute 4G interference summary per band:
      - Total distinct cells per band
      - For each cell, for each day, count hours with interference > -100 dBm.
        If any day has >=6 such hours, cell is counted as interfered.
    """
    if df.empty:
        return pd.DataFrame()

    total_cells = df.groupby('Band')['Cell Name'].nunique().reset_index()
    total_cells.columns = ['Band', 'Total count of cells']

    df['is_interfered_hour'] = df['L.UL.Interference.Avg(dBm)'] > -100

    daily_cell_summary = df.groupby(['Cell Name', 'Date'])['is_interfered_hour'].sum().reset_index()
    daily_cell_summary.rename(columns={'is_interfered_hour': 'interfered_hours_per_day'}, inplace=True)

    interfered_cells = daily_cell_summary[daily_cell_summary['interfered_hours_per_day'] >= 6]['Cell Name'].unique()

    interfered_cells_with_band = df[df['Cell Name'].isin(interfered_cells)][['Cell Name', 'Band']].drop_duplicates('Cell Name')
    interfered_per_band = interfered_cells_with_band.groupby('Band').size().reset_index(name='Count of Cells with External interference')

    result = pd.merge(total_cells, interfered_per_band, on='Band', how='left')
    result['Count of Cells with External interference'] = result['Count of Cells with External interference'].fillna(0).astype(int)

    first_date = df['Time'].min()
    result['year'] = first_date.year
    result['month'] = first_date.strftime('%b')
    result['Tech Type'] = '4G'
    result['Branch'] = 'East'

    return result[['year', 'month', 'Tech Type', 'Branch', 'Band',
                   'Count of Cells with External interference', 'Total count of cells']]

# ======================================================
# MAIN PIPELINE (COMPLETE)
# ======================================================
def main():
    # 1. Download to today's date/zipped folder
    date_folder = download_from_ftp(ftp_config, base_folder)
    if not date_folder:
        print("❌ Could not create/access date folder. Exiting.")
        return

    # 2. Extract ZIPs into date/unzipped/
    extract_zips(date_folder)

    # 3. Load CSVs from date/unzipped
    unzipped_folder = os.path.join(date_folder, "unzipped")
    if not os.path.exists(unzipped_folder):
        print(f"⚠️ No unzipped folder found at {unzipped_folder}. Exiting.")
        return

    dataframes = load_all_csvs(unzipped_folder)
    if not dataframes:
        print("❌ No CSV files found in unzipped folder. Exiting.")
        return

    # 4. Process KPIs
    peak_cs = process_cs(find_cs(dataframes))
    peak_iu, peak_s1 = process_ps_roaming(find_ps_roaming(dataframes))
    peak_2g, peak_3g = process_msc(find_msc(dataframes))
    peak_gb, peak_iu_users, peak_4g = process_ps_users(find_ps_users(dataframes))

    # 5. Build final_df
    if peak_cs.empty and peak_gb.empty and peak_iu_users.empty and peak_2g.empty and peak_3g.empty and peak_4g.empty and peak_iu.empty and peak_s1.empty:
        print("❌ No KPI data could be processed. Exiting.")
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

    # 6. Process interference (2G, 3G, 4G) and combine into one sheet
    output_folder = os.path.join(date_folder, "output")
    os.makedirs(output_folder, exist_ok=True)

    today_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"Final_Output_{today_str}.xlsx"
    output_path = os.path.join(output_folder, filename)

    sheets = {'Subscribers_KPIs': final_df}
    interference_dfs = []

    # 2G interference
    interference_csv_path_2g = find_local_interference_csv(date_folder)
    if interference_csv_path_2g:
        print(f"📂 Found 2G interference CSV: {interference_csv_path_2g}")
        df_int_2g = load_interference_csv(interference_csv_path_2g)
        result_2g = process_interference(df_int_2g)
        interference_dfs.append(result_2g)
    else:
        print("ℹ️ No 2G interference CSV found.")

    # 3G interference
    interference_csv_path_3g = find_3g_interference_csv(date_folder)
    if interference_csv_path_3g:
        print(f"📂 Found 3G interference CSV: {interference_csv_path_3g}")
        df_int_3g = load_3g_interference_csv(interference_csv_path_3g)
        result_3g = process_3g_interference(df_int_3g)
        interference_dfs.append(result_3g)
    else:
        print("ℹ️ No 3G interference CSV found.")

    # 4G interference
    interference_csv_path_4g = find_4g_interference_csv(date_folder)
    if interference_csv_path_4g:
        print(f"📂 Found 4G interference CSV: {interference_csv_path_4g}")
        df_int_4g = load_4g_interference_csv(interference_csv_path_4g)
        result_4g = process_4g_interference(df_int_4g)
        interference_dfs.append(result_4g)
    else:
        print("ℹ️ No 4G interference CSV found.")

    # Combine all interference data into one sheet
    if interference_dfs:
        combined_interference = pd.concat(interference_dfs, ignore_index=True)
        sheets['Interference_Summary'] = combined_interference
    else:
        print("ℹ️ No interference data to combine.")

    # Write Excel
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        for sheet_name, df_sheet in sheets.items():
            df_sheet.to_excel(writer, sheet_name=sheet_name, index=False)

    print(f"✅ DONE: Saved {len(sheets)} sheet(s) to {output_path}")

if __name__ == "__main__":
    main()
