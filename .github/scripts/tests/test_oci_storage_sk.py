"""Slovak storage questions through real builders and UI; installation forbidden."""
from contextlib import redirect_stdout
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'oci/src'),str(ROOT/'oci/remote')]
from proxmenux_oci import cli, custom, custom_mounts, extra_devices, i18n, installer, ui as native_ui, updates
from proxmenux_oci.catalog import Catalog


class Recorder:
    def __init__(self, answers=None):
        self.answers=answers or {}
        self.asked=[]
        self.messages=[]
    def _answer(self,text,default):
        self.asked.append(text)
        return self.answers.get(text,default)
    def ask(self,text,default=None,**kwargs):return self._answer(text,default if default is not None else '')
    def password(self,text,**kwargs):return self._answer(text,'fictional-value-for-tests-000000')
    def choose(self,text,options,default=None,**kwargs):return self._answer(text,default)
    def confirm(self,text,default=False,**kwargs):return self._answer(text,default)
    def checklist(self,text,options,defaults=None,**kwargs):return self._answer(text,defaults or [])
    def review(self,*args,**kwargs):return False
    def info(self,text):pass
    def message(self,text,*args):self.messages.append(text)


class StorageFixture(unittest.TestCase):
    def setUp(self):
        self.catalog=Catalog(ROOT/'oci')
        self.sk=json.loads((ROOT/'lang/sk.json').read_text())
        self.forbidden=[]
        self.patch(i18n,'_language','sk')
        self.patch(i18n,'_cache',self.sk)
        self.patch(installer.host,'storages',side_effect=lambda content: [
            {'storage':'local-lvm','type':'lvmthin','avail':100*2**30},
            {'storage':'fiction-storage','type':'dir','avail':200*2**30}] if content=='rootdir' else [
            {'storage':'local','type':'dir','avail':100*2**30}])
        self.patch(installer.host,'bridges',return_value=[{'iface':'vmbr0','cidr':'192.0.2.10/24'}])
        self.patch(installer.host,'timezone',return_value='Europe/Bratislava')
        self.patch(installer.host,'gpus',return_value={'intel':[],'amd':[],'nvidia':False})
        self.patch(installer.access,'ask_addresses',side_effect=lambda ui,bridge,names,*a:({name:'dhcp' for name in names},None))
        self.patch(installer.access,'ask_ipv4',return_value=('dhcp',None))
        for module,name in [(installer,'run_remote_install'),(cli,'run_remote_install'),
                (cli.images,'offer_removal'),(subprocess,'run'),(subprocess,'Popen'),(subprocess,'check_output'),
                (Path,'write_text'),(Path,'write_bytes'),(Path,'unlink')]:
            self.forbidden.append(self.patch(module,name,side_effect=AssertionError('Forbidden effect: '+name)))
        self.addCleanup(self.no_effects)
    def patch(self,module,name,*args,**kwargs):
        item=patch.object(module,name,*args,**kwargs);value=item.start();self.addCleanup(item.stop);return value
    def no_effects(self):
        for effect in self.forbidden:effect.assert_not_called()
    def recorder(self,answers=None):
        return Recorder({i18n.translate(key):value for key,value in (answers or {}).items()})
    def build(self,app,answers=None,mode=installer.ADVANCED_MODE):
        ui=self.recorder(answers)
        plan=installer.build_deployment(self.catalog.compose(app),ui,mode)
        return ui,plan


