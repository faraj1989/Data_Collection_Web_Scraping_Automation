"""Stable entry point for the NetEco current-alarm scraper."""
from pathlib import Path
import runpy

runpy.run_path(str(Path(__file__).with_name("neteco_continuous 15-5-2026.py")), run_name="__main__")
