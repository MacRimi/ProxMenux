#!/usr/bin/env python3
"""Run only the independently qualified, host-independent fixtures.

No filesystem discovery widens this manifest. Run from the repository root;
Python and Node have separate CI jobs so either failure blocks the check.
"""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

PYTHON_FILES = (
    "tests/test_lxc_update_jobs.py",
    "tests/test_post_install_i18n.py",
    "tests/test_remaining_cli_i18n.py",
    "AppImage/scripts/tests/test_pbs_i18n.py",
    "AppImage/scripts/tests/test_monitor_links_i18n.py",
    "AppImage/scripts/tests/test_monitor_links.py",
    "AppImage/scripts/tests/test_local_app_icon_isolation.py",
    "AppImage/scripts/tests/test_local_app_icons.py",
    "AppImage/scripts/tests/test_docker_app_discovery.py",
    "AppImage/scripts/tests/test_native_app_discovery.py",
    "tests/test_audit_presentation.py",
    "tests/test_audit_safety_wording.py",
    "tests/test_audit_policy.py",
    "tests/test_audit_report.py",
    "tests/test_audit_catalog.py",
    "tests/storage/test_nvme_status_message.py",
    "tests/test_fastfetch_config_generation.py",
    "tests/test_notification_active_payloads.py",
    "AppImage/scripts/tests/test_health_persistence_recurrence.py",
)
NODE_FILES = (
    "tests/test_lxc_update_jobs.cjs",
    "tests/test_api_import_boundaries.cjs",
    "tests/test_api_errors.cjs",
    "tests/test_optimization_labels.cjs",
    "tests/test_optimization_source.cjs",
    "tests/lxc_updates/test_app_editor_errors.cjs",
    "tests/test_oci_update_cancellation.cjs",
    "tests/test_host_backup_messages.cjs",
    "tests/test_pbs_i18n.cjs",
    "tests/test_monitor_links_i18n.cjs",
    "tests/lxc_updates/test_local_app_icons_ui.cjs",
    "tests/lxc_updates/test_docker_app_discovery_ui.cjs",
    "tests/lxc_updates/test_native_app_discovery_ui.cjs",
    "tests/lxc_updates/test_docker_delegated_ui.cjs",
    "tests/test_audit_diagnostic_document.cjs",
    "tests/test_audit_policy.cjs",
    "tests/test_audit_presentation.cjs",
    "tests/test_audit_safety_wording.cjs",
    "tests/test_audit_summary.cjs",
    "tests/test_backup_archives_empty.cjs",
    "tests/test_backup_destination_messages.cjs",
    "tests/test_borg_ssh_guidance.cjs",
    "tests/test_storage_messages.cjs",
    "tests/test_health_text.cjs",
    "tests/test_overview_chart_axis_gutters.cjs",
)

# unittest's CLI accepts a missing pattern as a successful zero-test run.
# Load the exact file in a fresh interpreter and reject zero tests and skips.
PYTHON_RUN = """import sys, unittest
folder, filename = sys.argv[1:]
suite = unittest.TestLoader().discover(start_dir=folder, pattern=filename)
count = suite.countTestCases()
if count == 0:
    raise SystemExit('No tests discovered: ' + folder + '/' + filename)
print('DISCOVERED=' + str(count), flush=True)
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() and result.testsRun == count and not result.skipped else 1)
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", required=True, choices=("python", "node"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    files = PYTHON_FILES if args.lane == "python" else NODE_FILES
    if not files or Path.cwd().resolve() != root:
        parser.error("nonempty manifest and repository-root working directory required")
    for path in files:
        if not (root / path).is_file():
            print(f"Missing qualified test: {path}", file=sys.stderr)
            return 1
    if args.lane == "node" and not (root / "AppImage/node_modules/typescript").is_dir():
        print("Install the locked offline-node dependencies first", file=sys.stderr)
        return 1
    for path in files:
        print(f"RUN {path}", flush=True)
        if args.lane == "python":
            folder, filename = str(Path(path).parent), Path(path).name
            command = [sys.executable, "-I", "-B", "-c", PYTHON_RUN, folder, filename]
            with tempfile.TemporaryDirectory(prefix="qualified-offline-") as scratch:
                environment = os.environ.copy()
                environment["TMPDIR"] = scratch
                result = subprocess.run(command, cwd=root, env=environment, check=False)
        else:
            command = ["node", path]
            result = subprocess.run(command, cwd=root, env=os.environ.copy(), check=False)
        if result.returncode != 0:
            print(f"FAIL {path}: exit {result.returncode}", file=sys.stderr)
            return 1
        print(f"PASS {path}", flush=True)
    print(f"PASS {args.lane}: {len(files)} qualified files", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
