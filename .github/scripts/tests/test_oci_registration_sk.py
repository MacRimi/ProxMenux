"""Restored-app registration through real Menu/CLI/Dialog; no host effects."""
from contextlib import nullcontext, redirect_stdout
import copy
import io
import json
from pathlib import Path
import string
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_oci_update_cancellation import CancellationFixture, ROOT
from proxmenux_oci import cli, i18n, management as menu, ui as native_ui
import oci_restore_recovery as restored
import oci_ui


class RegistrationFixture(CancellationFixture):
    def setUp(self):
        super().setUp()
        self.found = [{'vmid':110, 'hostname':'fiction-primary'}]
        self.original_found = copy.deepcopy(self.found)
        self.ui.confirm.return_value = False
        item = patch.object(menu, 'restored_applications', side_effect=lambda project:self.found)
        self.pending = item.start();self.addCleanup(item.stop)
        self.firewall = self.guard(menu, '_restored_firewall_rules')
        self.backend = [self.guard(restored, name) for name in ('recover','register','run')]
        self.files = [self.guard(Path, name) for name in ('write_text','write_bytes','unlink')]
        self.processes = [self.guard(subprocess, name) for name in ('run','Popen','check_output')]

    def members(self):
        self.found.append({'vmid':111,'hostname':'fiction-dependent'})
        self.original_found = copy.deepcopy(self.found)

    def no_effects(self):
        super().no_effects()
        self.firewall.assert_not_called()
        self.safe_backend()

    def safe_backend(self):
        for item in [*self.backend,*self.files,*self.processes]:item.assert_not_called()
        self.assertEqual(self.found,self.original_found)

    def accepted(self, answers, completed=True):
        self.ui.confirm.side_effect=answers
        self.firewall.side_effect=None
        self.firewall.return_value=[{'vmid':row['vmid'],'port':61208 if row['vmid']==110 else 19999,
                                    'source':'192.0.2.0/24'} for row in self.found]
        self.lifecycle.side_effect=None;self.lifecycle.return_value=completed
        self.pending.side_effect=lambda project:[] if completed and self.lifecycle.called else self.found


