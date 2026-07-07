import pandas as pd
import re
import os
from zipfile import ZipFile
from io import StringIO


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
    data_lines = lines[start_idx:-1]  # -1 removes the footer line

    # Remove any empty lines
    data_lines = [line for line in data_lines if line.strip()]

    return '\n'.join(data_lines)


def read_traffic_files(zip_path):
    """
    Read 2G, 3G, and 4G traffic data from zip file.
    """
    data_frames = {}

    with ZipFile(zip_path, 'r') as zip_file:
        for file_name in zip_file.namelist():
            if not file_name.endswith('.csv'):
                continue

            print(f"\nReading: {file_name}")

            # Read and clean the file content
            with zip_file.open(file_name) as f:
                content = f.read().decode('utf-8', errors='ignore')
                clean_content = clean_csv_content(content)

            # Read the cleaned CSV
            df = pd.read_csv(StringIO(clean_content))

            print(f"  Columns found: {list(df.columns)}")
            print(f"  Number of rows: {len(df)}")

            # Print first few dates to debug
            print(f"  First 5 dates: {df['Date'].head().tolist()}")

            # Remove footer row if present (last row)
            df = df[:-1] if len(df) > 0 else df

            # Determine which technology based on file name
            # Clean the filename by replacing non-breaking spaces with regular spaces
            clean_file_name = file_name.replace('\u00A0', ' ')

            if "(PS Traffic 2G)" in clean_file_name:
                # 2G Processing - using exact column names
                # Site: eGBTS, Traffic: PS Traffic(GB)
                print("  - Detected as 2G file")
                df_2g = df[['Date', 'eGBTS', 'PS Traffic(GB)']].copy()
                df_2g.columns = ['Date', 'Site_Name', 'Traffic_GB']
                df_2g['Technology'] = '2G'
                data_frames['2G'] = df_2g
                print(f"  - Loaded {len(df_2g)} 2G records")
                print(f"  - Unique 2G sites: {df_2g['Site_Name'].nunique()}")

            elif "(PS Traffic 3G)" in clean_file_name:
                # 3G Processing - using exact column names
                # Site: NodeB, Traffic: PS traffic (GB)
                print("  - Detected as 3G file")
                df_3g = df[['Date', 'NodeB', 'PS traffic (GB)']].copy()
                df_3g.columns = ['Date', 'Site_Name', 'Traffic_GB']
                df_3g['Technology'] = '3G'
                data_frames['3G'] = df_3g
                print(f"  - Loaded {len(df_3g)} 3G records")
                print(f"  - Unique 3G sites: {df_3g['Site_Name'].nunique()}")

            elif "(PS Traffic 4G)" in clean_file_name:
                # 4G Processing - using exact column names
                # Site: eNodeB Name, Traffic: Downlink Traffic Volume(GB) + UL Traffic Volume(GB)
                print("  - Detected as 4G file")
                dl_col = None
                ul_col = None

                for col in df.columns:
                    if 'Downlink Traffic Volume(GB)' in col:
                        dl_col = col
                    elif 'UL Traffic  Volume(GB)' in col:
                        ul_col = col

                if dl_col and ul_col:
                    df_4g = df[['Date', 'eNodeB Name', dl_col, ul_col]].copy()
                    df_4g.columns = ['Date', 'Site_Name', 'DL_GB', 'UL_GB']
                    df_4g['Traffic_GB'] = df_4g['DL_GB'] + df_4g['UL_GB']
                    df_4g['Technology'] = '4G'
                    data_frames['4G'] = df_4g[['Date', 'Site_Name', 'Traffic_GB', 'Technology']]
                    print(f"  - Loaded {len(df_4g)} 4G records")
                    print(f"  - Unique 4G sites: {df_4g['Site_Name'].nunique()}")
                else:
                    print(f"  - Warning: Could not find DL/UL columns for 4G")
                    print(f"    Available columns: {list(df.columns)}")
            else:
                print(f"  - Skipping: Unknown file type (clean name: {clean_file_name})")

    return data_frames


