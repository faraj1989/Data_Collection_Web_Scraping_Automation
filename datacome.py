import os
import re
import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import logging
from collections import defaultdict

# ------------------------- CONFIGURATION -------------------------
WATCH_FOLDER = r"c:\datacome"  # Folder to monitor for new CSV files
PROCESSED_LOG = r"c:\datacome\processed_files.txt"  # Keep track of processed files
INTERVAL_SECONDS = 300  # 5 minutes between checks
LOG_FILE = r"c:\datacome\analysis.log"

# Capacity thresholds (in bits per second) – adjust per resource or use a default
# You can also auto‑detect from the resource name if needed
DEFAULT_CAPACITY = 10e9  # 10 Gbps default, change as required
CAPACITY_MAP = {
    # Example: 'Eth-Trunk5': 20e9, 'Eth-Trunk2': 20e9
    # Leave empty to use DEFAULT_CAPACITY
}

# Alert thresholds (percentage of capacity)
WARNING_THRESHOLD_PCT = 70
CRITICAL_THRESHOLD_PCT = 85

# ------------------------- LOGGING SETUP -------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ------------------------- HELPER FUNCTIONS -------------------------
def parse_rate(rate_str):
    """Convert strings like '1.397G', '948.518M', '0.000' to bits per second (float)."""
    if pd.isna(rate_str) or rate_str == '' or rate_str == '0.000':
        return 0.0
    rate_str = str(rate_str).strip().upper()
    match = re.match(r'([\d\.]+)\s*([KMG]?)', rate_str)
    if not match:
        return 0.0
    value, unit = match.groups()
    value = float(value)
    multiplier = {'K': 1e3, 'M': 1e6, 'G': 1e9, '': 1}
    return value * multiplier.get(unit, 1)


def get_capacity_for_resource(resource_name):
    """Return link capacity in bps for a given resource name."""
    # Example: extract trunk type from name and map
    for key, cap in CAPACITY_MAP.items():
        if key in resource_name:
            return cap
    return DEFAULT_CAPACITY


def load_and_clean_csv(filepath):
    """
    Load the CSV file that may have header lines before the actual column names.
    Returns a pandas DataFrame with clean columns and numeric rates.
    """
    # Find the line where the actual header starts (row containing "Resource Name","Collection Time"...)
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    header_idx = None
    for i, line in enumerate(lines):
        if 'Resource Name' in line and 'Collection Time' in line:
            header_idx = i
            break
    if header_idx is None:
        raise ValueError("Could not find header row in CSV")

    # Read the CSV from that line onward
    df = pd.read_csv(filepath, skiprows=header_idx, encoding='utf-8')
    # Remove any trailing rows that are empty or contain only commas
    df = df.dropna(how='all')
    # Convert rate columns to numeric bits per second
    df['Outbound Rate(bit/s)_num'] = df['Outbound Rate(bit/s)'].apply(parse_rate)
    df['Inbound Rate(bit/s)_num'] = df['Inbound Rate(bit/s)'].apply(parse_rate)
    # Convert Collection Time to datetime
    df['Collection Time'] = pd.to_datetime(df['Collection Time'], errors='coerce')
    df = df.dropna(subset=['Collection Time'])
    return df


def compute_kpis(df):
    """
    Given a dataframe for a single file, compute overall and per-resource KPIs.
    Returns dict with summaries.
    """
    if df.empty:
        return {}
    # Overall stats
    overall_out_avg = df['Outbound Rate(bit/s)_num'].mean()
    overall_in_avg = df['Inbound Rate(bit/s)_num'].mean()
    overall_out_max = df['Outbound Rate(bit/s)_num'].max()
    overall_in_max = df['Inbound Rate(bit/s)_num'].max()

    # Per-resource stats
    resource_stats = []
    for name, group in df.groupby('Resource Name'):
        capacity = get_capacity_for_resource(name)
        out_avg = group['Outbound Rate(bit/s)_num'].mean()
        in_avg = group['Inbound Rate(bit/s)_num'].mean()
        out_max = group['Outbound Rate(bit/s)_num'].max()
        in_max = group['Inbound Rate(bit/s)_num'].max()
        out_util_pct = (out_avg / capacity) * 100 if capacity else 0
        in_util_pct = (in_avg / capacity) * 100 if capacity else 0
        resource_stats.append({
            'Resource': name,
            'Capacity (bps)': capacity,
            'Outbound Avg (bps)': out_avg,
            'Inbound Avg (bps)': in_avg,
            'Outbound Max (bps)': out_max,
            'Inbound Max (bps)': in_max,
            'Outbound Util %': out_util_pct,
            'Inbound Util %': in_util_pct,
            'Sample Count': len(group)
        })
    return {
        'file_time': df['Collection Time'].min(),  # approximate time of data
        'overall_out_avg': overall_out_avg,
        'overall_in_avg': overall_in_avg,
        'overall_out_max': overall_out_max,
        'overall_in_max': overall_in_max,
        'resource_stats': pd.DataFrame(resource_stats),
        'raw_data': df
    }


