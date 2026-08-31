"""Robust reader for MAE/NetEco Historical Alarms exports.

Both scrapers/mae_historical_alarms_scraper.py and
scrapers/neteco_historical_alarms_scraper.py save either a direct .csv or a
.zip of 1+ "HistoricalAlarms<n>.csv" parts. Each part has a preamble (title /
save-time / username / a multi-line quoted "Maintenance Status" field / blank
line) before the real header row, so the header is located by content match
rather than a fixed skiprows count - the embedded multi-line quoted field
makes line-counting unreliable, and Excel's own CSV writer does not always
repeat the preamble on every zip part.

MAE and NetEco use genuinely different column sets (confirmed against real
exports, not assumed):
  MAE:    <blank>, NE Type, MO Name, Name, Occurred On (NT), Cleared On (NT),
          Severity, Alarm ID, Alarm Duration
  NetEco: <blank>, Severity, Name, Site Name, Last Occurred, Cleared On,
          Device, Manage Domain, Device Type, Location Info
The leading "<blank>" column is not actually blank - it holds a correlation
flag ("Root alarm" / "Correlative alarm" / "-"), which is real root-cause
signal worth keeping. This module normalizes both schemas into one common
DataFrame shape by picking whichever known column name is present per field,
rather than branching on source name.
"""
import csv
import hashlib
import io
import re
import zipfile
from pathlib import Path

import pandas as pd

# canonical field -> candidate column names, in preference order
FIELD_ALIASES = {
    "ne_type": ("NE Type", "Device Type"),
    "site": ("MO Name", "Site Name"),
    "name": ("Name",),
    "occurred": ("Occurred On (NT)", "Last Occurred"),
    "cleared": ("Cleared On (NT)", "Cleared On"),
    "severity": ("Severity",),
    "alarm_id": ("Alarm ID",),
    "duration_text": ("Alarm Duration",),
    "device": ("Device",),
    "manage_domain": ("Manage Domain",),
    "location_info": ("Location Info",),
}

DURATION_RE = re.compile(
    r"(?:(?P<h>\d+)\s*hours?)?\s*(?:(?P<m>\d+)\s*minutes?)?\s*(?:(?P<s>\d+)\s*seconds?)?", re.IGNORECASE
)


def _is_header_row(cells) -> bool:
    stripped = [c.strip() for c in cells]
    has_site = "MO Name" in stripped or "Site Name" in stripped
    return "Name" in stripped and "Severity" in stripped and has_site


def _clean_correlation_flag(value: str) -> str:
    text = (value or "").replace("\t", "").strip()
    return text if text else "-"


def parse_duration_to_seconds(text):
    if text is None:
        return None
    text = str(text).strip()
    if not text or text == "-":
        return None
    match = DURATION_RE.search(text)
    if not match or not any(match.groups()):
        return None
    hours = int(match.group("h") or 0)
    minutes = int(match.group("m") or 0)
    seconds = int(match.group("s") or 0)
    return hours * 3600 + minutes * 60 + seconds


def _rows_from_excel(path: Path):
    """Read a raw .xlsx/.xlsm historical export as plain string rows, the same
    shape csv.reader would produce. Seen when a stray download never got
    zipped by its scraper (e.g. it landed in a shared/misconfigured download
    folder before being renamed and moved)."""
    frame = pd.read_excel(path, header=None, dtype=str, engine="openpyxl")
    return [["" if pd.isna(value) else str(value) for value in row] for row in frame.itertuples(index=False, name=None)]


def _iter_row_batches(export_path: Path):
    """Yield (member_name, rows) for every tabular payload in an export, where
    rows is a list of already-split row values - handles a direct .csv, a
    .zip of 1+ "HistoricalAlarms<n>.csv" parts, or a raw .xlsx/.xlsm export."""
    suffix = export_path.suffix.lower()
    if suffix == ".zip":
        with zipfile.ZipFile(export_path) as zf:
            names = sorted(n for n in zf.namelist() if n.lower().endswith(".csv"))
            for name in names:
                raw = zf.read(name)
                text = raw.decode("utf-8-sig", errors="replace")
                yield name, list(csv.reader(text.splitlines()))
    elif suffix in (".xlsx", ".xlsm"):
        yield export_path.name, _rows_from_excel(export_path)
    else:
        text = export_path.read_text(encoding="utf-8-sig", errors="replace")
        yield export_path.name, list(csv.reader(text.splitlines()))