def combine_traffic_data(data_frames):
    """
    Combine 2G, 3G, and 4G data into a single pivoted dataframe.
    """
    # Combine all technologies
    all_data = pd.concat(data_frames.values(), ignore_index=True)

    print(f"\nTotal records before processing: {len(all_data)}")
    print(f"Records by technology:\n{all_data['Technology'].value_counts()}")

    # Print sample dates before conversion
    print(f"\nSample dates before conversion: {all_data['Date'].head(10).tolist()}")
    print(f"Date data type: {all_data['Date'].dtype}")

    # The date format is YYYY-MM-DD
    all_data['Date_parsed'] = pd.to_datetime(all_data['Date'], format='%Y-%m-%d', errors='coerce')

    # If that doesn't work, try with other formats
    if all_data['Date_parsed'].isna().all():
        print("  - YYYY-MM-DD format didn't work, trying to infer format...")
        all_data['Date_parsed'] = pd.to_datetime(all_data['Date'], errors='coerce')

    # Show sample parsed dates
    print(f"\nSample dates after parsing: {all_data['Date_parsed'].head(10).tolist()}")

    # Count successful conversions
    valid_dates = all_data['Date_parsed'].notna().sum()
    print(f"Valid dates: {valid_dates} out of {len(all_data)}")

    # Remove any rows with invalid dates
    invalid_dates = all_data['Date_parsed'].isna().sum()
    if invalid_dates > 0:
        print(f"  - Removing {invalid_dates} rows with invalid dates")
        all_data = all_data.dropna(subset=['Date_parsed'])

    # Replace Date column with parsed version
    all_data['Date'] = all_data['Date_parsed']
    all_data = all_data.drop('Date_parsed', axis=1)

    if len(all_data) == 0:
        print("  - Warning: No valid dates found after parsing!")
        return pd.DataFrame()  # Return empty dataframe

    # Print unique sites per technology after date filtering
    print(f"\nUnique sites after date filtering:")
    for tech in ['2G', '3G', '4G']:
        tech_data = all_data[all_data['Technology'] == tech]
        if len(tech_data) > 0:
            print(f"  {tech}: {tech_data['Site_Name'].nunique()} unique sites")

    # Pivot to get separate columns for each technology
    pivoted = all_data.pivot_table(
        index=['Date', 'Site_Name'],
        columns='Technology',
        values='Traffic_GB',
        aggfunc='sum',
        fill_value=0
    ).reset_index()

    # Ensure all technology columns exist
    for tech in ['2G', '3G', '4G']:
        if tech not in pivoted.columns:
            pivoted[tech] = 0

    # Rename columns for clarity
    pivoted.columns = ['Date', 'Site_Name', '2G_Traffic_GB', '3G_Traffic_GB', '4G_Traffic_GB']

    # Calculate total traffic
    pivoted['Total_Traffic_GB'] = pivoted['2G_Traffic_GB'] + pivoted['3G_Traffic_GB'] + pivoted['4G_Traffic_GB']

    # Extract region from site name (prefix before numbers/underscore/parentheses)
    def extract_region(site_name):
        if pd.isna(site_name):
            return 'Unknown'
        site_str = str(site_name)
        # Remove parentheses and anything inside them (like FN)
        site_str = re.sub(r'\([^)]*\)', '', site_str)
        # Extract letters at the beginning (region name)
        match = re.match(r'^([A-Za-z]+)', site_str)
        if match:
            return match.group(1)
        return 'Other'

    pivoted['Region'] = pivoted['Site_Name'].apply(extract_region)

    # Sort by Date and Site Name
    pivoted = pivoted.sort_values(['Date', 'Site_Name']).reset_index(drop=True)

    # Format date as d-m-y for display
    pivoted['Date_Formatted'] = pivoted['Date'].dt.strftime('%d-%m-%Y')

    return pivoted


def generate_summary_reports(combined_df):
    """
    Generate summary reports from combined data.
    """
    reports = {}

    if len(combined_df) == 0:
        print("  - Warning: No data to generate summary reports")
        return reports

    # 1. Daily summary - format dates as d-m-y
    daily_summary = combined_df.groupby('Date').agg({
        '2G_Traffic_GB': 'sum',
        '3G_Traffic_GB': 'sum',
        '4G_Traffic_GB': 'sum',
        'Total_Traffic_GB': 'sum'
    }).reset_index()
    daily_summary['Date_Formatted'] = daily_summary['Date'].dt.strftime('%d-%m-%Y')
    daily_summary = daily_summary.sort_values('Date')
    reports['Daily_Summary'] = daily_summary

    # 2. Regional summary
    regional_summary = combined_df.groupby('Region').agg({
        '2G_Traffic_GB': 'sum',
        '3G_Traffic_GB': 'sum',
        '4G_Traffic_GB': 'sum',
        'Total_Traffic_GB': 'sum'
    }).reset_index()
    regional_summary = regional_summary.sort_values('Total_Traffic_GB', ascending=False)
    reports['Regional_Summary'] = regional_summary

    # 3. Top 50 sites by total traffic
    top_sites = combined_df.groupby('Site_Name').agg({
        'Region': 'first',
        '2G_Traffic_GB': 'sum',
        '3G_Traffic_GB': 'sum',
        '4G_Traffic_GB': 'sum',
        'Total_Traffic_GB': 'sum'
    }).reset_index()
    top_sites = top_sites.nlargest(50, 'Total_Traffic_GB')
    reports['Top_50_Sites'] = top_sites

    # 4. Technology share by date - format dates as d-m-y
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

    return reports


