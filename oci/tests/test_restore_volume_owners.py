"""A restore formats the managed volumes again, and Proxmox gives the root of
each one to the root of the container while everything inside keeps its owner.
The roots the recipe prepares get back the owner the installation gave them."""

import contextlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "remote"), str(ROOT / "src")]

import oci_instance_transaction as transaction  # noqa: E402
import oci_restore_recovery as recovery  # noqa: E402

TEMPLATE = {"proxmox": {"installer_profile": {"volume_preparations": [
    {"container_path": "/data", "owner_strategy": "mapped-application-user",
     "only_when_mount_type": "managed-volume"},
    {"container_path": "/config", "owner_strategy": "mapped-root", "mode": "0750"},
    {"container_path": "/media", "owner_strategy": "mapped-application-user"},
    {"container_path": "/models", "owner_strategy": "mapped-application-user"},
]}}}
DEPLOYMENT = {"security": {"unprivileged": True}, "environment": [], "mounts": [
    {"type": "managed-volume", "container_path": "/data", "backup": True},
    {"type": "managed-volume", "container_path": "/config", "backup": True},
    {"type": "host-bind", "container_path": "/media", "source": "/mnt/media"},
    {"type": "managed-volume", "container_path": "/models", "backup": True, "read_only": True},
]}
CONFIG = b"arch: amd64\nlxc.init.uid: 10001\nlxc.init.gid: 999\n"


class RestoreVolumeOwnersTests(unittest.TestCase):
    def run_on(self, deployment=DEPLOYMENT, template=TEMPLATE, config=CONFIG):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("data", "config", "media", "models"):
                (root / name).mkdir()
            with patch.object(transaction.os, "chown") as chown, patch.object(transaction.os, "chmod") as chmod:
                transaction.restore_volume_owners(root, deployment, template, config)
            resolved = root.resolve()
            owners = {str(c.args[0].relative_to(resolved)): c.args[1:3] for c in chown.call_args_list}
            modes = {str(c.args[0].relative_to(resolved)): c.args[1] for c in chmod.call_args_list}
            return owners, modes

    def test_the_application_and_root_volumes_get_their_owner_back(self):
        owners, modes = self.run_on()
        self.assertEqual(owners["data"], (110001, 100999))
        self.assertEqual(owners["config"], (100000, 100000))
        self.assertEqual(modes, {"config": 0o750})

    def test_host_directories_and_read_only_volumes_are_left_alone(self):
        owners, _ = self.run_on()
        self.assertNotIn("media", owners)
        self.assertNotIn("models", owners)

    def test_puid_and_volume_owner_decide_as_in_the_installation(self):
        deployment = dict(DEPLOYMENT, environment=[{"name": "PUID", "value": "1000"}, {"name": "PGID", "value": "1000"}])
        self.assertEqual(self.run_on(deployment)[0]["data"], (101000, 101000))
        template = {"proxmox": {"installer_profile": dict(TEMPLATE["proxmox"]["installer_profile"],
                                                          volume_owner={"uid": 1000, "gid": 1000})}}
        self.assertEqual(self.run_on(template=template)[0]["data"], (101000, 101000))

    def test_a_privileged_container_uses_the_ids_as_they_are(self):
        deployment = dict(DEPLOYMENT, security={"unprivileged": False})
        self.assertEqual(self.run_on(deployment)[0]["data"], (10001, 999))

    def test_a_recipe_without_preparations_changes_nothing(self):
        self.assertEqual(self.run_on(template={"proxmox": {"installer_profile": {}}}), ({}, {}))

    def test_a_symlink_never_leads_outside_the_container(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            (root / "data").symlink_to(outside)
            with patch.object(transaction.os, "chown") as chown:
                transaction.restore_volume_owners(root, DEPLOYMENT, TEMPLATE, CONFIG)
            self.assertNotIn(Path(outside).resolve(), [c.args[0] for c in chown.call_args_list])


class RecoveryCallersTests(unittest.TestCase):
    def test_a_rolled_back_update_restores_the_owners_with_its_recipe(self):
        with patch.object(transaction, "owned", return_value=CONFIG), patch.object(transaction, "run"), \
                patch.object(transaction, "remove_empty_format_directories"), \
                patch.object(transaction, "restore_volume_owners") as owners:
            transaction.cleanup_restored_format_dirs(1000, DEPLOYMENT, "identity", TEMPLATE)
        rootfs, deployment, template, config = owners.call_args.args
        self.assertEqual((deployment, template, config), (DEPLOYMENT, TEMPLATE, CONFIG))
        self.assertEqual(Path(rootfs).parts[-2:], ("1000", "rootfs"))

    def test_a_backup_adopted_in_oci_manage_uses_the_carried_recipe(self):
        entry = {"vmid": 1000, "config": "mp0: local-lvm:vm-1000-disk-1,mp=/data,backup=1\n",
                 "copy": {"record": {"deployment": DEPLOYMENT, "template": TEMPLATE}}}
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(recovery.carried, "container_root", return_value=contextlib.nullcontext(Path(tmp))), \
                patch.object(recovery.transaction, "remove_empty_format_directories"), \
                patch.object(recovery.transaction, "restore_volume_owners") as owners:
            recovery.clean_format_directories(entry)
        self.assertEqual(owners.call_args.args[1:3], (DEPLOYMENT, TEMPLATE))


if __name__ == "__main__":
    unittest.main()
