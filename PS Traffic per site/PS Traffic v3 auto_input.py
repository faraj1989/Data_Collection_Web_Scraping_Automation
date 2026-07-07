import argparse
import pandas as pd
import re
import os
import shutil
from io import StringIO
from datetime import datetime

from project_config import env_path_str

# Base folder for downloaded raw files, matching the FTP downloader logic.
script_dir = os.path.dirname(os.path.abspath(__file__))
base_raw_data_folder = env_path_str(
    "SUBSCRIBERS_RAW_DIR",
    os.path.normpath(os.path.join(script_dir, "..", "Subscribers", "Raw Data"))
)


def resolve_date_folder(date_input=None):
    """Resolve the raw data date folder from a date or a direct path."""
    if not date_input:
        today_str = datetime.now().strftime("%Y%m%d")
        return os.path.join(base_raw_data_folder, today_str)

    date_input = str(date_input).strip()
    if os.path.exists(date_input) and os.path.isdir(date_input):
        return os.path.abspath(date_input)

    if re.fullmatch(r"\d{8}", date_input):
        return os.path.join(base_raw_data_folder, date_input)

    return os.path.join(base_raw_data_folder, date_input)


def clean_csv_content(file_content):
    """
    Clean CSV content by removing metadata headers and footer.
    Headers are removed by finding the line starting with 'Date,'
    Footer is removed by taking all but the last line.
    """
    lines = file_content.strip().split('\n')

    # Find the line where actual data starts (line containing 'Date,')
    start_idx = 0
    for i, line in enumerate(lines):
        if line.startswith('Date,'):
            start_idx = i
            break

    # Extract data rows (remove footer by taking all but last line)
    data_lines = lines[start_idx:-1]

    # Remove any empty lines
    data_lines = [line for line in data_lines if line.strip()]

    return '\n'.join(data_lines)


def find_ps_traffic_files(unzipped_folder):
    """
    Find the PS Daily Traffic 2G, 3G, and 4G CSV files in the unzipped folder.
    """
    if not os.path.exists(unzipped_folder):
        print(f"⚠️ Unzipped folder does not exist: {unzipped_folder}")
        return None, None, None

    print(f"🔍 Searching for PS Traffic files in: {unzipped_folder}")

    ps_traffic_folder = None
    for root, dirs, files in os.walk(unzipped_folder):
        for dir_name in dirs:
            if dir_name.startswith('PS Daily Traffic_2G_3G_4G'):
                ps_traffic_folder = os.path.join(root, dir_name)
                break
        if ps_traffic_folder:
            break

    if not ps_traffic_folder:
        for root, dirs, files in os.walk(unzipped_folder):
            for dir_name in dirs:
                if 'PS Daily Traffic' in dir_name:
                    ps_traffic_folder = os.path.join(root, dir_name)
                    break
            if ps_traffic_folder:
                break

    if not ps_traffic_folder:
        print("❌ PS Daily Traffic folder not found in unzipped directory")
        print("\n📂 Available folders in unzipped:")
        if os.path.exists(unzipped_folder):
            for item in os.listdir(unzipped_folder):
                item_path = os.path.join(unzipped_folder, item)
                if os.path.isdir(item_path):
                    print(f"  - {item}")
                elif os.path.isfile(item_path) and item.endswith('.csv'):
                    print(f"  - {item} (file)")
        return None, None, None

    print(f"📂 PS Traffic folder: {ps_traffic_folder}")

    file_2g = None
    file_3g = None
    file_4g = None
    all_files = [f for f in os.listdir(ps_traffic_folder) if f.endswith('.csv')]

    for file in all_files:
        if '(PS Traffic 2G)' in file or '(PS Traffic 2G).csv' in file:
            file_2g = os.path.join(ps_traffic_folder, file)
        elif '(PS Traffic 3G)' in file or '(PS Traffic 3G).csv' in file:
            file_3g = os.path.join(ps_traffic_folder, file)
        elif '(PS Traffic 4G)' in file or '(PS Traffic 4G).csv' in file:
            file_4g = os.path.join(ps_traffic_folder, file)

    if not file_2g or not file_3g or not file_4g:
        for file in all_files:
            if '2G' in file and 'Traffic' in file and not file_2g:
                file_2g = os.path.join(ps_traffic_folder, file)
            elif '3G' in file and 'Traffic' in file and not file_3g:
                file_3g = os.path.join(ps_traffic_folder, file)
            elif '4G' in file and 'Traffic' in file and not file_4g:
                file_4g = os.path.join(ps_traffic_folder, file)

    if (not file_2g or not file_3g or not file_4g) and all_files:
        for file in all_files:
            file_path = os.path.join(ps_traffic_folder, file)
            if file_path in [file_2g, file_3g, file_4g]:
                continue
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    lines = content.split('\n')
                    header_line = None
                    for line in lines:
                        if line.startswith('Date,'):
                            header_line = line
                            break
                    if header_line:
                        if 'eGBTS' in header_line and 'PS Traffic(GB)' in header_line:
                            file_2g = file_path
                        elif 'NodeB' in header_line and 'PS traffic (GB)' in header_line:
                            file_3g = file_path
                        elif 'eNodeB Name' in header_line and 'Downlink Traffic Volume(GB)' in header_line:
                            file_4g = file_path
            except Exception as e:
                print(f"    ⚠️ Could not read {file}: {e}")

    print(f"\n📄 Final file list:")
    print(f"  2G: {os.path.basename(file_2g) if file_2g else '❌ NOT FOUND'}")
    print(f"  3G: {os.path.basename(file_3g) if file_3g else '❌ NOT FOUND'}")
    print(f"  4G: {os.path.basename(file_4g) if file_4g else '❌ NOT FOUND'}")

    return file_2g, file_3g, file_4g


