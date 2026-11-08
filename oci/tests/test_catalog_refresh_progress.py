"""Refreshing the catalog reports its steps, and the menu shows them as a progress bar."""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_catalog_refresh as base  # noqa: E402
from proxmenux_oci import catalog_refresh as refresh  # noqa: E402
from proxmenux_oci.catalog import Catalog  # noqa: E402
from proxmenux_oci.ui import TerminalUI  # noqa: E402


class CatalogRefreshProgress(unittest.TestCase):
    setUp = base.CatalogRefreshTests.setUp
    fetch = base.CatalogRefreshTests.fetch

    def test_a_download_reports_every_step_in_order_up_to_the_last_file(self):
        steps = []
        refresh.synchronize(self.root, "main", self.fetch,
                            progress=lambda percent, message, **values: steps.append((percent, message, values)))
        percents = [step[0] for step in steps]
        self.assertEqual(percents, sorted(percents))
        self.assertEqual((percents[0], percents[-1]), (5, 95))
        downloads = [values for _, message, values in steps if message.startswith("Downloading")]
        self.assertEqual(downloads[-1], {"done": len(self.files), "total": len(self.files)})

    def test_the_worker_writes_the_step_and_the_menu_reads_it_translated(self):
        synchronize = refresh.synchronize
        offline = lambda root, channel, force=False, progress=None: synchronize(
            root, channel, self.fetch, force=force, progress=progress)
        with patch.object(refresh, "synchronize", offline):
            refresh.worker(self.root, "main")
        self.assertTrue(refresh.read_json(refresh.cache_root(self.root) / "main-result.json")["ok"])
        percent, text = refresh.read_progress(self.root, "main")
        self.assertEqual(percent, 95)
        self.assertEqual(text, "Applying the new catalog...")
        refresh.write_json(refresh.progress_path(self.root, "main"),
                           {"percent": 40, "message": "Downloading the catalog files ({done}/{total})...",
                            "values": {"done": 3, "total": 7}})
        self.assertEqual(refresh.read_progress(self.root, "main"), (40, "Downloading the catalog files (3/7)..."))

    def test_a_new_refresh_starts_at_zero_and_stops_reporting_once_finished(self):
        refresh.write_json(refresh.progress_path(self.root, "main"), {"percent": 95, "message": "old", "values": {}})
        status = refresh.CatalogRefresh(self.root, Catalog(self.root))
        process = Mock(); process.poll.return_value = None
        with patch.object(refresh.subprocess, "Popen", return_value=process):
            status.start(force=True)
        self.assertEqual(status.progress()[0], 0)
        process.poll.return_value = 0
        self.assertIsNone(status.progress())


class TerminalGauge(unittest.TestCase):
    def test_each_new_step_is_printed_once(self):
        states = iter([(0, "Start"), (0, "Start"), (50, "Half"), None])
        output = io.StringIO()
        with redirect_stdout(output), patch("proxmenux_oci.ui.time.sleep"):
            TerminalUI().gauge(lambda: next(states))
        self.assertEqual(output.getvalue().splitlines(), ["[  0%] Start", "[ 50%] Half"])


if __name__ == "__main__":
    unittest.main()
