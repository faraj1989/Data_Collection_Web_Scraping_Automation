import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

from project_config import load_env_file
from project_logging import setup_logger


def default_paths() -> dict:
    project_root = Path(__file__).resolve().parent
    download_dir = Path(os.getenv("SMARTCARE_DOWNLOAD_DIR", str(Path.home() / "Downloads"))).expanduser()
    smartcare_output_dir = Path(os.getenv("SMARTCARE_OUTPUT_DIR", str(Path.home() / "Downloads" / "SmartCare_Exports"))).expanduser()
    analysis_output_dir = Path(os.getenv("ANALYSIS_OUTPUT_DIR", str(Path.home() / "Downloads" / "Processed_Analysis"))).expanduser()
    history_file = Path(os.getenv("ANALYSIS_HISTORY_FILE", str(analysis_output_dir / "Comprehensive_Analysis_Historical.xlsx"))).expanduser()

    return {
        "smartcare_script": project_root / "SmartCare CEM" / "SmartCare CEM v11.py",
        "analysis_script": project_root / "download_analysis_pipeline.py",
        "download_dir": download_dir,
        "smartcare_output_dir": smartcare_output_dir,
        "analysis_output_dir": analysis_output_dir,
        "history_file": history_file,
    }


def parse_args():
    defaults = default_paths()
    parser = argparse.ArgumentParser(description="Run SmartCare CEM then analysis and update history")
    parser.add_argument("--smartcare-script", default=str(defaults["smartcare_script"]))
    parser.add_argument("--analysis-script", default=str(defaults["analysis_script"]))
    parser.add_argument("--download-dir", default=str(defaults["download_dir"]))
    parser.add_argument("--smartcare-output-dir", default=str(defaults["smartcare_output_dir"]))
    parser.add_argument("--analysis-output-dir", default=str(defaults["analysis_output_dir"]))
    parser.add_argument("--history-file", default=str(defaults["history_file"]))
    parser.add_argument("--login-attempts", type=int, default=2)
    return parser.parse_args()


def run_smartcare(script_path: Path, download_dir: Path, output_dir: Path, login_attempts: int, logger: logging.Logger) -> int:
    env = os.environ.copy()
    env["SMARTCARE_DOWNLOAD_DIR"] = str(download_dir)
    env["SMARTCARE_OUTPUT_DIR"] = str(output_dir)
    env["SMARTCARE_LOGIN_ATTEMPTS"] = str(login_attempts)

    cmd = [
        sys.executable,
        str(script_path),
        "--download-dir",
        str(download_dir),
        "--output-dir",
        str(output_dir),
        "--login-attempts",
        str(login_attempts),
    ]
    result = subprocess.run(cmd, cwd=script_path.parent, env=env, capture_output=True, text=True)
    if result.stdout:
        logger.info(result.stdout.strip())
    if result.stderr:
        logger.error(result.stderr.strip())
    return result.returncode


def run_analysis(script_path: Path, source_dir: Path, output_dir: Path, history_file: Path, logger: logging.Logger) -> int:
    cmd = [
        sys.executable,
        str(script_path),
        "--source-dir",
        str(source_dir),
        "--output-dir",
        str(output_dir),
        "--history-file",
        str(history_file),
    ]
    result = subprocess.run(cmd, cwd=script_path.parent, env=os.environ.copy(), capture_output=True, text=True)
    if result.stdout:
        logger.info(result.stdout.strip())
    if result.stderr:
        logger.error(result.stderr.strip())
    return result.returncode


def main() -> int:
    args = parse_args()
    load_env_file(override=True)
    logger = setup_logger("smartcare-analysis-wrapper")

    download_dir = Path(args.download_dir).expanduser().resolve()
    smartcare_output_dir = Path(args.smartcare_output_dir).expanduser().resolve()
    analysis_output_dir = Path(args.analysis_output_dir).expanduser().resolve()
    history_file = Path(args.history_file).expanduser().resolve()

    download_dir.mkdir(parents=True, exist_ok=True)
    smartcare_output_dir.mkdir(parents=True, exist_ok=True)
    analysis_output_dir.mkdir(parents=True, exist_ok=True)
    history_file.parent.mkdir(parents=True, exist_ok=True)

    logger.info("Running SmartCare CEM...")
    rc = run_smartcare(Path(args.smartcare_script), download_dir, smartcare_output_dir, args.login_attempts, logger)
    if rc != 0:
        logger.error("SmartCare CEM failed with exit code %d", rc)
        return rc

    logger.info("SmartCare CEM completed. Running analysis...")
    rc = run_analysis(Path(args.analysis_script), smartcare_output_dir, analysis_output_dir, history_file, logger)
    if rc != 0:
        logger.error("Analysis failed with exit code %d", rc)
        return rc

    logger.info("SmartCare + analysis task completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

