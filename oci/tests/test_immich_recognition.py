"""The recognition of an installed Immich moves between the CPU and a GPU of
the host without reinstalling: the machine learning container takes the image
and the devices of the new choice."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))
sys.path.insert(0, str(ROOT / "src"))

import oci_immich_recognition as recognition
import oci_rocm_check

CONFIG = """arch: amd64
cores: 4
dev0: path=/dev/dri/renderD128,gid=993,mode=0660
dev1: path=/dev/kfd,gid=993,mode=0660
memory: 8192
lxc.environment.runtime: IMMICH_PORT=3003
lxc.environment.runtime: HSA_OVERRIDE_GFX_VERSION=10.3.0
lxc.environment.runtime: HSA_USE_SVM=0
lxc.environment: NVIDIA_VISIBLE_DEVICES=all
lxc.hook.mount: /usr/local/lib/proxmenux/oci/nvidia-mount-abc.sh
lxc.signal.halt: SIGTERM

[snapshot]
arch: amd64
lxc.environment.runtime: HSA_USE_SVM=0
"""


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "101.conf"
        self.path.write_text(CONFIG)
        patcher = patch.object(recognition, "conf", return_value=self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_what_the_previous_choice_left_is_taken_away(self):
        deleted = []
        with patch.object(recognition.oci_stack_modify, "entries",
                          return_value={"dev0": "path=/dev/dri/renderD128,gid=993", "dev1": "path=/dev/kfd,gid=993",
                                        "dev2": "path=/dev/ttyUSB0,gid=20"}), \
                patch.object(recognition, "run", side_effect=lambda *command: deleted.append(command[-1])):
            recognition.strip_gpu(101)
        self.assertEqual(deleted, ["dev0", "dev1"])
        text = self.path.read_text()
        current, _, snapshot = text.partition("\n[")
        for gone in ("HSA_OVERRIDE", "HSA_USE_SVM", "NVIDIA_VISIBLE_DEVICES", "nvidia-mount"):
            self.assertNotIn(gone, current)
        self.assertIn("lxc.environment.runtime: IMMICH_PORT=3003\n", current)
        self.assertIn("lxc.signal.halt: SIGTERM\n", current)
        # A snapshot is history: it is not rewritten.
        self.assertEqual(snapshot, CONFIG.partition("\n[")[2])

    def test_new_settings_go_before_the_snapshots(self):
        recognition.append_lines(101, ["lxc.environment.runtime: HSA_OVERRIDE_GFX_VERSION=11.0.0"])
        current, _, snapshot = self.path.read_text().partition("\n[")
        self.assertTrue(current.endswith("lxc.environment.runtime: HSA_OVERRIDE_GFX_VERSION=11.0.0\n"))
        self.assertEqual(snapshot, CONFIG.partition("\n[")[2])


class RecordTests(unittest.TestCase):
    RECORD = {"deployment": {"machine_learning": {
        "acceleration": "openvino", "render_device": "/dev/dri/renderD128", "model_cache_size_gb": 8,
        "resources": {"cores": 4, "memory_mb": 8192, "swap_mb": 1024, "cpu_allocation": "quota"}}}}

    def test_the_record_says_what_runs_recognition_and_with_what_resources(self):
        cpu = recognition.recorded(self.RECORD, "cpu", None, None)
        self.assertEqual((cpu["acceleration"], cpu["render_device"], cpu["gfx_override"]), ("cpu", None, None))
        self.assertEqual((cpu["resources"]["memory_mb"], cpu["resources"]["cpu_allocation"]), (4096, "cpuset"))
        self.assertEqual((cpu["model_cache_size_gb"], cpu["resources"]["swap_mb"]), (8, 1024))
        rocm = recognition.recorded(self.RECORD, "rocm", "/dev/dri/renderD129", "10.3.0")
        self.assertEqual((rocm["acceleration"], rocm["render_device"], rocm["gfx_override"]),
                         ("rocm", "/dev/dri/renderD129", "10.3.0"))
        self.assertEqual(rocm["resources"]["memory_mb"], 8192)
        self.assertEqual(recognition.recorded(self.RECORD, "openvino", "/dev/dri/renderD128", None)["resources"]
                         ["cpu_allocation"], "quota")
        # The record it was read from is not changed.
        self.assertEqual(self.RECORD["deployment"]["machine_learning"]["acceleration"], "openvino")

    def test_the_record_declares_the_variables_of_the_new_choice(self):
        base = [{"name": "IMMICH_PORT", "value": "3003"}]
        names = lambda found: [(entry["name"], entry["value"]) for entry in found]
        nvidia = recognition.declared(base, "cuda", None)
        self.assertEqual(names(nvidia), [("IMMICH_PORT", "3003"), ("NVIDIA_DRIVER_CAPABILITIES", "compute,utility")])
        amd = recognition.declared(nvidia, "rocm", "10.3.0")
        self.assertEqual(names(amd), [("IMMICH_PORT", "3003"), ("HSA_OVERRIDE_GFX_VERSION", "10.3.0"),
                                      ("HSA_USE_SVM", "0")])
        self.assertEqual(names(recognition.declared(nvidia, "rocm", None)), names(base))
        self.assertEqual(names(recognition.declared(amd, "cpu", None)), names(base))
        self.assertEqual(names(recognition.declared(amd, "openvino", None)), names(base))

    def test_the_record_declares_the_resources_of_the_new_choice(self):
        intel = {"cores": 4, "memory_mb": 8192, "swap_mb": 1024, "cpu_allocation": "quota"}
        self.assertEqual(recognition.resources(intel, "cpu"), {"cores": 4, "memory_mb": 4096, "swap_mb": 1024})
        self.assertEqual(recognition.resources(intel, "cuda"), {"cores": 4, "memory_mb": 8192, "swap_mb": 1024})
        self.assertEqual(recognition.resources(recognition.resources(intel, "cpu"), "openvino"), intel)
        self.assertEqual(intel["cpu_allocation"], "quota")

    def test_a_record_rebuilt_by_an_update_describes_the_new_container(self):
        def record(**plan):
            return {"vmid": 101, "template": {"proxmox": {"installer_profile": {"id": "ml", "cpu_allocation": "quota"}}},
                    "deployment": {"environment": [], "rootfs": {"storage": "local-lvm", "size_gb": 12},
                                   "resources": {"cores": 4, "memory_mb": 8192, "cpu_allocation": "quota"}, **plan}}

        with patch.object(recognition, "settings", return_value={"rootfs": "local-lvm:vm-101-disk-0,size=40G"}):
            rebuilt = record()
            recognition.declare(rebuilt, "rocm", "11.0.0")
            self.assertEqual(rebuilt["deployment"]["rootfs"]["size_gb"], 40)
            self.assertEqual(rebuilt["deployment"]["resources"], {"cores": 4, "memory_mb": 8192})
            self.assertEqual(rebuilt["template"]["proxmox"]["installer_profile"], {"id": "ml"})
            self.assertEqual([entry["name"] for entry in rebuilt["deployment"]["environment"]],
                             ["HSA_OVERRIDE_GFX_VERSION", "HSA_USE_SVM"])
            recognition.declare(rebuilt, "openvino", None)
            self.assertEqual(rebuilt["template"]["proxmox"]["installer_profile"]["cpu_allocation"], "quota")
            self.assertEqual(rebuilt["deployment"]["environment"], [])
            # A record still described by its native configuration is read from it.
            native = record(native_config="arch: amd64")
            recognition.declare(native, "rocm", "11.0.0")
            self.assertEqual(native, record(native_config="arch: amd64"))

    def test_a_choice_this_host_cannot_serve_is_refused_before_anything_changes(self):
        with self.assertRaises(ValueError):
            recognition.validate("vulkan", None, None)
        with self.assertRaises(ValueError):
            recognition.validate("rocm", "/dev/dri/renderD999", None)
        with self.assertRaises(ValueError):
            recognition.validate("openvino", "/etc/passwd", None)
        with self.assertRaises(ValueError):
            recognition.validate("cpu", None, "10.3.0")
        recognition.validate("cpu", None, None)

    def test_only_an_immich_of_proxmenux_is_changed(self):
        def member(vmid, adapter, role):
            return {"vmid": vmid, "deployment": {"replay_profile": {"adapter": adapter, "role": role}}}

        def records(roles, adapter="install_immich_stack.sh"):
            found = {vmid: member(vmid, adapter, role) for vmid, role in roles.items()}
            found[100]["stack"] = {"members": [{"vmid": vmid} for vmid in roles]}
            return found

        immich = records({100: "server", 101: "machine-learning", 102: "database", 103: "valkey"})
        with patch.object(recognition.instances, "read", side_effect=lambda root, vmid: immich[vmid]):
            _, found = recognition.members(Path("/nonexistent"), 100)
        self.assertEqual(found["machine-learning"]["vmid"], 101)
        for other in (records({100: "application", 101: "database"}, "install_tandoor_stack.sh"),
                      records({100: "server", 101: "machine-learning"})):
            with patch.object(recognition.instances, "read", side_effect=lambda root, vmid: other[vmid]):
                with self.assertRaises(ValueError):
                    recognition.members(Path("/nonexistent"), 100)


class RevertTests(unittest.TestCase):
    def test_the_previous_choice_is_what_the_record_says(self):
        record = {"deployment": {"machine_learning": {"acceleration": "rocm", "render_device": "/dev/dri/renderD128",
                                                      "gfx_override": "10.3.0"}}}
        self.assertEqual(recognition.chosen(record), ("rocm", "/dev/dri/renderD128", "10.3.0"))
        self.assertEqual(recognition.chosen({"deployment": {}}), ("cpu", None, None))

    def test_a_failed_change_puts_the_previous_choice_back_the_way_it_was_given(self):
        calls = []
        with patch.object(recognition.oci_stack_modify, "is_running", return_value=True), \
                patch.object(recognition, "stop", side_effect=lambda vmid: calls.append(("stop", vmid))), \
                patch.object(recognition, "apply", side_effect=lambda *arguments: calls.append(("apply",) + arguments[2:])), \
                patch.object(recognition.subprocess, "run", side_effect=lambda command, **_: calls.append(tuple(command[:3]))):
            recognition.revert(Path("/nonexistent"), 100, 101, {"cpu": "image"}, ("cpu", None, None), True)
        self.assertEqual(calls, [("stop", 101), ("apply", 101, {"cpu": "image"}, "cpu", None, None),
                                 ("pct", "start", "101")])

    def test_a_revert_that_fails_does_not_hide_the_first_error(self):
        with patch.object(recognition.oci_stack_modify, "is_running", return_value=False), \
                patch.object(recognition, "apply", side_effect=RuntimeError("pct set: locked")), \
                patch.object(recognition, "msg_warn") as warned, \
                patch.object(recognition.subprocess, "run") as started:
            recognition.revert(Path("/nonexistent"), 100, 101, {}, ("cpu", None, None), True)
        self.assertIn("pct set: locked", warned.call_args[0][0])
        started.assert_not_called()


class RocmProbeTests(unittest.TestCase):
    def test_the_probe_runs_with_what_the_container_tells_rocm(self):
        config = ("arch: amd64\nlxc.environment.runtime: PATH=/opt/venv/bin\n"
                  "lxc.environment.runtime: HSA_OVERRIDE_GFX_VERSION=10.3.0\nlxc.environment.runtime: HSA_USE_SVM=0\n"
                  "lxc.environment.runtime: HSA_BAD=1; reboot\n")
        self.assertEqual(oci_rocm_check.variables(config), ["HSA_OVERRIDE_GFX_VERSION=10.3.0", "HSA_USE_SVM=0"])
        self.assertEqual(oci_rocm_check.variables("arch: amd64\n"), [])
        listed = "arch: amd64\nenv: PATH=/opt/venv/bin\0HSA_OVERRIDE_GFX_VERSION=11.0.0\0HSA_USE_SVM=0\0HOME=/root\n"
        self.assertEqual(oci_rocm_check.variables(listed), ["HSA_OVERRIDE_GFX_VERSION=11.0.0", "HSA_USE_SVM=0"])


def protobuf_fields(data):
    """The fields of a protobuf message as (number, value) pairs."""
    position = 0

    def varint():
        nonlocal position
        value = shift = 0
        while True:
            byte = data[position]
            position += 1
            value |= (byte & 0x7F) << shift
            shift += 7
            if not byte & 0x80:
                return value

    while position < len(data):
        key = varint()
        number, wire = key >> 3, key & 7
        if wire == 0:
            yield number, varint()
        elif wire == 2:
            size = varint()
            yield number, data[position:position + size]
            position += size
        else:
            position += 4 if wire == 5 else 8


def packed_numbers(data):
    numbers, value, shift = [], 0, 0
    for byte in data:
        value |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            numbers.append(value)
            value = shift = 0
    return numbers


class RocmProbeModelTests(unittest.TestCase):
    def test_the_embedded_model_has_layers_that_fit_each_other(self):
        import base64
        model = base64.b64decode(oci_rocm_check.MODEL, validate=True)
        graph = next(value for number, value in protobuf_fields(model) if number == 7)
        shapes = {}
        for number, tensor in protobuf_fields(graph):
            if number != 5:
                continue
            dims, name = [], None
            for field, value in protobuf_fields(tensor):
                if field == 1:
                    dims += packed_numbers(value) if isinstance(value, bytes) else [value]
                elif field == 8:
                    name = value.decode()
            shapes[name] = dims
        # The dense layer takes one value per channel of the convolution.
        self.assertEqual(shapes["w"], [4, 3, 3, 3])
        self.assertEqual(shapes["fw"], [shapes["w"][0], 2])
        self.assertEqual((shapes["b"], shapes["fb"]), ([4], [2]))


class ChoicesTests(unittest.TestCase):
    def choices(self, found, blocker=None):
        from proxmenux_oci import stack_recreation
        with patch("proxmenux_oci.host.gpus", return_value=found), \
                patch("proxmenux_oci.host.rocm_blocker", return_value=blocker):
            return stack_recreation.recognition_choices("local-lvm")

    def test_the_choices_are_what_the_host_has(self):
        node = "/dev/dri/renderD128"
        tags = lambda found, blocker=None: [tag for tag, _, _ in self.choices(found, blocker)]
        self.assertEqual(tags({"intel": [], "amd": [], "nvidia": False}), ["cpu"])
        self.assertEqual(tags({"intel": [node], "amd": [], "nvidia": True}), ["cpu", "openvino", "cuda"])
        self.assertEqual(tags({"intel": [], "amd": [node], "nvidia": False, "amd_gfx_target": 100300}), ["cpu", "rocm"])
        self.assertEqual(tags({"intel": [], "amd": [node], "nvidia": False, "amd_gfx_target": 90012}, "generation"), ["cpu"])

    def test_an_amd_gpu_rocm_does_not_support_officially_is_marked(self):
        found = {"intel": [], "amd": ["/dev/dri/renderD128"], "nvidia": False, "amd_gfx_target": 100305}
        tag, label, details = self.choices(found)[-1]
        self.assertEqual(tag, "rocm")
        self.assertIn("experimental", label)
        self.assertEqual((details["experimental"], details["override"], details["render"]),
                         (True, "10.3.0", "/dev/dri/renderD128"))
        native = self.choices(dict(found, amd_gfx_target=110501))[-1]
        self.assertEqual((native[2]["experimental"], native[2]["override"]), (False, None))
        self.assertNotIn("experimental", native[1])


if __name__ == "__main__":
    unittest.main()
