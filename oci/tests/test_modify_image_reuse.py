"""Unchanged OCI images permit native resource edits or verified local reuse."""
import copy
import hashlib
import json
from pathlib import Path
import re
import stat
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'remote'))
import oci_carried_record
import oci_instances as instances
import oci_resource_modify as resources
import oci_update_current as update

DIGEST = 'sha256:'+'a'*64
NEW = 'sha256:'+'b'*64
IDENTITY = '11111111-1111-4111-8111-111111111111'
CONFIG = (f'arch: amd64\ncores: 2\ndescription: proxmenux-instance={IDENTITY}\n'
          'memory: 512\nrootfs: local-zfs:subvol-115-disk-0,size=8G\n'
          'lxc.environment.runtime: A=one\nlxc.environment.runtime: B=two\n').encode()


def record():
    return {'schema_version': 1, 'vmid': 115, 'installation_id': IDENTITY, 'status': 'installed',
            'template': {'id': 'example-app', 'catalog_ui': {'title': 'Example'},
                'container_contract': {'image': {'reference': 'example/app:latest'}},
                'proxmox': {'installer_profile': {'startup_healthcheck': {'type': 'running'}}}},
            'deployment': {'vmid': 115, 'hostname': 'example', 'template_storage': 'local',
                'resources': {'cores': 2, 'memory_mb': 512, 'swap_mb': 512},
                'network': {'bridge': 'vmbr0', 'ipv4': 'dhcp'}, 'mounts': [], 'devices': [],
                'environment': [{'name': 'PASSWORD', 'value': 'private-test-value', 'sensitive': True}]},
            'observed': {'config': CONFIG.decode(), 'config_sha256': resources.sha(CONFIG),
                'image': {'manifest_digest': DIGEST, 'architecture': 'amd64', 'os': 'linux'},
                'resolved_registry_digest': DIGEST, 'archive_path': '/missing/deleted-image.tar'}}


class ResourceModifyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'instances'
        self.configs = Path(self.temp.name)/'configs'
        self.configs.mkdir()
        self.file = self.configs/'115.conf'
        self.file.write_bytes(CONFIG)
        self.saved = record()
        self.candidate = copy.deepcopy(self.saved)
        self.candidate['deployment']['resources'].update(cores=3, memory_mb=768)
        self.params = {'cores': '3', 'memory': '768'}
        instances.write(instances.location(self.root, 115), self.saved)
        self.calls = []
        self.native_failure = None
        def run(*args):
            self.calls.append(args)
            self.assertEqual(args[:3], ('pct', 'set', '115'))
            expected = args[args.index('--digest')+1]
            self.assertEqual(expected, hashlib.sha1(self.file.read_bytes()).hexdigest())
            if self.native_failure:
                raise self.native_failure
            text = self.file.read_text()
            for index in range(5, len(args), 2):
                text = re.sub(r'^'+args[index][2:]+r': .*$', args[index][2:]+': '+args[index+1], text, flags=re.M)
            self.file.write_text(text)
            return b''
        def observe(*args):
            result = copy.deepcopy(self.saved['observed'])
            result.update(config=self.file.read_text(), config_sha256=resources.sha(self.file.read_bytes()))
            return result
        patches = [patch.object(resources, 'CONFIG_DIR', self.configs),
            patch.object(instances, 'command', side_effect=lambda *args: self.file.read_bytes()),
            patch.object(resources.transaction, 'run', side_effect=run),
            patch.object(resources.transaction, 'open_log'), patch.object(resources.transaction, 'log'),
            patch.object(instances, 'observe', side_effect=observe),
            patch.object(oci_carried_record, 'carry', return_value='carried')]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def apply(self):
        return resources.apply(self.root, self.saved, self.candidate, CONFIG, self.params)

    def test_resource_only_change_needs_no_archive_and_preserves_every_other_field(self):
        directory = self.apply()
        after = instances.read(self.root, 115)
        self.assertEqual(after['deployment']['resources'], {'cores': 3, 'memory_mb': 768, 'swap_mb': 512})
        for key in ('network', 'mounts', 'devices', 'environment'):
            self.assertEqual(after['deployment'][key], self.saved['deployment'][key])
        self.assertEqual(after['observed']['image'], self.saved['observed']['image'])
        self.assertEqual(after['observed']['archive_path'], '/missing/deleted-image.tar')
        self.assertEqual(after['observed']['config_sha256'], resources.sha(self.file.read_bytes()))
        self.assertNotIn('pending_transaction', after)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(stat.S_IMODE((directory/'before.json').stat().st_mode), 0o600)
        self.assertEqual(json.loads((directory/'before.json').read_text())['record'], self.saved)
        self.assertNotIn('private-test-value', str(self.calls))

    def test_network_environment_template_and_extra_device_edits_use_the_normal_installer(self):
        for mutate in (
            lambda c: c['deployment']['network'].update(ipv4='192.0.2.2/24'),
            lambda c: c['deployment']['environment'][0].update(value='changed'),
            lambda c: c['template']['container_contract']['image'].update(reference='example/app:other'),
            lambda c: c['deployment']['devices'].append({'host_path': '/dev/ttyACM0'}),
            lambda c: c['deployment']['resources'].update(swap_mb=1024),
        ):
            candidate = copy.deepcopy(self.candidate)
            mutate(candidate)
            self.assertIsNone(resources.changes(self.saved, candidate, CONFIG))

    def test_invalid_values_and_unchanged_proposal_do_not_use_the_native_path(self):
        for value in (True, 0, -1, 64, 128.5, '768'):
            candidate = copy.deepcopy(self.saved)
            candidate['deployment']['resources']['memory_mb'] = value
            self.assertIsNone(resources.changes(self.saved, candidate, CONFIG))
        self.assertIsNone(resources.changes(self.saved, copy.deepcopy(self.saved), CONFIG))

    def test_cpu_limit_profile_stays_a_cpu_limit(self):
        config = CONFIG.replace(b'cores: 2', b'cpulimit: 2')
        self.assertEqual(resources.changes(self.saved, self.candidate, config), {'cpulimit': '3', 'memory': '768'})

    def test_native_failure_leaves_saved_record_and_config_unchanged(self):
        self.native_failure = RuntimeError('native API rejected edit')
        with self.assertRaisesRegex(RuntimeError, 'rejected'):
            self.apply()
        self.assertEqual(self.file.read_bytes(), CONFIG)
        self.assertEqual(instances.read(self.root, 115), self.saved)

    def test_observation_failure_rolls_back_resource_values(self):
        with patch.object(instances, 'observe', side_effect=RuntimeError('observation failed')):
            with self.assertRaisesRegex(RuntimeError, 'observation failed'):
                self.apply()
        self.assertEqual(self.file.read_bytes(), CONFIG)
        self.assertEqual(instances.read(self.root, 115), self.saved)
        self.assertEqual(len(self.calls), 2)

    def test_record_write_failure_rolls_back_resources(self):
        real_write = instances.write
        failed = False
        def write(path, value):
            nonlocal failed
            if Path(path) == instances.location(self.root, 115) and not failed:
                failed = True
                raise OSError('record could not be saved')
            real_write(path, value)
        with patch.object(instances, 'write', side_effect=write):
            with self.assertRaisesRegex(OSError, 'could not be saved'):
                self.apply()
        self.assertEqual(self.file.read_bytes(), CONFIG)
        self.assertEqual(instances.read(self.root, 115), self.saved)

    def test_configuration_drift_is_rejected_before_native_set(self):
        self.file.write_bytes(CONFIG.replace(b'memory: 512', b'memory: 1024'))
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.apply()
        self.assertEqual(self.calls, [])

    def test_repeated_environment_entries_are_all_preserved_by_the_guard(self):
        changed = CONFIG.replace(b'cores: 2', b'cores: 3').replace(b'memory: 512', b'memory: 768')
        self.assertTrue(resources.expected_config(CONFIG, changed, self.params))
        self.assertFalse(resources.expected_config(CONFIG, changed.replace(b'A=one', b'A=foreign'), self.params))

    def test_cpu_change_preserves_homepage_dns_timezone_and_cpu_priority(self):
        extra = b'nameserver: 10.0.1.1\ntimezone: Europe/Madrid\ncpuunits: 100\n'
        config = CONFIG + extra
        self.file.write_bytes(config)
        self.saved['observed'].update(config=config.decode(), config_sha256=resources.sha(config))
        self.saved['deployment']['resources']['cpu_units'] = 100
        self.candidate = copy.deepcopy(self.saved)
        self.candidate['deployment']['resources']['cores'] = 3
        instances.write(instances.location(self.root,115),self.saved)
        resources.apply(self.root,self.saved,self.candidate,config,{'cores':'3'})
        self.assertEqual(self.file.read_bytes(), config.replace(b'cores: 2',b'cores: 3'))
        self.assertEqual(instances.read(self.root,115)['deployment']['resources']['cpu_units'],100)

    def test_a_concurrent_unrelated_change_is_not_overwritten_during_rollback(self):
        def observe(*args):
            self.file.write_bytes(self.file.read_bytes().replace(b'A=one', b'A=foreign'))
            raise RuntimeError('concurrent edit')
        with patch.object(instances, 'observe', side_effect=observe), patch.object(resources, 'msg_warn') as warn:
            with self.assertRaisesRegex(RuntimeError, 'concurrent edit'):
                self.apply()
        self.assertIn(b'A=foreign', self.file.read_bytes())
        self.assertEqual(len(self.calls), 1)
        warn.assert_called_once()
        self.assertEqual(instances.read(self.root, 115), self.saved)

    def test_a_carried_record_error_does_not_undo_the_successful_edit(self):
        with patch.object(oci_carried_record, 'carry', side_effect=RuntimeError('copy unavailable')):
            self.apply()
        self.assertEqual(instances.read(self.root, 115)['deployment']['resources']['memory_mb'], 768)
        self.assertEqual(len(self.calls), 1)


class CachedArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'original-installation.tar'
        self.path.write_bytes(b'fixture verified by stub')
        self.desired = record()
        self.image = {'manifest_digest': DIGEST}
        self.candidate = dict(self.image, registry_digest=DIGEST)

    def resolve(self, paths, image=None):
        def run(args, error, capture=False):
            self.assertNotEqual(args[0], 'skopeo', 'No layers should be downloaded')
            return json.dumps(self.candidate) if '-c' in args else b''
        with patch.object(update, 'run_quiet', side_effect=run), \
                patch.object(update, 'image_from_archive', return_value=image or self.image), \
                patch.object(instances, 'command') as command:
            result = update.resolve_archive(self.desired, b'arch: amd64\n', local_archives=paths)
        command.assert_not_called()
        return result

    def test_original_installation_archive_is_reused_without_update_cache_lookup(self):
        self.assertEqual(self.resolve([self.path]), (self.path, DIGEST))

    def test_invalid_original_cache_is_kept_and_a_second_matching_archive_is_reused(self):
        other = self.path.with_name('other.tar')
        other.write_bytes(b'second fixture')
        def image(path):
            return {'manifest_digest': NEW if str(path) == str(self.path) else DIGEST}
        with patch.object(update, 'run_quiet', side_effect=lambda args, *a, **kw: json.dumps(self.candidate) if '-c' in args else b''), \
                patch.object(update, 'image_from_archive', side_effect=image), \
                patch.object(instances, 'command') as command:
            result = update.resolve_archive(self.desired, b'arch: amd64\n', local_archives=[self.path, other])
        self.assertEqual(result, (other, DIGEST))
        self.assertTrue(self.path.exists())
        command.assert_not_called()

    def test_a_new_digest_downloads_once_instead_of_using_an_old_archive(self):
        candidate = {'manifest_digest': NEW, 'registry_digest': NEW}
        cached = self.path.with_name('update.tar')
        copies = []
        def run(args, *a, **kwargs):
            if '-c' in args:
                return json.dumps(candidate)
            if args[0] == 'skopeo':
                copies.append(args)
                Path(args[-1].removeprefix('oci-archive:')).write_bytes(b'new verified fixture')
            return b''
        def image(path):
            return {'manifest_digest': DIGEST if str(path) == str(self.path) else NEW}
        with patch.object(update, 'run_quiet', side_effect=run), \
                patch.object(update, 'image_from_archive', side_effect=image), \
                patch.object(instances, 'command', return_value=str(cached).encode()), \
                patch.object(update.work_backup, 'available', return_value=1024**4), \
                patch.object(update.transaction, 'log'):
            result = update.resolve_archive(self.desired, b'arch: amd64\n', local_archives=[self.path])
        self.assertEqual(result, (cached, NEW))
        self.assertEqual(len(copies), 1)
        self.assertIn('docker://example/app@'+NEW, copies[0])
        self.assertEqual(self.path.read_bytes(), b'fixture verified by stub')

    def test_a_broken_or_symlink_original_cache_does_not_hide_a_valid_update_cache(self):
        cached = self.path.with_name('update.tar')
        cached.write_bytes(b'valid update fixture')
        link = self.path.with_name('link.tar')
        link.symlink_to(self.path)
        verified = []
        def run(args, *a, **kwargs):
            if '-c' in args:
                return json.dumps(self.candidate)
            self.assertNotEqual(args[0], 'skopeo')
            verified.append(Path(args[-1]))
            if Path(args[-1]) == self.path:
                raise RuntimeError('corrupt archive')
            return b''
        with patch.object(update, 'run_quiet', side_effect=run), \
                patch.object(update, 'image_from_archive', return_value=self.image), \
                patch.object(instances, 'command', return_value=str(cached).encode()):
            result = update.resolve_archive(self.desired, b'arch: amd64\n', local_archives=[link, self.path])
        self.assertEqual(result, (cached, DIGEST))
        self.assertNotIn(link, verified)
        self.assertTrue(link.is_symlink())
        self.assertTrue(self.path.exists())