class RegistrationCancellationTests(RegistrationFixture):
    def test_offer_no_is_explicit_falsy_cancellation(self):
        self.assertIs(menu.offer_recovery(ROOT/'oci',self.ui),menu.CANCELLED)
        self.assertFalse(menu.CANCELLED);self.no_effects()

    def test_direct_single_no_finishes_before_a_third_pending_read(self):
        self.assertEqual(menu.direct_recovery(ROOT/'oci'),6)
        self.assertEqual(self.pending.call_count,2)
        self.no_effects()

    def test_real_cli_single_no_returns_six_without_output(self):
        with patch.object(cli,'Catalog'),redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(['recover']),6)
        self.assertEqual(output.getvalue(),'');self.no_effects()

    def test_real_cli_multi_container_no_is_not_a_guest_action(self):
        self.members()
        with patch.object(cli,'Catalog'):
            self.assertEqual(cli.main(['recover']),6)
        text=self.ui.confirm.call_args.args[0]
        self.assertIn('CT 110',text);self.assertIn('CT 111',text)
        self.no_effects()

    def test_actual_dialog_initial_no_and_escape_for_single_and_multi(self):
        dialog=native_ui.DialogUI()
        for multi in (False,True):
            if multi:self.members()
            for code in (1,255):
                with self.subTest(multi=multi,code=code),patch.object(native_ui,'interactive_ui',return_value=dialog), \
                        patch.object(dialog,'_run',return_value=subprocess.CompletedProcess('dialog',code,stderr='')):
                    self.assertEqual(menu.direct_recovery(ROOT/'oci'),6)
                self.no_effects()

    def test_native_menu_continues_to_list_after_registration_no(self):
        self.ui.choose.return_value=None
        with patch.object(menu,'_clean_orphans'),patch.object(menu,'_records_unread',return_value=[]):
            menu.interactive_management(ROOT/'oci',self.ui)
        self.ui.choose.assert_called_once();self.no_effects()

    def test_optional_firewall_and_start_no_registers_without_flags(self):
        self.members();self.accepted([True,False,False,False])
        self.assertEqual(menu.direct_recovery(ROOT/'oci'),0)
        self.assertEqual(self.lifecycle.call_args.args[0],
                         [menu.sys.executable,str(ROOT/'oci/remote/oci_restore_recovery.py'),'recover'])
        self.assertEqual(self.ui.confirm.call_count,4);self.safe_backend()

    def test_single_optional_no_preserves_registration_without_start(self):
        self.accepted([True,False,False])
        self.assertEqual(menu.direct_recovery(ROOT/'oci'),0)
        self.assertEqual(self.lifecycle.call_args.args[0],
                         [menu.sys.executable,str(ROOT/'oci/remote/oci_restore_recovery.py'),'recover'])
        self.assertEqual(self.ui.confirm.call_count,3);self.safe_backend()

    def test_only_one_confirmed_firewall_is_forwarded_and_no_start(self):
        self.members();self.accepted([True,False,True,False])
        self.assertEqual(menu.direct_recovery(ROOT/'oci'),0)
        self.assertEqual(self.lifecycle.call_args.args[0][-2:],['--host-firewall','111'])
        self.assertNotIn('--start',self.lifecycle.call_args.args[0]);self.safe_backend()

    def test_explicit_start_yes_retains_flag_but_never_starts_any_guest_here(self):
        self.accepted([True,False,True])
        self.assertEqual(menu.direct_recovery(ROOT/'oci'),0)
        self.assertEqual(self.lifecycle.call_args.args[0][-1],'--start');self.safe_backend()

    def test_failed_registration_stays_failure_with_pending_records(self):
        self.accepted([True,False,False],completed=False)
        self.assertEqual(menu.direct_recovery(ROOT/'oci'),1)
        self.safe_backend()

    def test_empty_list_is_success_without_confirmation_or_backend(self):
        self.found.clear();self.original_found=[]
        self.assertEqual(menu.direct_recovery(ROOT/'oci'),0)
        self.ui.confirm.assert_not_called();self.ui.message.assert_called_once();self.no_effects()

    def test_root_identity_failure_never_probes_restored_apps(self):
        with patch.object(menu.os,'geteuid',return_value=1000):
            self.assertEqual(menu.direct_recovery(ROOT/'oci'),1)
        self.pending.assert_not_called();self.ui.confirm.assert_not_called();self.no_effects()

    def test_empty_offer_does_not_cancel_the_native_menu(self):
        self.found.clear();self.original_found=[]
        self.assertIsNone(menu.offer_recovery(ROOT/'oci',self.ui))
        self.ui.confirm.assert_not_called();self.no_effects()

    def test_empty_registration_state_is_rendered_in_slovak_without_recovery(self):
        catalog=json.loads((ROOT/'lang/sk.json').read_text())
        with patch.object(i18n,'_language','sk'),patch.object(i18n,'_cache',catalog):
            self.found.clear();self.original_found=[]
            self.assertEqual(menu.direct_recovery(ROOT/'oci'),0)
        self.assertEqual(self.ui.message.call_args.args[0],
                         'Žiadna OCI aplikácia obnovená zo zálohy nečaká na opätovnú registráciu.')
        self.no_effects()

    def test_initial_single_and_multi_dialog_describes_registration_precheck(self):
        catalog=json.loads((ROOT/'lang/sk.json').read_text())
        for multi in (False,True):
            if multi:self.members()
            with self.subTest(multi=multi),patch.object(i18n,'_language','sk'),patch.object(i18n,'_cache',catalog):
                self.assertEqual(menu.direct_recovery(ROOT/'oci'),6)
            text=self.ui.confirm.call_args.args[0]
            self.assertIn('Pred opätovnou registráciou',text)
            self.assertNotIn('Obnova najprv',text)
            self.assertIn('aplikácie sa potom nespúšťajú automaticky',text)
            self.no_effects()

    def test_real_backend_blocker_stays_error_and_uses_registration_wording(self):
        catalog=json.loads((ROOT/'lang/sk.json').read_text())
        plan={'title':'Fictional restored application','restored':[{'vmid':110}],
              'blockers':['Fictional missing resource'],'notes':[]}
        with patch.object(menu.sys,'argv',['fixture','recover','--root','/fiction-only']), \
                patch.object(restored.instances,'locked',return_value=nullcontext()), \
                patch.object(restored,'prepare',return_value=[plan]), \
                patch.object(oci_ui,'_language','sk'),patch.object(oci_ui,'_cache',catalog), \
                patch.object(restored,'msg_error') as error,patch.object(restored,'msg_info2'):
            self.assertEqual(restored.main(),1)
        error.assert_called_once_with('Túto aplikáciu zatiaľ nemožno znova zaregistrovať:')
        self.no_effects()

    def test_real_host_resource_check_reports_missing_data_without_creating_anything(self):
        catalog=json.loads((ROOT/'lang/sk.json').read_text())
        plan={'restored':[{'vmid':110,'config':'mp0: /fiction-only/data,mp=/data\n',
                          'copy':{'record':{'deployment':{},'observed':{}}}}], 'blockers':[],'notes':[]}
        with patch.object(oci_ui,'_language','sk'),patch.object(oci_ui,'_cache',catalog), \
                patch.object(restored.os.path,'isdir',return_value=False), \
                patch.object(restored,'firewall_rule',return_value=None):
            restored.check_host_resources(plan)
        self.assertEqual(len(plan['blockers']),1)
        self.assertIn('/fiction-only/data',plan['blockers'][0])
        self.assertIn('registráciu zopakujte',plan['blockers'][0])
        self.no_effects()


