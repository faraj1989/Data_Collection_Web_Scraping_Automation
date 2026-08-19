"""Offline smoke tests for configuration and report-discovery contracts."""
import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path

import pandas as pd
from project_config import parse_env_file


ROOT = Path(__file__).resolve().parents[1]


def load_module(filename, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ConfigurationSmokeTests(unittest.TestCase):
    def test_env_parser_handles_quoted_windows_path(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text('DATA_ROOT="C:\\\\Libyana Data"\nEMPTY=\n', encoding="utf-8")
            self.assertEqual(parse_env_file(env_file)["DATA_ROOT"], r"C:\Libyana Data")
            self.assertEqual(parse_env_file(env_file)["EMPTY"], "")

    def test_stable_entry_points_exist(self):
        for name in ("mae_scraper.py", "neteco_scraper.py", "merge_noc_reports.py",
                     "subscriber_reports.py", "ps_traffic_report.py"):
            self.assertTrue((ROOT / name).is_file(), name)


class AnalysisSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pipeline = load_module("download_analysis_pipeline.py", "analysis_pipeline_smoke")

    def test_discover_files_filters_supported_analysis_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "Comprehensive_Analysis_latest.csv").write_text("time,application,total traffic(byte)\n",
                                                                      encoding="utf-8")
            (base / "unrelated.csv").write_text("x\n", encoding="utf-8")
            self.assertEqual([p.name for p in self.pipeline.discover_files(base)],
                             ["Comprehensive_Analysis_latest.csv"])

    def test_safe_zip_extraction_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            archive_path = base / "bad.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../outside.txt", "unsafe")
            with zipfile.ZipFile(archive_path) as archive:
                with self.assertRaises(ValueError):
                    self.pipeline.safe_extract_zip(archive, base / "output")

    def test_report_metrics_are_generated_from_valid_input(self):
        frame = pd.DataFrame({
            "time": ["2026-08-01 01:00:00", "2026-08-01 02:00:00"],
            "application": ["Video", "Voice"],
            "total_traffic_byte": [1024 ** 3, 2 * 1024 ** 3],
            "tcp_connection_success_rate": ["99%", "98%"],
            "downlink_tcp_retransmission_rate": ["1%", "2%"],
            "average_tcp_packet_loss_rate": ["0.1%", "0.2%"],
            "downlink_tcp_packet_loss_rate": ["0.1%", "0.2%"],
            "tcp_connection_success_rate_included_rst": ["99%", "98%"],
        })
        top100 = self.pipeline.build_top100_traffic(frame)
        metrics = self.pipeline.build_rate_metrics(frame)
        self.assertEqual(len(top100), 2)
        self.assertEqual(metrics.loc[0, "total_traffic_gb"], 3)


if __name__ == "__main__":
    unittest.main()