def save_to_excel(combined_df, reports, output_path):
    """
    Save all data to Excel with multiple sheets.
    """
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        # Main combined data - use formatted date
        if len(combined_df) > 0:
            export_df = combined_df.copy()
            # Replace Date with formatted version for Excel
            export_df['Date'] = export_df['Date'].dt.strftime('%d-%m-%Y')
            export_df = export_df.drop('Date_Formatted', axis=1)
            export_df.to_excel(writer, sheet_name='All_Traffic_Data', index=False)
        else:
            # Create an empty dataframe with the expected columns
            empty_df = pd.DataFrame(
                columns=['Date', 'Site_Name', '2G_Traffic_GB', '3G_Traffic_GB', '4G_Traffic_GB', 'Total_Traffic_GB',
                         'Region'])
            empty_df.to_excel(writer, sheet_name='All_Traffic_Data', index=False)

        # Summary reports
        for sheet_name, df in reports.items():
            # For reports with dates, format them
            if 'Date' in df.columns and not df.empty:
                if 'Date_Formatted' in df.columns:
                    df = df.copy()
                    df['Date'] = df['Date_Formatted']
                    df = df.drop('Date_Formatted', axis=1)
            df.to_excel(writer, sheet_name=sheet_name, index=False)

        # Auto-adjust column widths
        for sheet in writer.sheets.values():
            for column in sheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 30)
                sheet.column_dimensions[column_letter].width = adjusted_width


def main(zip_file_path, output_file_path):
    """
    Main function to process traffic files and generate combined report.
    """
    print("=" * 60)
    print("Processing PS Daily Traffic Files")
    print("=" * 60)

    # Check if file exists
    if not os.path.exists(zip_file_path):
        print(f"❌ Error: Could not find '{zip_file_path}'")
        print("Please update the zip_file_path variable with the correct path.")
        return None

    # Read all files
    print("\n📂 Reading CSV files from zip archive...")
    data_frames = read_traffic_files(zip_file_path)

    if not data_frames:
        print("❌ Error: No data files found in the zip archive!")
        return None

    # Combine data
    print("\n🔄 Combining data from all technologies...")
    combined_df = combine_traffic_data(data_frames)

    if len(combined_df) == 0:
        print("❌ Error: No valid data after processing!")
        return None

    # Generate summaries
    print("\n📊 Generating summary reports...")
    reports = generate_summary_reports(combined_df)

    # Save to Excel
    print(f"\n💾 Saving to Excel file: {output_file_path}")
    save_to_excel(combined_df, reports, output_file_path)

    # Print statistics with formatted dates
    print("\n" + "=" * 60)
    print("✅ Processing Complete!")
    print("=" * 60)

    if len(combined_df) > 0 and combined_df['Date'].notna().any():
        min_date = combined_df['Date'].min()
        max_date = combined_df['Date'].max()
        if pd.notna(min_date) and pd.notna(max_date):
            print(f"📅 Date Range: {min_date.strftime('%d-%m-%Y')} to {max_date.strftime('%d-%m-%Y')}")
    else:
        print("📅 Date Range: No valid dates found")

    print(f"📍 Total Sites: {combined_df['Site_Name'].nunique()}")
    print(f"📈 Total Records: {len(combined_df)}")
    print(f"🌍 Regions Found: {combined_df['Region'].nunique()}")
    print(f"\n📊 Total Traffic Summary:")
    print(f"   2G: {combined_df['2G_Traffic_GB'].sum():,.2f} GB")
    print(f"   3G: {combined_df['3G_Traffic_GB'].sum():,.2f} GB")
    print(f"   4G: {combined_df['4G_Traffic_GB'].sum():,.2f} GB")
    print(f"   Total: {combined_df['Total_Traffic_GB'].sum():,.2f} GB")
    print(f"\n📁 Output file: {output_file_path}")

    return combined_df


# Run the script
if __name__ == "__main__":
    # Update this to your actual zip file location
    ZIP_FILE_PATH = r"C:\Users\faraj\Downloads\PS Daily Traffic_2G_3G_4G_ L7D_20260615235036-20260616000135.zip"
    OUTPUT_FILE_PATH = "Combined_Traffic_Report.xlsx"

    result = main(ZIP_FILE_PATH, OUTPUT_FILE_PATH)