def load_traffic_file(file_path, file_type):
    if not file_path or not os.path.exists(file_path):
        print(f"⚠️ {file_type} file not found: {file_path}")
        return None

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        clean_content = clean_csv_content(content)
        df = pd.read_csv(StringIO(clean_content))
        df = df[:-1] if len(df) > 0 else df
        print(f"  - Loaded {len(df)} records")
        print(f"  - Columns: {list(df.columns)}")
        return df
    except Exception as e:
        print(f"  ❌ Error loading {file_type} file: {e}")
        return None


def process_2g_data(df):
    if df is None or df.empty:
        return pd.DataFrame()
    try:
        df_2g = df[['Date', 'eGBTS', 'PS Traffic(GB)']].copy()
        df_2g.columns = ['Date', 'Site_Name', 'Traffic_GB']
        df_2g['Technology'] = '2G'
        return df_2g
    except KeyError as e:
        print(f"  ❌ Error processing 2G data: {e}")
        print(f"  Available columns: {list(df.columns)}")
        return pd.DataFrame()


def process_3g_data(df):
    if df is None or df.empty:
        return pd.DataFrame()
    try:
        df_3g = df[['Date', 'NodeB', 'PS traffic (GB)']].copy()
        df_3g.columns = ['Date', 'Site_Name', 'Traffic_GB']
        df_3g['Technology'] = '3G'
        return df_3g
    except KeyError as e:
        print(f"  ❌ Error processing 3G data: {e}")
        print(f"  Available columns: {list(df.columns)}")
        return pd.DataFrame()


def process_4g_data(df):
    if df is None or df.empty:
        return pd.DataFrame()
    try:
        df_4g = df[['Date', 'eNodeB Name', 'Downlink Traffic Volume(GB)', 'UL Traffic  Volume(GB)']].copy()
        df_4g.columns = ['Date', 'Site_Name', 'DL_GB', 'UL_GB']
        df_4g['Traffic_GB'] = df_4g['DL_GB'] + df_4g['UL_GB']
        df_4g['Technology'] = '4G'
        return df_4g[['Date', 'Site_Name', 'Traffic_GB', 'Technology']]
    except KeyError as e:
        print(f"  ❌ Error processing 4G data: {e}")
        print(f"  Available columns: {list(df.columns)}")
        return pd.DataFrame()


def extract_region(site_name):
    if pd.isna(site_name):
        return 'Unknown'
    site_str = str(site_name)
    site_str = re.sub(r'\([^)]*\)', '', site_str)
    match = re.match(r'^([A-Za-z]+)', site_str)
    return match.group(1) if match else 'Other'


