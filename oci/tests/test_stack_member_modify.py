"""Every container of every stack can be modified: resources, variables, paths
and devices, and what an adapter derives from them follows."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "remote"))

import oci_immich_recognition as recognition
import oci_stack_modify as stack_modify
from proxmenux_oci import stack_recreation

APPLICATION = {"vmid": 129, "stack_member": {"name": "server"},
               "deployment": {"replay_profile": {"adapter": "install_immich_stack.sh", "role": "server"},
                              "environment": [{"name": "DB_PASSWORD", "value": "s3cret", "sensitive": True}]}}
DATABASE = {"vmid": 130, "stack_member": {"name": "database"},
            "deployment": {"replay_profile": {"adapter": "install_immich_stack.sh", "role": "database"}}}
LEARNING = {"vmid": 131, "stack_member": {"name": "immich-machine-learning"},
            "deployment": {"replay_profile": {"adapter": "install_immich_stack.sh", "role": "machine-learning"}}}
PRIMARY = {"vmid": 129, "stack": {"members": [DATABASE, APPLICATION, LEARNING]}}


def record(role="server", defaults=()):
    return {"deployment": {"replay_profile": {"adapter": "install_immich_stack.sh", "role": role}},
            "observed": {"image": {"defaults": {"Env": list(defaults)}}}}


class EngineSettingsTests(unittest.TestCase):
    def test_resources_become_proxmox_settings(self):
        values = stack_modify.settings_values(record("database"), b"cores: 2\nmemory: 2048\n",
                                              {"resources": {"cores": 4, "memory_mb": 6144, "swap_mb": 0}})
        self.assertEqual(values, {"cores": 4, "memory": 6144, "swap": 0})

    def test_a_container_limited_by_cpu_time_keeps_that_kind_of_limit(self):
        values = stack_modify.settings_values(record("machine-learning"), b"cpulimit: 4\nmemory: 4096\n",
                                              {"resources": {"cores": 2}})
        self.assertEqual(values, {"cpulimit": 2})

    def test_immich_server_cpu_cores_follow_its_cores(self):
        values = stack_modify.settings_values(record(), b"cores: 4\nenv: CPU_CORES=4\0TZ=UTC\n",
                                              {"resources": {"cores": 2}})
        self.assertEqual(values["cores"], 2)
        self.assertEqual(sorted(values["env"].split("\0")), ["CPU_CORES=2", "TZ=UTC"])

    def test_a_removed_variable_the_image_defines_comes_back_with_its_value(self):
        values = stack_modify.settings_values(record("database", ["LANG=C.UTF-8"]),
                                              b"env: LANG=es_ES.UTF-8\0EXTRA=1\n",
                                              {"environment": {"set": {"TZ": "Europe/Madrid"},
                                                               "unset": ["LANG", "EXTRA"]}})
        self.assertEqual(sorted(values["env"].split("\0")), ["LANG=C.UTF-8", "TZ=Europe/Madrid"])

    def test_invalid_values_are_refused_before_anything_changes(self):
        for changes in ({"resources": {"cores": 0}}, {"resources": {"memory_mb": "4096"}},
                        {"resources": {"disk": 8}}, {"environment": {"set": {"BAD NAME": "x"}}},
                        {"environment": {"set": {"A": "line\nbreak"}}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                stack_modify.validate_settings(changes)

    def test_a_change_without_settings_is_still_valid(self):
        stack_modify.validate_settings({"remove_mounts": []})
        self.assertEqual(stack_modify.settings_values(record(), b"cores: 2\n", {"add_mounts": []}), {})


class RecognitionMemoryTests(unittest.TestCase):
    def test_the_ram_a_choice_set_follows_the_new_choice(self):
        self.assertEqual(recognition.memory("cuda", 4096, "cpu"), 8192)
        self.assertEqual(recognition.memory("cpu", 8192, "cuda"), 4096)

    def test_the_ram_the_user_set_is_never_lowered(self):
        self.assertEqual(recognition.memory("cpu", 12000, "cuda"), 12000)
        self.assertEqual(recognition.memory("cuda", 16384, "cpu"), 16384)
        # Less than the new choice needs: the choice still gets what it needs.
        self.assertEqual(recognition.memory("cuda", 6000, "cpu"), 8192)

    def test_without_a_current_value_the_choice_decides(self):
        self.assertEqual(recognition.memory("cpu"), 4096)
        self.assertEqual(recognition.memory("openvino"), 8192)


class ScriptedUI:
    def __init__(self, choices=(), answers=()):
        self.choices, self.answers, self.asked = list(choices), dict(answers), []

    def choose(self, text, options, default=None, **_):
        self.asked.append((text, [tag for tag, _label in options], default))
        return self.choices.pop(0)

    def ask(self, prompt, default=None, required=True, title=None):
        return self.answers.get(prompt, default)

    def review(self, *args, **kwargs):
        return True

    def message(self, *args, **kwargs):
        raise AssertionError(args)


@patch("proxmenux_oci.i18n.language", return_value="en")
@patch.object(stack_recreation, "current_resources",
              return_value={"cores": 2, "memory_mb": 2048, "swap_mb": 512})
class ConsoleModifyTests(unittest.TestCase):
    def run_modify(self, ui, member_vmid=None):
        sent = {}

        def lifecycle(command, title):
            sent["vmid"] = int(command[2])
            sent["changes"] = json.loads(Path(command[4]).read_text())
            return True

        self.assertTrue(stack_recreation.modify_stack(Path("/engine"), ui, PRIMARY, lifecycle, member_vmid))
        return sent

    def test_every_member_is_offered_with_the_application_first(self, *_):
        ui = ScriptedUI(["130", "resources"], {"RAM in MiB": "4096"})
        sent = self.run_modify(ui)
        text, tags, default = ui.asked[0]
        self.assertEqual((tags, default), (["129", "130", "131"], "129"))
        self.assertEqual(sent, {"vmid": 130, "changes": {**sent["changes"], "resources": {"memory_mb": 4096}}})

    def test_a_member_opened_directly_skips_the_choice_of_container(self, *_):
        ui = ScriptedUI(["resources"], {"Cores": "3"})
        sent = self.run_modify(ui, member_vmid=131)
        self.assertEqual(sent["vmid"], 131)
        self.assertEqual(sent["changes"]["resources"], {"cores": 3})
        self.assertIn("recognition", ui.asked[0][1])

    def test_recognition_is_offered_only_on_the_machine_learning_container(self, *_):
        ui = ScriptedUI(["resources"], {"Swap in MiB": "0"})
        self.run_modify(ui, member_vmid=130)
        self.assertNotIn("recognition", ui.asked[0][1])


if __name__ == "__main__":
    unittest.main()
