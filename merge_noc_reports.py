"""Stable entry point for the NOC report merger."""
from pathlib import Path
import runpy

runpy.run_path(str(Path(__file__).with_name("Processing & Merging Script 31-5 with sharing.py")), run_name="__main__")
