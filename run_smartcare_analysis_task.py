import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

from project_config import load_env_file
from project_logging import setup_logger


def default_paths() -> dict:
    load_env_file()
    project_root = Path(__file__).resolve().parent
    download_dir = Path(os.getenv("SMARTCARE_DOWNLOAD_DIR", str(Path.home() / "Downloads"))).expanduser()
    smartcare_output_dir = Path(
        os.getenv("SMARTCARE_OUTPUT_DIR", str(Path.home() / "Downloads" / "SmartCare_Exports"))).expanduser()
    analysis_output_dir = Path(
        os.getenv("ANALYSIS_OUTPUT_DIR", str(Path.home() / "Downloads" / "Processed_Analysis"))).expanduser()
    history_file = Path(os.getenv("ANALYSIS_HISTORY_FILE",
                                  str(analysis_output_dir / "Comprehensive_Analysis_Historical.xlsx"))).expanduser()

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


def run_smartcare(script_path: Path, download_dir: Path, output_dir: Path, login_attempts: int,
                  logger: logging.Logger) -> int:
    """Run SmartCare CEM script with proper error handling."""

    # ========== FIX: Validate script path ==========
    if not script_path.exists():
        logger.error(f"❌ SmartCare script not found: {script_path}")
        logger.info(f"   Looking for script at: {script_path}")
        logger.info(f"   Project root: {script_path.parent}")
        return 1

    # Ensure the script's parent directory exists
    if not script_path.parent.exists():
        logger.error(f"❌ Script directory does not exist: {script_path.parent}")
        return 1

    env = os.environ.copy()
    env["SMARTCARE_DOWNLOAD_DIR"] = str(download_dir)
    env["SMARTCARE_OUTPUT_DIR"] = str(output_dir)
    env["SMARTCARE_LOGIN_ATTEMPTS"] = str(login_attempts)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    cmd = [sys.executable, str(script_path), "--download-dir", str(download_dir),
           "--output-dir", str(output_dir), "--login-attempts", str(login_attempts)]

    logger.info(f"📂 Working directory: {script_path.parent}")
    logger.info(f"📄 Script: {script_path.name}")
    logger.info(f"🚀 Running command: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            cwd=str(script_path.parent),  # FIX: Convert to string
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.stdout:
            logger.info(result.stdout.strip())
        if result.stderr:
            logger.error(result.stderr.strip())
        return result.returncode
    except FileNotFoundError as e:
        logger.error(f"❌ File not found: {e}")
        logger.info(f"   Check that Python executable exists: {sys.executable}")
        return 1
    except PermissionError as e:
        logger.error(f"❌ Permission denied: {e}")
        return 1
    except Exception as e:
        logger.error(f"❌ Unexpected error running SmartCare: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return 1


def run_analysis(script_path: Path, source_dir: Path, output_dir: Path, history_file: Path,
                 logger: logging.Logger) -> int:
    """Run analysis script with proper error handling."""

    # ========== FIX: Validate script path ==========
    if not script_path.exists():
        logger.error(f"❌ Analysis script not found: {script_path}")
        logger.info(f"   Looking for script at: {script_path}")
        return 1

    # Ensure the script's parent directory exists
    if not script_path.parent.exists():
        logger.error(f"❌ Script directory does not exist: {script_path.parent}")
        return 1

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

    logger.info(f"📂 Working directory: {script_path.parent}")
    logger.info(f"📄 Script: {script_path.name}")
    logger.info(f"🚀 Running command: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            cwd=str(script_path.parent),  # FIX: Convert to string
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.stdout:
            logger.info(result.stdout.strip())
        if result.stderr:
            logger.error(result.stderr.strip())
        return result.returncode
    except FileNotFoundError as e:
        logger.error(f"❌ File not found: {e}")
        return 1
    except PermissionError as e:
        logger.error(f"❌ Permission denied: {e}")
        return 1
    except Exception as e:
        logger.error(f"❌ Unexpected error running analysis: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return 1


def main() -> int:
    args = parse_args()
    load_env_file(override=True)
    logger = setup_logger("smartcare-analysis-wrapper")

    # ========== FIX: Convert paths and log them ==========
    download_dir = Path(args.download_dir).expanduser().resolve()
    smartcare_output_dir = Path(args.smartcare_output_dir).expanduser().resolve()
    analysis_output_dir = Path(args.analysis_output_dir).expanduser().resolve()
    history_file = Path(args.history_file).expanduser().resolve()

    smartcare_script = Path(args.smartcare_script).expanduser().resolve()
    analysis_script = Path(args.analysis_script).expanduser().resolve()

    # Log all paths for debugging
    logger.info("=" * 60)
    logger.info("📁 Path Configuration:")
    logger.info(f"   SmartCare Script: {smartcare_script}")
    logger.info(f"   Analysis Script: {analysis_script}")
    logger.info(f"   Download Dir: {download_dir}")
    logger.info(f"   SmartCare Output: {smartcare_output_dir}")
    logger.info(f"   Analysis Output: {analysis_output_dir}")
    logger.info(f"   History File: {history_file}")
    logger.info("=" * 60)

    # Create all directories
    try:
        download_dir.mkdir(parents=True, exist_ok=True)
        smartcare_output_dir.mkdir(parents=True, exist_ok=True)
        analysis_output_dir.mkdir(parents=True, exist_ok=True)
        history_file.parent.mkdir(parents=True, exist_ok=True)
        logger.info("✅ All directories created/verified")
    except Exception as e:
        logger.error(f"❌ Failed to create directories: {e}")
        return 1

    # ========== FIX: Check if scripts exist ==========
    if not smartcare_script.exists():
        logger.error(f"❌ SmartCare script not found: {smartcare_script}")
        logger.info("   Please check the path in Script Paths settings")
        return 1

    if not analysis_script.exists():
        logger.error(f"❌ Analysis script not found: {analysis_script}")
        logger.info("   Please check the path in Script Paths settings")
        return 1

    # Run SmartCare
    logger.info("🚀 Running SmartCare CEM...")
    rc = run_smartcare(smartcare_script, download_dir, smartcare_output_dir, args.login_attempts, logger)
    if rc != 0:
        logger.error("❌ SmartCare CEM failed with exit code %d", rc)
        return rc

    logger.info("✅ SmartCare CEM completed successfully.")

    # Run Analysis
    logger.info("🚀 Running analysis...")
    rc = run_analysis(analysis_script, smartcare_output_dir, analysis_output_dir, history_file, logger)
    if rc != 0:
        logger.error("❌ Analysis failed with exit code %d", rc)
        return rc

    logger.info("✅ SmartCare + analysis task completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