def analyze_site_coverage(data_frames):
    print("\n" + "=" * 60)
    print("📊 SITE COVERAGE ANALYSIS")
    print("=" * 60)

    tech_sites = {}
    for tech, df in data_frames.items():
        if not df.empty:
            tech_sites[tech] = set(df['Site_Name'].unique())
            print(f"\n{tech} sites: {len(tech_sites[tech])}")

    if len(tech_sites) < 2:
        print("⚠️ Not enough technologies for coverage analysis")
        return None

    if len(tech_sites) >= 3 and all(tech in tech_sites for tech in ['2G', '3G', '4G']):
        all_three = tech_sites['2G'] & tech_sites['3G'] & tech_sites['4G']
        print(f"\n✅ Sites with ALL THREE technologies (2G+3G+4G): {len(all_three)}")
        if len(all_three) > 0 and len(all_three) <= 20:
            print(f"   {sorted(list(all_three))}")

    if '2G' in tech_sites and '3G' in tech_sites:
        two_three = tech_sites['2G'] & tech_sites['3G'] - tech_sites.get('4G', set())
        print(f"\n📱 Sites with 2G+3G (no 4G): {len(two_three)}")
        if len(two_three) > 0 and len(two_three) <= 20:
            print(f"   {sorted(list(two_three))}")

    if '2G' in tech_sites and '4G' in tech_sites:
        two_four = tech_sites['2G'] & tech_sites['4G'] - tech_sites.get('3G', set())
        print(f"\n📱 Sites with 2G+4G (no 3G): {len(two_four)}")
        if len(two_four) > 0 and len(two_four) <= 20:
            print(f"   {sorted(list(two_four))}")

    if '3G' in tech_sites and '4G' in tech_sites:
        three_four = tech_sites['3G'] & tech_sites['4G'] - tech_sites.get('2G', set())
        print(f"\n📱 Sites with 3G+4G (no 2G): {len(three_four)}")
        if len(three_four) > 0 and len(three_four) <= 20:
            print(f"   {sorted(list(three_four))}")

    if '2G' in tech_sites:
        only_2g = tech_sites['2G'] - tech_sites.get('3G', set()) - tech_sites.get('4G', set())
        print(f"\n📱 Sites with ONLY 2G: {len(only_2g)}")
        if len(only_2g) > 0 and len(only_2g) <= 20:
            print(f"   {sorted(list(only_2g))}")

    if '3G' in tech_sites:
        only_3g = tech_sites['3G'] - tech_sites.get('2G', set()) - tech_sites.get('4G', set())
        print(f"\n📱 Sites with ONLY 3G: {len(only_3g)}")
        if len(only_3g) > 0 and len(only_3g) <= 20:
            print(f"   {sorted(list(only_3g))}")

    if '4G' in tech_sites:
        only_4g = tech_sites['4G'] - tech_sites.get('2G', set()) - tech_sites.get('3G', set())
        print(f"\n📱 Sites with ONLY 4G: {len(only_4g)}")
        if len(only_4g) > 0 and len(only_4g) <= 20:
            print(f"   {sorted(list(only_4g))}")

    all_sites = set()
    for sites in tech_sites.values():
        all_sites.update(sites)
    print(f"\n📍 TOTAL UNIQUE SITES (all technologies): {len(all_sites)}")

    return tech_sites


def combine_traffic_data(data_frames):
    valid_frames = {tech: df for tech, df in data_frames.items() if not df.empty}
    if not valid_frames:
        print("❌ No valid data to combine")
        return pd.DataFrame()

    all_data = pd.concat(valid_frames.values(), ignore_index=True)
    print(f"\nTotal records before processing: {len(all_data)}")
    print(f"Records by technology:\n{all_data['Technology'].value_counts()}")

    all_data['Date'] = pd.to_datetime(all_data['Date'], errors='coerce')
    if all_data['Date'].isna().all():
        print("  - Trying alternative date format...")
        all_data['Date'] = pd.to_datetime(all_data['Date'], format='%d/%m/%Y', errors='coerce')

    valid_dates = all_data['Date'].notna().sum()
    print(f"Valid dates: {valid_dates} out of {len(all_data)}")
    invalid_dates = all_data['Date'].isna().sum()
    if invalid_dates > 0:
        print(f"  - Removing {invalid_dates} rows with invalid dates")
        all_data = all_data.dropna(subset=['Date'])

    if len(all_data) == 0:
        print("  - Warning: No valid dates found after parsing!")
        return pd.DataFrame()

    pivoted = all_data.pivot_table(
        index=['Date', 'Site_Name'],
        columns='Technology',
        values='Traffic_GB',
        aggfunc='sum',
        fill_value=0
    ).reset_index()

    for tech in ['2G', '3G', '4G']:
        if tech not in pivoted.columns:
            pivoted[tech] = 0

    pivoted.columns = ['Date', 'Site_Name', '2G_Traffic_GB', '3G_Traffic_GB', '4G_Traffic_GB']
    pivoted['Total_Traffic_GB'] = pivoted['2G_Traffic_GB'] + pivoted['3G_Traffic_GB'] + pivoted['4G_Traffic_GB']
    pivoted['Region'] = pivoted['Site_Name'].apply(extract_region)
    pivoted = pivoted.sort_values(['Date', 'Site_Name']).reset_index(drop=True)
    pivoted['Date_Formatted'] = pivoted['Date'].dt.strftime('%d-%m-%Y')

    return pivoted


