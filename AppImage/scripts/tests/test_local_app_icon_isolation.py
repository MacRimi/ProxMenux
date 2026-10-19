"""Security boundaries independent of UI/cache successes; no live CT required."""
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import local_app_icons as icons


def png():
    output = io.BytesIO()
    Image.new('RGB', (8, 8)).save(output, 'PNG')
    return output.getvalue()


class Isolation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_root_normalization_never_opens_an_image_in_the_monitor(self):
        data = png()
        with patch.object(icons.os, 'geteuid', return_value=0), \
                patch.object(icons, '_decode_worker', return_value=(data, 'image/png'), create=True) as child, \
                patch.object(Image, 'open', side_effect=AssertionError('root decoder forbidden')) as opened:
            self.assertEqual(icons.normalize(data, 'image/png'), (data, 'image/png'))
        child.assert_called_once_with(data, 'image/png')
        opened.assert_not_called()

    def test_only_the_selected_raster_decoder_is_enabled(self):
        data = png()
        with patch.object(icons.os, 'geteuid', return_value=65534), patch.object(Image, 'open', wraps=Image.open) as opened:
            getattr(icons, '_normalize', icons.normalize)(data, 'image/png')
        self.assertEqual(opened.call_args.kwargs.get('formats'), ['PNG'])

    def test_unprivileged_monitor_also_uses_a_bounded_decoder(self):
        data=png()
        with patch.object(icons.os,'geteuid',return_value=1001), \
                patch.object(icons,'_decode_worker',return_value=(data,'image/png')) as decoder:
            self.assertEqual(icons.normalize(data,'image/png'),(data,'image/png'))
        decoder.assert_called_once_with(data,'image/png')

    def test_direct_root_decoder_is_rejected_before_pillow(self):
        data=png()
        with patch.object(icons.os,'geteuid',return_value=0),patch.object(Image,'open') as opened:
            with self.assertRaises(icons.IconError):icons._normalize(data,'image/png')
        opened.assert_not_called()

    def test_saturated_decoder_has_zero_child_or_image_calls(self):
        data=png();slots=Mock();slots.acquire.return_value=False
        with patch.object(icons,'DECODERS',slots),patch.object(icons,'_decode_worker') as worker,patch.object(Image,'open') as opened:
            with self.assertRaises(icons.IconError):icons.normalize(data,'image/png')
        worker.assert_not_called();opened.assert_not_called();slots.release.assert_not_called()

    def test_decoder_failure_always_releases_its_slot(self):
        data=png();slots=Mock();slots.acquire.return_value=True
        with patch.object(icons,'DECODERS',slots),patch.object(icons,'_decode_worker',side_effect=icons.IconError('unavailable')):
            with self.assertRaises(icons.IconError):icons.normalize(data,'image/png')
        slots.release.assert_called_once()

    def test_foreign_address_has_zero_http_calls_even_when_lxc_reports_it(self):
        with patch.object(icons, '_owns_address', return_value=False, create=True), \
                patch.object(icons, '_open', side_effect=AssertionError('foreign network forbidden')) as http:
            with self.assertRaises(icons.IconError):
                icons._fetch('http://10.0.0.99:8080')
        http.assert_not_called()

    def fake_proc(self):
        for folder in ('self/ns', '2468/ns'):
            (self.root / folder).mkdir(parents=True)
            (self.root / folder / 'net').write_text('namespace fixture')
        (self.root / '2468/stat').write_text('2468 (container (init)) S ' + '0 ' * 18 + '12345 0\n')

    def test_namespace_descriptor_is_pinned_and_closed(self):
        self.fake_proc()
        with patch.object(icons, 'PROC', self.root), patch.object(icons, '_run', return_value='2468\n') as run:
            with icons._network(101) as (fd, identity):
                self.assertEqual(identity[0:2], (2468, '12345'))
                self.assertEqual(os.fstat(fd).st_ino, (self.root / '2468/ns/net').stat().st_ino)
                self.assertTrue(icons._network_unchanged(101, identity))
            with self.assertRaises(OSError):os.fstat(fd)
        self.assertTrue(all(c.args[0] == ['lxc-info', '-n', '101', '-pH'] for c in run.call_args_list))

    def test_host_namespace_pid_reuse_and_changed_pid_never_fetch_or_store(self):
        for case in ('host', 'pid', 'start', 'namespace'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                self.root = Path(temporary);self.fake_proc()
                def identify(args):
                    if case == 'pid':return '2469' if identify.calls else self.first(identify)
                    if identify.calls:
                        if case == 'start':(self.root / '2468/stat').write_text('2468 (init) S ' + '0 ' * 18 + '54321\n')
                        if case == 'namespace':
                            (self.root / '2468/ns/new').write_text('replacement')
                            os.replace(self.root / '2468/ns/new', self.root / '2468/ns/net')
                    identify.calls += 1
                    return '2468'
                identify.calls=0
                if case=='host':
                    (self.root / '2468/ns/net').unlink()
                    os.link(self.root / 'self/ns/net', self.root / '2468/ns/net')
                with patch.object(icons, 'PROC', self.root), patch.object(icons, '_run', side_effect=identify), \
                        patch.object(icons, '_origin', return_value='http://10.0.0.42:80'), \
                        patch.object(icons, '_worker') as worker, patch.object(icons, 'store') as store:
                    with self.assertRaises(icons.IconError):icons.discover(101, {'port':80,'scheme':'http'})
                worker.assert_not_called();store.assert_not_called()

    @staticmethod
    def first(function):
        function.calls+=1
        return '2468'

    def test_missing_or_invalid_pid_cannot_start_a_worker(self):
        for value in ('', '0', '1', '-3', '2468\n2469', 'text'):
            with self.subTest(pid=value), patch.object(icons, '_run', return_value=value), \
                    patch.object(icons, '_origin', return_value='http://10.0.0.42:80'), \
                    patch.object(icons, '_worker') as worker, patch.object(icons, 'store') as store, \
                    patch.object(icons.os, 'open') as opened:
                with self.assertRaises(icons.IconError):icons.discover(101, {'port':80,'scheme':'http'})
                worker.assert_not_called();store.assert_not_called();opened.assert_not_called()

    def test_partial_process_identity_and_missing_namespace_fail_without_effects(self):
        for value in ('', '2468 (truncated)', '2468 (init) S 0 0'):
            with self.subTest(stat=value),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);(root/'2468').mkdir();(root/'2468/stat').write_text(value)
                with patch.object(icons,'PROC',root),patch.object(icons,'_run',return_value='2468'), \
                        patch.object(icons,'_origin',return_value='http://10.0.0.42:80'), \
                        patch.object(icons,'_worker') as worker,patch.object(icons,'store') as store:
                    with self.assertRaises(icons.IconError):icons.discover(101,{'port':80,'scheme':'http'})
                worker.assert_not_called();store.assert_not_called()
        self.fake_proc();(self.root/'2468/ns/net').unlink()
        with patch.object(icons,'PROC',self.root),patch.object(icons,'_run',return_value='2468'), \
                patch.object(icons,'_origin',return_value='http://10.0.0.42:80'), \
                patch.object(icons,'_worker') as worker,patch.object(icons,'store') as store:
            with self.assertRaises(icons.IconError):icons.discover(101,{'port':80,'scheme':'http'})
        worker.assert_not_called();store.assert_not_called()

    def test_failed_init_pid_command_has_zero_network_or_cache_effects(self):
        with patch.object(icons,'_run',side_effect=icons.IconError('lxc-info timed out')), \
                patch.object(icons,'_origin',return_value='http://10.0.0.42:80'), \
                patch.object(icons,'_worker') as worker,patch.object(icons,'store') as store:
            with self.assertRaises(icons.IconError):icons.discover(101,{'port':80,'scheme':'http'})
        worker.assert_not_called();store.assert_not_called()

    def test_guest_restart_after_worker_preserves_existing_cache(self):
        with patch.object(icons, '_origin', return_value='http://10.0.0.42:80'), \
                patch.object(icons, '_network', return_value=contextlib.nullcontext((81,'old'))), \
                patch.object(icons, '_worker', return_value=(png(),'image/png')), \
                patch.object(icons, '_network_unchanged', return_value=False), patch.object(icons,'store') as store:
            with self.assertRaises(icons.IconError):icons.discover(101, {'port':80,'scheme':'http'})
        store.assert_not_called()

    def test_only_ct_network_namespace_and_unprivileged_credentials_are_selected(self):
        with patch.object(icons.os,'geteuid',return_value=0):
            command=icons._worker_command(['--fetch','http://10.0.0.42:80','81'],81)
            decoder=icons._worker_command(['--decode'],None)
        self.assertEqual(command[:4],['/usr/bin/nsenter','--net=/proc/self/fd/81','--no-fork','--'])
        for required in ('--reuid=65534','--regid=65534','--clear-groups','--no-new-privs','--bounding-set=-all','--inh-caps=-all','--ambient-caps=-all'):
            self.assertIn(required,command);self.assertIn(required,decoder)
        self.assertEqual(decoder[:3],['/usr/bin/unshare','--net','--'])
        self.assertNotIn('--all',command);self.assertNotIn('--mount',command);self.assertNotIn('--user',command)

    def test_failure_to_enter_namespace_has_no_host_fallback(self):
        with patch.object(icons.subprocess,'Popen',side_effect=OSError('nsenter unavailable')) as start:
            with self.assertRaises(icons.IconError):icons._worker('http://10.0.0.42:80',81)
        self.assertEqual(start.call_count,1)
        self.assertEqual(start.call_args.args[0][0],'/usr/bin/nsenter')
        self.assertEqual(start.call_args.kwargs['pass_fds'],(81,))

    def test_address_ownership_uses_only_namespace_local_interfaces(self):
        for address in ('10.0.0.42','fd12::42'):
            with patch.object(icons,'_run',return_value=json.dumps([{'addr_info':[{'local':address}]}])) as run:
                self.assertTrue(icons._owns_address(address));self.assertFalse(icons._owns_address('10.0.0.99'))
                self.assertEqual(run.call_args.args[0],['/usr/sbin/ip','-json','address','show'])
        with patch.object(icons,'_run',return_value='partial JSON'), patch.object(icons,'_open') as network:
            with self.assertRaises(icons.IconError):icons._fetch('http://10.0.0.42:80')
            network.assert_not_called()

    def test_worker_security_guard_precedes_decode_or_network(self):
        fields='NoNewPrivs:\t1\nCapEff:\t0\nCapPrm:\t0\nCapAmb:\t0\n'
        for uid,gid,groups,body in ((0,65534,[],fields),(65534,0,[],fields),
                (65534,65534,[0],fields),(65534,65534,[],fields.replace('NoNewPrivs:\t1','NoNewPrivs:\t0')),
                *[(65534,65534,[],fields.replace(key+':\t0',key+':\t1')) for key in ('CapEff','CapPrm','CapAmb')]):
            with patch.object(icons.os,'geteuid',return_value=uid),patch.object(icons.os,'getegid',return_value=gid), \
                    patch.object(icons.os,'getgroups',return_value=groups),patch.object(Path,'read_text',return_value=body):
                with self.assertRaises(icons.IconError):icons._assert_worker()

    def test_oversized_and_malformed_worker_output_is_rejected(self):
        helper=self.root/'output.py'
        for body in ('x'*(icons.MAX_BYTES*2+1),'not-json',json.dumps({'mime':'image/png','body':'bad base64'})):
            helper.write_text('import sys\nsys.stdout.write('+repr(body)+')\n')
            with patch.object(icons,'_worker_command',return_value=[sys.executable,str(helper)]):
                with self.assertRaises(icons.IconError):icons._run_worker(['--decode'])

    def test_root_legacy_and_current_cache_decode_without_guest_probes(self):
        data=png();root=self.root/'101';root.mkdir()
        for legacy in (False,True):
            token=('a' if legacy else 'b')*32
            if legacy:
                (root/(token+'.bin')).write_bytes(data)
                (root/(token+'.json')).write_text(json.dumps({'content_type':'image/png'}))
            else:(root/(token+'.icon')).write_text(json.dumps({'mime':'image/png','body':base64.b64encode(data).decode()}))
            with patch.object(icons,'CACHE',self.root),patch.object(icons.os,'geteuid',return_value=0), \
                    patch.object(icons,'_decode_worker',return_value=(data,'image/png')) as decoder, \
                    patch.object(icons,'_run') as guest,patch.object(Image,'open') as raster:
                self.assertEqual(icons.read(101,token),(data,'image/png'))
                decoder.assert_called_once();guest.assert_not_called();raster.assert_not_called()


if __name__=='__main__':unittest.main()
