"""The menus that install drivers inside a container leave out the ones
created from an OCI image: those are changed from OCI manager Apps."""
from pathlib import Path
import re
import subprocess
import tempfile
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[3]
MENUS = ('scripts/gpu_tpu/add_gpu_lxc.sh', 'scripts/gpu_tpu/install_coral_lxc.sh')
ORDINARY = "arch: amd64\ncores: 2\nhostname: debian\nostype: debian\nrootfs: local-lvm:vm-111-disk-0,size=8G\n"
OCI = ORDINARY + "entrypoint: /init\nlxc.signal.halt: SIGTERM\n"


def function(path, name):
    source = (ROOT / path).read_text()
    return re.search(rf'^{name}\(\) \{{\n.*?^\}}\n', source, re.MULTILINE | re.DOTALL)[0]


class GpuMenusHideOci(TestCase):
    def is_oci(self, config):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / '111.conf').write_text(config)
            helper = function('scripts/utils.sh', 'pmx_lxc_is_oci').replace('/etc/pve/lxc', folder)
            return subprocess.run(['bash', '-c', helper + 'pmx_lxc_is_oci 111'], capture_output=True).returncode == 0

    def test_a_container_from_an_oci_image_is_told_apart_by_its_configuration(self):
        self.assertTrue(self.is_oci(OCI))
        self.assertTrue(self.is_oci(ORDINARY + "cmd: nginx -g 'daemon off;'\n"))
        self.assertFalse(self.is_oci(ORDINARY))
        # A setting that only mentions the word is not an entrypoint.
        self.assertFalse(self.is_oci(ORDINARY + "description: entrypoint: none\n"))

    def test_a_container_without_configuration_is_not_one(self):
        with tempfile.TemporaryDirectory() as folder:
            helper = function('scripts/utils.sh', 'pmx_lxc_is_oci').replace('/etc/pve/lxc', folder)
            self.assertNotEqual(subprocess.run(['bash', '-c', helper + 'pmx_lxc_is_oci 999'],
                                               capture_output=True).returncode, 0)

    def test_both_menus_skip_them_and_say_so(self):
        for menu in MENUS:
            body = function(menu, 'select_container')
            self.assertLess(body.index('pmx_lxc_is_oci "$ctid"'), body.index('menu_items+=('), menu)
            self.assertIn('Containers created from an OCI image are not listed:', body, menu)
            self.assertEqual(body.count('${oci_note}'), 2, menu)


SWITCHES = (('scripts/gpu_tpu/switch_gpu_mode.sh', 'apply_lxc_action_for_vm_mode', 'prompt_lxc_action_for_vm_mode'),
            ('scripts/gpu_tpu/switch_gpu_mode_direct.sh', 'apply_lxc_action_for_vm_mode', 'prompt_lxc_action_for_vm_mode'),
            ('scripts/gpu_tpu/add_gpu_vm.sh', 'cleanup_lxc_configs', None))


class GpuToVmKeepsOciConfiguration(TestCase):
    """A GPU that moves to a VM stops the containers that use it. One created
    from an OCI image keeps its configuration, which OCI manager Apps records."""

    def test_an_oci_container_is_never_edited(self):
        for script, apply, _ in SWITCHES:
            body = function(script, apply)
            guard = body.index('pmx_lxc_is_oci "$ctid"')
            self.assertLess(guard, body.index('action="keep_gpu_disable_onboot"'), script)
            removal = body.index('"$action" == "remove_gpu_keep_onboot"')
            self.assertLess(guard, removal, script)
            # The only edit of a configuration hangs from the per-container action.
            self.assertEqual(len(re.findall(r'_from_lxc_conf "\$', body)), 1, script)
            edit = body.index('_from_lxc_conf "$')
            condition = body.rindex('if [[', 0, edit)
            self.assertIn('"$action" == "remove_gpu_keep_onboot"', body[condition:edit], script)

    def test_the_list_names_them_and_nothing_is_asked_when_all_are_oci(self):
        for script, _, prompt in SWITCHES:
            source = (ROOT / script).read_text() if prompt is None else function(script, prompt)
            self.assertIn('", OCI"', source, script)
            self.assertIn('OCI containers keep their configuration', source, script)
            self.assertIn('"$oci_count" -eq ${#LXC_AFFECTED_CTIDS[@]}', source, script)


class DiskAndSharePickersHideOci(TestCase):
    """Adding a disk or a mount, and the NFS and Samba set-ups, change the
    container they are given. A container from an OCI image is not offered."""

    def test_every_picker_filters_before_it_lists(self):
        pickers = ((function('scripts/global/share-common.func', 'select_lxc_container'), 'options+=('),
                   (function('scripts/global/share-common.func', 'select_privileged_lxc'), 'ct_list+='),
                   (function('scripts/share/lxc-mount-manager_minimal.sh', 'select_lxc_container'), 'options+=('))
        for body, listing in pickers:
            self.assertLess(body.index('pmx_lxc_is_oci "$id"'), body.index(listing))
            self.assertIn('Containers created from an OCI image are not listed', body)
        disk = (ROOT / 'scripts/storage/disk-passthrough_ct.sh').read_text()
        picker = disk[disk.index('CT_LIST=""'):disk.index('if [ -z "$CTID" ]')]
        self.assertLess(picker.index('pmx_lxc_is_oci "$ct_id"'), picker.index('CT_LIST+='))
        self.assertIn('${OCI_NOTE}" $UI_MENU_H $UI_MENU_W $CT_LIST_H', picker)

    def test_a_disk_in_use_is_still_looked_for_in_every_container(self):
        for script in ('scripts/storage/disk-passthrough_ct.sh', 'scripts/storage/disk-passthrough.sh'):
            source = (ROOT / script).read_text()
            check = source[source.index('disk_referenced_in_config "$CT_CONFIG_RAW" "$DISK"'):]
            scan = check[:check.index("done < <(pct list | awk 'NR>1 {print $1, $3}')")]
            self.assertNotIn('pmx_lxc_is_oci', scan, script)
