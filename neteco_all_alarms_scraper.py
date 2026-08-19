"""Stable entry point for the NetEco all-alarms scraper."""
from pathlib import Path
import runpy

runpy.run_path(str(Path(__file__).with_name("neteco_continuous all alrams.py")), run_name="__main__")