def detect_anomalies(kpis_df):
    """
    Simple anomaly detection: identify resources with utilisation above thresholds
    or with zero traffic (possible outage).
    """
    if kpis_df.empty:
        return []
    alerts = []
    for _, row in kpis_df.iterrows():
        out_util = row['Outbound Util %']
        in_util = row['Inbound Util %']
        if out_util >= CRITICAL_THRESHOLD_PCT or in_util >= CRITICAL_THRESHOLD_PCT:
            alerts.append(
                f"CRITICAL: {row['Resource']} utilisation {max(out_util, in_util):.1f}% > {CRITICAL_THRESHOLD_PCT}%")
        elif out_util >= WARNING_THRESHOLD_PCT or in_util >= WARNING_THRESHOLD_PCT:
            alerts.append(
                f"WARNING: {row['Resource']} utilisation {max(out_util, in_util):.1f}% > {WARNING_THRESHOLD_PCT}%")
        # Zero traffic detection (both directions zero for many samples)
        if row['Outbound Max (bps)'] == 0 and row['Inbound Max (bps)'] == 0:
            alerts.append(f"INFO: {row['Resource']} has zero traffic (possible down/link down)")
    return alerts


def generate_report(kpis_dict, output_filepath=None):
    """Create an Excel report with sheets for summary, resource stats, and alerts."""
    if not kpis_dict:
        logger.warning("No data to report")
        return
    timestamp = kpis_dict['file_time'].strftime('%Y%m%d_%H%M%S')
    if output_filepath is None:
        output_filepath = os.path.join(WATCH_FOLDER, f"analysis_report_{timestamp}.xlsx")

    with pd.ExcelWriter(output_filepath, engine='openpyxl') as writer:
        # Summary sheet
        summary_data = {
            'Metric': ['Overall Average Outbound (bps)', 'Overall Average Inbound (bps)',
                       'Overall Max Outbound (bps)', 'Overall Max Inbound (bps)',
                       'Number of Resources', 'Data Time Window'],
            'Value': [f"{kpis_dict['overall_out_avg']:.2e}", f"{kpis_dict['overall_in_avg']:.2e}",
                      f"{kpis_dict['overall_out_max']:.2e}", f"{kpis_dict['overall_in_max']:.2e}",
                      len(kpis_dict['resource_stats']), kpis_dict['file_time']]
        }
        pd.DataFrame(summary_data).to_excel(writer, sheet_name='Summary', index=False)

        # Resource stats sheet
        kpis_dict['resource_stats'].to_excel(writer, sheet_name='Resource KPIs', index=False)

        # Alerts sheet
        alerts = detect_anomalies(kpis_dict['resource_stats'])
        if alerts:
            pd.DataFrame({'Alert': alerts}).to_excel(writer, sheet_name='Alerts', index=False)
        else:
            pd.DataFrame({'Status': ['No anomalies detected']}).to_excel(writer, sheet_name='Alerts', index=False)

    logger.info(f"Report saved: {output_filepath}")
    return output_filepath


def get_already_processed():
    """Return set of filenames that have been processed."""
    if os.path.exists(PROCESSED_LOG):
        with open(PROCESSED_LOG, 'r') as f:
            return set(line.strip() for line in f)
    return set()


def mark_processed(filename):
    """Add filename to processed log."""
    with open(PROCESSED_LOG, 'a') as f:
        f.write(filename + '\n')


def process_new_files():
    """Scan WATCH_FOLDER for new CSV files, process them, and generate reports."""
    processed = get_already_processed()
    csv_files = [f for f in os.listdir(WATCH_FOLDER) if f.endswith('.csv') and f not in processed]
    if not csv_files:
        logger.info("No new CSV files found.")
        return

    for csv_file in csv_files:
        filepath = os.path.join(WATCH_FOLDER, csv_file)
        try:
            logger.info(f"Processing {csv_file}...")
            df = load_and_clean_csv(filepath)
            if df.empty:
                logger.warning(f"No valid data in {csv_file}")
                mark_processed(csv_file)
                continue
            kpis = compute_kpis(df)
            report_path = generate_report(kpis)
            # Optionally, send email or push to dashboard here
            mark_processed(csv_file)
            logger.info(f"Successfully processed {csv_file}")
        except Exception as e:
            logger.error(f"Error processing {csv_file}: {e}", exc_info=True)


def main_loop():
    """Main loop: check every INTERVAL_SECONDS."""
    logger.info(f"Starting Datacome CSV analyzer. Watching {WATCH_FOLDER}")
    while True:
        process_new_files()
        logger.info(f"Sleeping for {INTERVAL_SECONDS // 60} minutes...")
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main_loop()