def generate_summary_reports(combined_df):
    reports = {}
    if len(combined_df) == 0:
        print("  - Warning: No data to generate summary reports")
        return reports

    daily_summary = combined_df.groupby('Date').agg({
        '2G_Traffic_GB': 'sum',
        '3G_Traffic_GB': 'sum',
        '4G_Traffic_GB': 'sum',
        'Total_Traffic_GB': 'sum'
    }).reset_index()
    daily_summary['Date_Formatted'] = daily_summary['Date'].dt.strftime('%d-%m-%Y')
    daily_summary = daily_summary.sort_values('Date')
    reports['Daily_Summary'] = daily_summary

    regional_summary = combined_df.groupby('Region').agg({
        '2G_Traffic_GB': 'sum',
        '3G_Traffic_GB': 'sum',
        '4G_Traffic_GB': 'sum',
        'Total_Traffic_GB': 'sum'
    }).reset_index()
    regional_summary = regional_summary.sort_values('Total_Traffic_GB', ascending=False)
    reports['Regional_Summary'] = regional_summary

    top_sites = combined_df.groupby('Site_Name').agg({
        'Region': 'first',
        '2G_Traffic_GB': 'sum',
        '3G_Traffic_GB': 'sum',
        '4G_Traffic_GB': 'sum',
        'Total_Traffic_GB': 'sum'
    }).reset_index()
    top_sites = top_sites.nlargest(50, 'Total_Traffic_GB')
    reports['Top_50_Sites'] = top_sites

    worst_sites = combined_df.groupby('Site_Name').agg({
        'Region': 'first',
        '2G_Traffic_GB': 'sum',
        '3G_Traffic_GB': 'sum',
        '4G_Traffic_GB': 'sum',
        'Total_Traffic_GB': 'sum'
    }).reset_index()
    worst_sites = worst_sites[worst_sites['Total_Traffic_GB'] > 0]
    worst_sites = worst_sites.nsmallest(50, 'Total_Traffic_GB')
    reports['Worst_50_Sites'] = worst_sites

    tech_share = combined_df.groupby('Date').agg({
        '2G_Traffic_GB': 'sum',
        '3G_Traffic_GB': 'sum',
        '4G_Traffic_GB': 'sum'
    }).reset_index()
    total_by_date = tech_share[['2G_Traffic_GB', '3G_Traffic_GB', '4G_Traffic_GB']].sum(axis=1)
    for tech in ['2G', '3G', '4G']:
        tech_share[f'{tech}_Share_%'] = (tech_share[f'{tech}_Traffic_GB'] / total_by_date * 100).round(2)
    tech_share['Date_Formatted'] = tech_share['Date'].dt.strftime('%d-%m-%Y')
    reports['Tech_Share_by_Date'] = tech_share

    if not combined_df.empty:
        site_coverage = combined_df.groupby('Site_Name').agg({
            'Region': 'first',
            '2G_Traffic_GB': lambda x: (x > 0).sum() if len(x) > 0 else 0,
            '3G_Traffic_GB': lambda x: (x > 0).sum() if len(x) > 0 else 0,
            '4G_Traffic_GB': lambda x: (x > 0).sum() if len(x) > 0 else 0,
            'Total_Traffic_GB': 'sum'
        }).reset_index()
        site_coverage.columns = ['Site_Name', 'Region', 'Days_With_2G', 'Days_With_3G', 'Days_With_4G', 'Total_Traffic_GB']
        site_coverage['Has_2G'] = site_coverage['Days_With_2G'] > 0
        site_coverage['Has_3G'] = site_coverage['Days_With_3G'] > 0
        site_coverage['Has_4G'] = site_coverage['Days_With_4G'] > 0

        def get_tech_combo(row):
            combo = []
            if row['Has_2G']: combo.append('2G')
            if row['Has_3G']: combo.append('3G')
            if row['Has_4G']: combo.append('4G')
            return '+'.join(combo) if combo else 'None'

        site_coverage['Tech_Combination'] = site_coverage.apply(get_tech_combo, axis=1)
        reports['Site_Coverage'] = site_coverage

    return reports


