"""Stable entry point for the MAE current-alarm scraper."""
from pathlib import Path
import runpy

runpy.run_path(str(Path(__file__).with_name("mae_scraper_newerBrowserversion149.py")), run_name="__main__")