class StorageWordingTests(StorageFixture):
    def test_tandoor_files_question_and_minimum_error_keep_the_limit(self):
        ui,plan=self.build('tandoor',{'Files volume size in GB':'9'})
        self.assertIn('Veľkosť dátového zväzku pre súbory v GB',ui.asked)
        self.assertEqual(plan['media']['size_gb'],9)
        with self.assertRaisesRegex(installer.InstallError,'Dátový zväzok súborov Tandoor musí mať najmenej 2 GB'):
            self.build('tandoor',{'Files volume size in GB':'1'})

    def test_paperless_storage_documents_and_consume_export_names(self):
        ui,plan=self.build('paperless-ngx',{'Documents volume size in GB':'30',
            'Where to store the consume and export folders':'managed-volume','Size of each consume/export volume in GB':'3'})
        for text in ['Úložisko pre údaje a dokumenty aplikácie Paperless',
                'Veľkosť dátového zväzku pre dokumenty v GB',
                'Veľkosť každého dátového zväzku pre consume a export v GB']:
            self.assertIn(text,ui.asked)
        self.assertEqual((plan['media_size_gb'],plan['transfer']['size_gb'],plan['transfer']['backup']),(30,3,True))

    def test_paperless_volume_limit_and_transfer_limit_errors(self):
        with self.assertRaisesRegex(installer.InstallError,'Trvalé dátové zväzky aplikácie Paperless musia mať najmenej 8 GB'):
            self.build('paperless-ngx',{'Documents volume size in GB':'7'})
        with self.assertRaisesRegex(installer.InstallError,'Dátové zväzky pre consume a export musia mať najmenej 1 GB'):
            self.build('paperless-ngx',{'Where to store the consume and export folders':'managed-volume',
                'Size of each consume/export volume in GB':'0'})

    def test_postgresql_question_and_error_are_shared_by_immich_and_nextcloud(self):
        for app in ('immich','nextcloud-stack'):
            with self.subTest(app=app):
                ui,plan=self.build(app,{'PostgreSQL volume size in GB':'12'})
                self.assertIn('Veľkosť dátového zväzku PostgreSQL v GB',ui.asked)
                self.assertEqual(plan['database_size_gb'],12)
                with self.assertRaisesRegex(installer.InstallError,'Dátový zväzok PostgreSQL musí mať najmenej 8 GB'):
                    self.build(app,{'PostgreSQL volume size in GB':'7'})

    def test_host_directory_remains_outside_the_container_backup(self):
        ui,plan=self.build('nextcloud-stack',{'Where to store the Nextcloud files, configuration and data':'host-bind',
            'Shared host directory':'/fiction-only/existing-data'})
        self.assertIn('Zdieľaný adresár hostiteľa',ui.asked)
        self.assertEqual((plan['application']['mode'],plan['application']['host_path'],plan['application']['backup']),
            ('host-bind','/fiction-only/existing-data',False))

    def test_default_and_advanced_builders_preserve_language_independent_plans(self):
        for app in ('jellyfin','immich','nextcloud-stack','paperless-ngx','tandoor'):
            for mode in (installer.DEFAULT_MODE,installer.ADVANCED_MODE):
                with self.subTest(app=app,mode=mode):
                    _ui,slovak=self.build(app,mode=mode)
                    with patch.object(i18n,'_language','en'):
                        _ui,english=self.build(app,mode=mode)
                    self.assertEqual(slovak,english)

    def test_multi_path_cancel_and_invalid_selection_preserve_all_members(self):
        services=[{'name':'main','main':True,'deployment':{'mounts':[]}},
                  {'name':'database','deployment':{'mounts':[]}}]
        original=copy.deepcopy(services)
        ui=self.recorder({'Add extra paths to this stack':True,'Containers that will receive this path':[]})
        with self.assertRaisesRegex(ValueError,'^Vyberte aspoň jeden kontajner aplikácie$'):
            custom_mounts.ask_stack_custom_mounts(ui,services,'fiction-storage')
        self.assertIn('Pridať ďalšie cesty do aplikácie s viacerými kontajnermi',ui.asked)
        self.assertEqual(services,original)
        ui=self.recorder({'Add extra paths to this stack':True,'Containers that will receive this path':['main'],
            'Data location':None})
        with self.assertRaises(native_ui.UserCancelled):custom_mounts.ask_stack_custom_mounts(ui,services,'fiction-storage')
        self.assertEqual(services,original)

    def test_shared_selection_error_in_device_flow_also_preserves_members(self):
        services=[{'name':'main','main':True,'deployment':{}}];original=copy.deepcopy(services)
        ui=self.recorder()
        with patch.object(extra_devices,'ask_extra_devices',return_value=[{'kind':'usb','host_path':'/fiction-only/device'}]), \
                patch.object(ui,'checklist',return_value=[]):
            with self.assertRaisesRegex(ValueError,'^Vyberte aspoň jeden kontajner aplikácie$'):
                extra_devices.ask_stack_extra_devices(ui,services)
        self.assertEqual(services,original)

    def test_selected_path_is_added_only_to_selected_member_with_backup(self):
        services=[{'name':'main','main':True,'deployment':{'mounts':[]}},
                  {'name':'database','deployment':{'mounts':[]}}]
        ui=self.recorder({'Add extra paths to this stack':True,'Containers that will receive this path':['main']})
        custom_mounts.ask_stack_custom_mounts(ui,services,'fiction-storage')
        self.assertEqual(services[1]['deployment']['mounts'],[])
        mount=services[0]['deployment']['mounts'][0]
        self.assertEqual((mount['source'],mount['container_path'],mount['size_gb'],mount['backup']),
            ('fiction-storage','/media-extra',8,True))
        self.assertIn('Pridať ďalšiu cestu do aplikácie s viacerými kontajnermi',ui.asked)

    def test_rclone_shared_directory_question_is_localized_without_creating_it(self):
        ui=self.recorder({'Shared directory for copy/sync operations':'/fiction-only/rclone'})
        with patch.object(ui,'confirm',return_value=True):
            plan=installer.build_deployment(self.catalog.compose('rclone'),ui,installer.ADVANCED_MODE)
        self.assertIn('Zdieľaný adresár na kopírovanie a synchronizáciu',ui.asked)
        self.assertTrue(any(m.get('source')=='/fiction-only/rclone' and not m['backup'] for m in plan['mounts']))


