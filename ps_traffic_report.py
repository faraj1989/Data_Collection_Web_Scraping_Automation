"""Stable entry point for PS traffic reporting."""
from pathlib import Path
import runpy

runpy.run_path(str(Path(__file__).parent / "PS Traffic per site" / "PS Traffic per site v3 .py"), run_name="__main__")