def file_fingerprint(path: Path) -> str:
    """Content hash so a stray copy of an export already folded into the
    ledger is recognized even if its name, location, or mtime changed."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detect_source(export_path: Path):
    """Identify whether a raw export is MAE- or NetEco-shaped by its header
    row. Needed for a stray download whose generic browser filename (e.g.
    "HistoricalAlarms20260824195647961.zip") doesn't say which scraper
    produced it - which happens precisely when both scrapers' download
    folders were misconfigured to the same shared path. Returns "MAE",
    "NetEco", or None if the file doesn't look like either."""
    try:
        for _member_name, rows in _iter_row_batches(Path(export_path)):
            for row in rows:
                if row and _is_header_row(row):
                    stripped = [str(c).strip() for c in row]
                    if "MO Name" in stripped:
                        return "MAE"
                    if "Site Name" in stripped:
                        return "NetEco"
                    return None
    except Exception:
        return None
    return None


def _parse_part(rows, source_label):
    header = None
    header_idx = None
    for idx, row in enumerate(rows):
        if row and _is_header_row(row):
            header = [str(c).strip() for c in row]
            header_idx = idx
            break
    if header is None:
        return [], None

    col_index = {name: i for i, name in enumerate(header) if name}
    field_index = {}
    for field, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if alias in col_index:
                field_index[field] = col_index[alias]
                break

    records = []
    for row in rows[header_idx + 1:]:
        if not row or all(not str(c).strip() for c in row):
            continue

        def get(field):
            idx = field_index.get(field)
            if idx is None or idx >= len(row):
                return None
            value = str(row[idx]).strip()
            return value if value and value.lower() != "nan" else None

        records.append({
            "Correlation Flag": _clean_correlation_flag(row[0] if row else ""),
            "NE Type": get("ne_type"),
            "Site": get("site"),
            "Name": get("name"),
            "Occurred On": get("occurred"),
            "Cleared On": get("cleared"),
            "Severity": get("severity"),
            "Alarm ID": get("alarm_id"),
            "Alarm Duration Text": get("duration_text"),
            "Device": get("device"),
            "Manage Domain": get("manage_domain"),
            "Location Info": get("location_info"),
            "_source_file": source_label,
        })
    return records, header


def load_historical_export(export_path, source: str) -> pd.DataFrame:
    """Parse a MAE or NetEco Historical Alarms export (.csv or .zip of parts)
    into a normalized DataFrame. `source` is a free-text label ("MAE" or
    "NetEco") stamped onto every row - it does not affect parsing, since
    column presence alone drives field mapping."""
    export_path = Path(export_path)
    all_records = []
    seen_keys = set()

    for member_name, rows in _iter_row_batches(export_path):
        records, header = _parse_part(rows, f"{export_path.name}:{member_name}")
        if header is None:
            continue
        for record in records:
            key = (record["Site"], record["Name"], record["Occurred On"])
            if key in seen_keys:
                continue
            seen_keys.add(key)
            all_records.append(record)

    df = pd.DataFrame.from_records(
        all_records,
        columns=["Correlation Flag", "NE Type", "Site", "Name", "Occurred On", "Cleared On",
                 "Severity", "Alarm ID", "Alarm Duration Text", "Device", "Manage Domain",
                 "Location Info", "_source_file"],
    )
    df.insert(0, "Source", source)
    if df.empty:
        df["Occurred On"] = pd.Series(dtype="datetime64[ns]")
        df["Cleared On"] = pd.Series(dtype="datetime64[ns]")
        df["Alarm Duration Seconds"] = pd.Series(dtype="float64")
        return df

    df["Occurred On"] = pd.to_datetime(df["Occurred On"], errors="coerce")
    df["Cleared On"] = pd.to_datetime(df["Cleared On"], errors="coerce")

    duration_from_text = df["Alarm Duration Text"].map(parse_duration_to_seconds)
    duration_from_timestamps = (df["Cleared On"] - df["Occurred On"]).dt.total_seconds()
    df["Alarm Duration Seconds"] = duration_from_text.fillna(duration_from_timestamps)
    return df
