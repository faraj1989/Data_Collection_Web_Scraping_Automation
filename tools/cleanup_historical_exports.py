"""Delete raw MAE/NetEco Historical Alarms exports older than
HISTORICAL_RAW_EXPORT_RETENTION_DAYS (default 3 days).

Both historical scrapers write a new multi-part zip/csv every 5-7 minutes and
never delete anything themselves, so raw exports accumulate at roughly
1-2.5 GB/day combined. processing/historical_noc_analysis.py folds every
export into a persistent ledger (HISTORICAL_LEDGER_PATH) that keeps the data
that actually matters (chronic-offender/trend history) indefinitely, so the
raw dated export files are safe to prune once they age out - the ledger, not
the raw exports, is the long-term record.

Run on demand or as a daily scheduled task (see scheduler_tasks.py).
"""
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from project_config import env_int, env_path, load_env_file

load_env_file()
MAE_EXPORT_DIR = env_path("MAE_HISTORICAL_EXPORT_BASE_DIR", r"C:\Historical_Alarms")
NETECO_EXPORT_DIR = env_path("NETECO_HISTORICAL_EXPORT_BASE_DIR", r"C:\Historical_Alarms")
RETENTION_DAYS = env_int("HISTORICAL_RAW_EXPORT_RETENTION_DAYS", 3)

EXPORT_PATTERNS = ("HistoricalAlarms_MAE_*.*", "NetEco_Historical_Alarm_*.*")


def log(message):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def find_export_files(base_dirs, patterns):
    seen = set()
    files = []
    for base_dir in base_dirs:
        if not base_dir.exists():
            continue
        for pattern in patterns:
            for path in list(base_dir.glob(f"*/{pattern}")) + list(base_dir.glob(pattern)):
                if path not in seen and path.is_file():
                    seen.add(path)
                    files.append(path)
    return files


def cleanup(base_dirs, retention_days: int, dry_run: bool = False) -> int:
    cutoff = datetime.now() - timedelta(days=retention_days)
    deleted = 0
    for path in find_export_files(base_dirs, EXPORT_PATTERNS):
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        if mtime < cutoff:
            log(f"{'Would delete' if dry_run else 'Deleting'}: {path} (modified {mtime:%Y-%m-%d %H:%M})")
            if not dry_run:
                try:
                    path.unlink()
                    deleted += 1
                except OSError as exc:
                    log(f"WARNING: could not delete {path}: {exc}")
            else:
                deleted += 1
    return deleted


def main():
    dry_run = "--dry-run" in sys.argv
    log(f"Retention: {RETENTION_DAYS} days")
    log(f"MAE export dir: {MAE_EXPORT_DIR}")
    log(f"NetEco export dir: {NETECO_EXPORT_DIR}")
    base_dirs = {MAE_EXPORT_DIR, NETECO_EXPORT_DIR}
    count = cleanup(base_dirs, RETENTION_DAYS, dry_run=dry_run)
    log(f"{'Would have deleted' if dry_run else 'Deleted'} {count} file(s) older than {RETENTION_DAYS} days.")


if __name__ == "__main__":
    main()