class UpdateRoutingTests(unittest.TestCase):
    def run_update(self, new_image=False, resource_edit=True, reject_recreation=False):
        saved = record()
        candidate = copy.deepcopy(saved)
        candidate['deployment']['resources']['memory_mb'] = 768
        if not resource_edit:
            candidate['deployment']['environment'][0]['value'] = 'changed'
        proposal = {'operation': 'recreate', 'candidate': candidate}
        import contextlib, oci_operation_notice
        with patch.object(instances, 'locked', return_value=contextlib.nullcontext()), \
                patch.object(instances, 'read', return_value=saved), \
                patch.object(instances, 'command', return_value=CONFIG), \
                patch.object(update.transaction, 'candidate_contract', return_value=candidate), \
                patch.object(update.transaction, 'external_changes', return_value={}), \
                patch.object(update.transaction, 'preflight', side_effect=ValueError('advanced Proxmox settings') if reject_recreation else None), \
                patch.object(update, 'resolve_archive', return_value=(Path('/new.tar') if new_image or not resource_edit else None, NEW if new_image else DIGEST)) as resolve, \
                patch.object(resources, 'apply') as apply_resources, \
                patch.object(update.transaction, 'apply') as apply_image, \
                patch.object(oci_operation_notice, 'operation', return_value=contextlib.nullcontext()):
            update.update(115, proposal=proposal)
        return resolve, apply_resources, apply_image

    def test_unchanged_image_routes_cpu_ram_edits_to_the_existing_guest(self):
        resolve, native, image = self.run_update()
        resolve.assert_not_called()
        native.assert_called_once()
        image.assert_not_called()

    def test_a_new_image_for_other_configuration_changes_uses_verified_recreation(self):
        _resolve, native, image = self.run_update(new_image=True,resource_edit=False)
        native.assert_not_called()
        image.assert_called_once()

    def test_cpu_edits_do_not_implicitly_upgrade_the_image(self):
        resolve,native,image=self.run_update(new_image=True)
        resolve.assert_not_called()
        native.assert_called_once()
        image.assert_not_called()

    def test_homepage_resource_edit_does_not_run_the_recreation_preflight(self):
        resolve,native,image=self.run_update(reject_recreation=True)
        resolve.assert_not_called()
        native.assert_called_once()
        image.assert_not_called()

    def test_other_modifications_offer_the_recorded_archive_to_the_resolver(self):
        resolve, native, image = self.run_update(resource_edit=False)
        self.assertIsNone(resolve.call_args.args[2])
        self.assertEqual(resolve.call_args.kwargs['local_archives'], ['/missing/deleted-image.tar'])
        native.assert_not_called()
        image.assert_called_once()


if __name__ == '__main__':
    unittest.main()