class RegistrationContractTests(unittest.TestCase):
    def test_real_monitor_shell_recover_keeps_global_cli_contract_and_exit_six(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);(base/'scripts/oci').mkdir(parents=True)
            (base/'utils.sh').write_text('load_language() { :; }\ninitialize_cache() { :; }\n')
            (base/'scripts/oci/oci_manager_apps.sh').write_text('printf "%s\\n" "$@"\nexit 6\n')
            script=(ROOT/'scripts/oci/manage_instance.sh').read_text()
            script=script.replace('/usr/local/share/proxmenux',folder)
            import os
            result=subprocess.run(['bash','-c',script],capture_output=True,text=True,
                                  env={**os.environ,'ACTION':'recover','VMID':'not-a-vmid'})
        self.assertEqual(result.returncode,6);self.assertEqual(result.stdout,'recover\n')
        self.assertEqual(result.stderr,'')

    def test_curated_slovak_registration_words_and_format_fields(self):
        catalog=json.loads((ROOT/'lang/sk.json').read_text())
        expected={
          'Recover restored OCI applications':'Registrácia',
          'No restored OCI application is waiting to be recovered.':'registráciu',
          'Recover them now?':'zaregistrovať',
          'This application cannot be recovered yet:':'zaregistrovať',
          'The application could not be recovered:':'zaregistrovať',
          'Start the applications once they are registered? Answer No if the original containers are still running on another host: both would use the same addresses.':'vyberte Nie',
          'it is locked or its disk could not be mounted':'uzamknutý',
          'The local storage does not accept snippets':'local',
          'it uses an NVIDIA GPU and this host has no working NVIDIA driver and Container Toolkit. Install them and run the recovery again.':'NVIDIA Container Toolkit',
          'the NVIDIA hook of the container is not available:':'spúšťací skript',
          'its Rclone mount is published again on this host at':'v ceste',
          'Choose another bridge for the container in Proxmox (Network) and run the recovery again.':'registráciu',
          'Mount or create it with its data and run the recovery again.':'registráciu',
          'Connect it, or remove it from the container in Proxmox (Resources), and run the recovery again.':'registráciu',
        }
        fields=lambda text:sorted(f for _,f,_,_ in string.Formatter().parse(text) if f)
        for key,word in expected.items():
            with self.subTest(key=key):
                self.assertIn(word,catalog[key]);self.assertEqual(fields(key),fields(catalog[key]))

    def test_registration_web_text_is_distinct_from_previous_installation_recovery(self):
        for locale in ('en','sk'):
            data=json.loads((ROOT/'AppImage/messages'/locale/'common.json').read_text())['vmLxc']
            with self.subTest(locale=locale):
                self.assertEqual(data['ociUpdates']['registerRestored'],
                                 'Znova zaregistrovať' if locale=='sk' else 'Register again')
                self.assertEqual(data['ociUpdates']['recover'],'Obnoviť' if locale=='sk' else 'Recover')
                self.assertIn('zaregistrovať' if locale=='sk' else 'Register again',data['updates']['ociRestoredBody'])
                self.assertIn('Zaregistrovať' if locale=='sk' else 'Register',data['ociUpdates']['terminalTitleRecover'])


if __name__=='__main__':unittest.main()
