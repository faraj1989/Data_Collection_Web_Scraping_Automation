# NOC Automation Suite

Windows automation for MAE, NetEco, SmartCare, subscriber reporting, PS traffic analysis, and Telegram NOC reporting.

## First-time setup

1. Create and activate a virtual environment.
2. Install the pinned dependencies: `python -m pip install -r requirements.txt`.
3. Copy `.env.example` to `.env`, then enter the current credentials and service URLs.
4. Start [Start Control Panel.bat](<Start Control Panel.bat>) or run `python control_panel.py`.

Never commit `.env`, generated reports, logs, or downloaded data. They are excluded by `.gitignore`.

## Project layout

Code is grouped by function; `control_panel.py`, `service_watchdog.py`, `project_config.py`,
and `project_logging.py` stay at the repo root as the control/config layer.

- `scrapers/` — MAE and NetEco alarm scrapers
- `processing/` — report merging and site-centric NOC analysis
- `reports/` — SmartCare CEM, comprehensive analysis, PS traffic, subscriber reporting
- `bots/` — Telegram NOC bot
- `tools/` — standalone dev utilities

## Active entry points

Use these stable names for new shortcuts, scheduled tasks, and documentation:

- `scrapers/mae_scraper.py`
- `scrapers/neteco_scraper.py`
- `scrapers/neteco_all_alarms_scraper.py`
- `processing/merge_noc_reports.py`
- `processing/enhanced_noc_analysis.py` (site-centric MAE + NetEco incident and root-cause analysis)
- `reports/subscriber_reports.py`
- `reports/ps_traffic_report.py`
- `reports/run_smartcare_analysis_task.py`
- `bots/telegram_noc_bot.py`

The older date/version-named scripts are retained as implementation compatibility targets. The stable entry points let those internal names be replaced later without changing operations. `script_registry.py`'s `SCRIPT_REGISTRY` is the single source of truth for every script's location.

## Security and operations

- Rotate the previously exposed Telegram and FTP credentials before restarting services.
- Keep `FTP_IGNORE_CERT=False` unless a legacy internal server requires otherwise.
- Existing historical runtime logs may contain the old Telegram token; handle or remove them securely after rotation.
- SmartCare now accepts `--download-dir` and `--output-dir`; successful exports are moved into the analysis source folder.

## Verification

Run the offline checks before deployment:

```powershell
.\.venv\Scripts\python.exe -m compileall -q .
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe "reports\SmartCare CEM v11.py" --help
```