class InputAndCancellationTests(StorageFixture):
    def test_dialog_required_value_and_password_use_slovak_then_retry(self):
        dialog=native_ui.DialogUI()
        empty=subprocess.CompletedProcess('dialog',0,stderr='')
        value=subprocess.CompletedProcess('dialog',0,stderr='fiction-value')
        with patch.object(dialog,'_run',side_effect=[empty,value]),patch.object(dialog,'message') as message:
            self.assertEqual(dialog.ask('fiction-field'),'fiction-value')
            message.assert_called_once_with('Táto hodnota je povinná.')
        with patch.object(dialog,'_run',side_effect=[empty,value,value]),patch.object(dialog,'message') as message:
            self.assertEqual(dialog.password('fiction-field'),'fiction-value')
            message.assert_called_once_with('Táto hodnota je povinná.')

    def test_terminal_required_value_and_password_are_also_localized(self):
        terminal=native_ui.TerminalUI()
        with patch('builtins.input',side_effect=['','fiction-value']),redirect_stdout(io.StringIO()) as output:
            self.assertEqual(terminal.ask('fiction-field'),'fiction-value')
        self.assertIn('Táto hodnota je povinná.',output.getvalue())
        with patch.object(native_ui.getpass,'getpass',side_effect=['','fiction-value','fiction-value']),redirect_stdout(io.StringIO()) as output:
            self.assertEqual(terminal.password('fiction-field'),'fiction-value')
        self.assertIn('Táto hodnota je povinná.',output.getvalue())

    def test_real_install_flow_storage_cancel_and_final_no_never_dispatch(self):
        template=self.catalog.compose('tandoor');original=copy.deepcopy(template)
        dialog=native_ui.DialogUI()
        for code in (1,255):
            replies=[subprocess.CompletedProcess('dialog',0,stderr=value) for value in ('','fiction-stack','2','2048')]
            replies.append(subprocess.CompletedProcess('dialog',code,stderr=''))
            with self.subTest(code=code),patch.object(dialog,'_run',side_effect=replies) as run:
                with self.assertRaises(native_ui.UserCancelled):cli.install_template(dialog,template,'tandoor',installer.ADVANCED_MODE)
                self.assertEqual(run.call_count,5)
                self.assertEqual(template,original)
        self.assertIsNone(cli.install_template(self.recorder(),template,'tandoor',installer.ADVANCED_MODE))
        self.assertEqual(template,original)

    def test_numeric_retry_keeps_previous_answers_and_already_correct_slovak(self):
        ui=Recorder();wizard=native_ui.BacktrackUI(ui)
        wizard.answers=[('ask','previous'),('ask','abc')];wizard.cursor=2
        self.assertTrue(wizard.retry_last(ValueError("invalid literal for int() with base 10: 'abc'")))
        self.assertEqual(ui.messages,["Hodnota musí byť číslo: 'abc'\n\nZadajte hodnotu znova."])
        self.assertEqual((wizard.answers,wizard.cursor),([('ask','previous')],0));wizard.close()

    def test_real_menu_error_handler_has_slovak_heading_and_preserves_detail(self):
        ui=Mock();ui.choose.side_effect=['custom',None]
        with patch.object(cli,'interactive_ui',return_value=ui),patch.object(custom,'explore',side_effect=ValueError('fiction-detail')), \
                patch.object(updates,'UpdateCheck') as checker:
            check=checker.return_value.__enter__.return_value
            check.active=False;check.notice.return_value='';check.status.return_value={'available':[]}
            self.assertEqual(cli.interactive(self.catalog),0)
        ui.message.assert_called_once_with('Operáciu sa nepodarilo dokončiť:\n\nfiction-detail')
