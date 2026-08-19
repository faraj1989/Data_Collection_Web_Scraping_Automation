# Libyana Automation Suite

Windows automation for MAE, NetEco, SmartCare, subscriber reporting, PS traffic analysis, and Telegram NOC reporting.

## First-time setup

1. Create and activate a virtual environment.
2. Install the pinned dependencies: `python -m pip install -r requirements.txt`.
3. Copy `.env.example` to `.env`, then enter the current credentials and service URLs.
4. Start [Start Automation Master Orchestrator.bat](<Start Automation Master Orchestrator.bat>) or run `python orchestrator_gui.py`.

Never commit `.env`, generated reports, logs, or downloaded data. They are excluded by `.gitignore`.

## Active entry points

Use these stable names for new shortcuts, scheduled tasks, and documentation:

- `mae_scraper.py`
- `neteco_scraper.py`
- `neteco_dual_current_alarm_scraper.py` (original and All Current Alarms views in one session)
- `merge_noc_reports.py`
- `subscriber_reports.py`
- `ps_traffic_report.py`
- `enhanced_noc_analysis.py` (site-centric MAE + NetEco incident and root-cause analysis)
- `run_smartcare_analysis_task.py`
- `telegram_noc_bot.py`

The older date/version-named scripts are retained as implementation compatibility targets. The stable entry points let those internal names be replaced later without changing operations.

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
.\.venv\Scripts\python.exe "SmartCare CEM\SmartCare CEM v11.py" --help
```