def save_historical_archive(combined_df, reports, archive_dir, date_range):
    """
    Save processed data to historical archive with timestamp.
    """
    if not os.path.exists(archive_dir):
        os.makedirs(archive_dir)
        print(f"  📁 Created archive directory: {archive_dir}")

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    archive_filename = f"PS_Traffic_History_{date_range}_{timestamp}.xlsx"
    archive_path = os.path.join(archive_dir, archive_filename)
    csv_filename = f"PS_Traffic_History_{date_range}_{timestamp}.csv"
    csv_path = os.path.join(archive_dir, csv_filename)

    print(f"  📁 Archiving to: {archive_path}")

    with pd.ExcelWriter(archive_path, engine='openpyxl') as writer:
        if len(combined_df) > 0:
            export_df = combined_df.copy()
            export_df['Date'] = export_df['Date'].dt.strftime('%d-%m-%Y')
            export_df = export_df.drop('Date_Formatted', axis=1)
            export_df.to_excel(writer, sheet_name='All_Traffic_Data', index=False)
        else:
            empty_df = pd.DataFrame(columns=['Date', 'Site_Name', '2G_Traffic_GB', '3G_Traffic_GB',
                                             '4G_Traffic_GB', 'Total_Traffic_GB', 'Region'])
            empty_df.to_excel(writer, sheet_name='All_Traffic_Data', index=False)

        for sheet_name, df in reports.items():
            if not df.empty:
                if 'Date' in df.columns and 'Date_Formatted' in df.columns:
                    df = df.copy()
                    df['Date'] = df['Date_Formatted']
                    df = df.drop('Date_Formatted', axis=1)
                df.to_excel(writer, sheet_name=sheet_name, index=False)

        for sheet in writer.sheets.values():
            for column in sheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except Exception:
                        pass
                sheet.column_dimensions[column_letter].width = min(max_length + 2, 30)

    if len(combined_df) > 0:
        export_df = combined_df.copy()
        export_df['Date'] = export_df['Date'].dt.strftime('%d-%m-%Y')
        export_df = export_df.drop('Date_Formatted', axis=1)
        export_df.to_csv(csv_path, index=False)
        print(f"  📁 CSV version: {csv_path}")

    return archive_path, csv_path


def save_to_excel(combined_df, reports, output_path):
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        if len(combined_df) > 0:
            export_df = combined_df.copy()
            export_df['Date'] = export_df['Date'].dt.strftime('%d-%m-%Y')
            export_df = export_df.drop('Date_Formatted', axis=1)
            export_df.to_excel(writer, sheet_name='All_Traffic_Data', index=False)
        else:
            empty_df = pd.DataFrame(columns=['Date', 'Site_Name', '2G_Traffic_GB', '3G_Traffic_GB', '4G_Traffic_GB', 'Total_Traffic_GB', 'Region'])
            empty_df.to_excel(writer, sheet_name='All_Traffic_Data', index=False)

        for sheet_name, df in reports.items():
            if not df.empty:
                if 'Date' in df.columns and 'Date_Formatted' in df.columns:
                    df = df.copy()
                    df['Date'] = df['Date_Formatted']
                    df = df.drop('Date_Formatted', axis=1)
                df.to_excel(writer, sheet_name=sheet_name, index=False)

        for sheet in writer.sheets.values():
            for column in sheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except Exception:
                        pass
                sheet.column_dimensions[column_letter].width = min(max_length + 2, 30)

    return output_path


