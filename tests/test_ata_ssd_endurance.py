"""Replaying SMART output verifies ATA wear without a physical disk."""
import ast
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SCRIPTS = Path(__file__).resolve().parents[1] / "AppImage/scripts"
sys.path.insert(0, str(SCRIPTS))
import disk_identity
import smartctl_resolver


def reader(endurance):
    path = SCRIPTS / "flask_server.py"
    tree = ast.parse(path.read_text())
    names = {"_get_smart_data_uncached", "_smart_default_payload",
             "_smart_payload_score", "_smart_probe_complete"}
    functions = ast.Module(body=[node for node in tree.body
                                 if isinstance(node, ast.FunctionDef) and node.name in names], type_ignores=[])
    context = dict(json=json, subprocess=subprocess, disk_identity=disk_identity, _smart_probe_cache={},
                   smartctl_probe_types=lambda name: ("sat",), is_disk_usb=lambda name: False,
                   _SMART_TIMEOUT=5, smartctl_command=smartctl_resolver.smartctl_command,
                   ata_endurance_used=endurance)
    exec(compile(functions, str(path), "exec"), context)
    return context["_get_smart_data_uncached"]


class AtaEnduranceTests(unittest.TestCase):
    def read(self, output, used):
        endurance = Mock(return_value=used)
        read = reader(endurance)
        process = Mock(returncode=0)
        process.communicate.return_value = (output, "")
        with patch.object(subprocess, "Popen", return_value=process):
            return read("sda"), endurance

    def test_ambiguous_attribute_prefers_standard_usage_in_json_and_text(self):
        json_report = json.dumps({
            "model_name": "WDC WDS240G2G0B-00EPW0", "serial_number": "test",
            "rotation_rate": 0, "ata_smart_attributes": {"table": [
                {"id": 230, "name": "Media_Wearout_Indicator", "value": 100},
            ]},
        })
        text_report = ("Device Model: WDC WDS240G2G0B-00EPW0\nSerial Number: test\n"
                       "ID# ATTRIBUTE_NAME FLAG VALUE WORST THRESH TYPE UPDATED WHEN_FAILED RAW_VALUE\n"
                       "230 Media_Wearout_Indicator 0x0032 100 100 000 Old_age Always - 0\n")
        for report in (json_report, text_report):
            for used, remaining in ((2, 98), (0, 100), (105, 0), (None, None)):
                with self.subTest(report=report, used=used):
                    result, probe = self.read(report, used)
                    self.assertEqual(result["ssd_life_left"], remaining)
                    self.assertEqual(result["media_wearout_indicator"], used)
                    probe.assert_called_once()
                    self.assertNotIn("_needs_ata_endurance", result)

    def test_explicit_life_attribute_keeps_its_existing_behavior(self):
        report = json.dumps({"ata_smart_attributes": {"table": [
            {"id": 231, "name": "SSD_Life_Left", "value": 93},
        ]}})
        data, probe = self.read(report, 50)
        self.assertEqual(data["ssd_life_left"], 93)
        probe.assert_not_called()

    def test_statistics_probe_reuses_the_successful_transport(self):
        command = ["smartctl", "-a", "-j", "-d", "sat", "/dev/sda"]
        for used in (0, 99, 105, None, True, -1, 256):
            with self.subTest(used=used), patch.object(subprocess, "run") as run:
                run.return_value = SimpleNamespace(stdout=json.dumps({"endurance_used": {"current_percent": used}}))
                actual = smartctl_resolver.ata_endurance_used(command)
                self.assertEqual(actual, used if type(used) is int and 0 <= used <= 255 else None)
                self.assertEqual(run.call_args.args[0], [
                    "smartctl", "-n", "standby", "-l", "devstat,7", "-j", "-d", "sat", "/dev/sda",
                ])