def main(date_folder=None):
    if not date_folder:
        date_folder = resolve_date_folder(None)
    else:
        date_folder = resolve_date_folder(date_folder)

    print("=" * 60)
    print("Processing PS Daily Traffic Files")
    print("=" * 60)
    print(f"📂 Date folder: {date_folder}")
    print(f"📦 Base raw data folder: {base_raw_data_folder}")

    unzipped_folder = os.path.join(date_folder, "unzipped")
    file_2g, file_3g, file_4g = find_ps_traffic_files(unzipped_folder)

    if not file_2g and not file_3g and not file_4g:
        print("❌ No PS Traffic files found!")
        return None

    data_frames = {}
    df_2g_raw = load_traffic_file(file_2g, "2G")
    if df_2g_raw is not None:
        data_frames['2G'] = process_2g_data(df_2g_raw)

    df_3g_raw = load_traffic_file(file_3g, "3G")
    if df_3g_raw is not None:
        data_frames['3G'] = process_3g_data(df_3g_raw)

    df_4g_raw = load_traffic_file(file_4g, "4G")
    if df_4g_raw is not None:
        data_frames['4G'] = process_4g_data(df_4g_raw)

    if not data_frames:
        print("❌ No data loaded!")
        return None

    analyze_site_coverage(data_frames)

    print("\n🔄 Combining data from all technologies...")
    combined_df = combine_traffic_data(data_frames)

    if len(combined_df) == 0:
        print("❌ Error: No valid data after processing!")
        return None

    print("\n📊 Generating summary reports...")
    reports = generate_summary_reports(combined_df)

    output_folder = os.path.join(date_folder, "output")
    os.makedirs(output_folder, exist_ok=True)
    today_str = datetime.now().strftime("%Y-%m-%d")
    output_filename = f"PS_Traffic_Combined_Report_{today_str}.xlsx"
    output_path = os.path.join(output_folder, output_filename)

    print(f"\n💾 Saving to Excel file: {output_path}")
    save_to_excel(combined_df, reports, output_path)

    print("\n📁 Creating historical archive...")
    if len(combined_df) > 0 and combined_df['Date'].notna().any():
        min_date = combined_df['Date'].min()
        max_date = combined_df['Date'].max()
        date_range = f"{min_date.strftime('%Y%m%d')}_{max_date.strftime('%Y%m%d')}" if pd.notna(min_date) and pd.notna(max_date) else "nodate"
    else:
        date_range = "nodata"

    archive_dir = os.path.join(os.path.dirname(date_folder), "Historical_Archive")
    archive_path, csv_path = save_historical_archive(combined_df, reports, archive_dir, date_range)

    print("\n" + "=" * 60)
    print("✅ Processing Complete!")
    print("=" * 60)
    if len(combined_df) > 0 and combined_df['Date'].notna().any():
        min_date = combined_df['Date'].min()
        max_date = combined_df['Date'].max()
        if pd.notna(min_date) and pd.notna(max_date):
            print(f"📅 Date Range: {min_date.strftime('%d-%m-%Y')} to {max_date.strftime('%d-%m-%Y')}")

    print(f"📍 Total Sites: {combined_df['Site_Name'].nunique()}")
    print(f"📈 Total Records: {len(combined_df)}")
    print(f"🌍 Regions Found: {combined_df['Region'].nunique()}")
    print(f"\n📊 Total Traffic Summary:")
    print(f"   2G: {combined_df['2G_Traffic_GB'].sum():,.2f} GB")
    print(f"   3G: {combined_df['3G_Traffic_GB'].sum():,.2f} GB")
    print(f"   4G: {combined_df['4G_Traffic_GB'].sum():,.2f} GB")
    print(f"   Total: {combined_df['Total_Traffic_GB'].sum():,.2f} GB")
    print(f"\n📁 Output file: {output_path}")
    print(f"📁 Archive file: {archive_path}")

    return combined_df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process PS Traffic data from already unzipped raw files.")
    parser.add_argument("--date", "-d", help="Date folder name (YYYYMMDD) or direct path to the raw data date folder.")
    args = parser.parse_args()

    selected_folder = resolve_date_folder(args.date)
    if not os.path.exists(selected_folder):
        print(f"❌ Date folder not found: {selected_folder}")
    else:
        main(selected_folder)
