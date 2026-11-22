"""PBS CLI language and no-effect boundaries using real functions, isolated files."""
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]


def function(path, name):
    text = (ROOT/path).read_text()
    start = text.index(name+'() {')
    return text[start:text.index('\n}\n', start)+3]


def repository(components, suite='trixie'):
    return dict(Types=['deb'], URIs=['https://credential.invalid/private'], Suites=[suite],
                Components=components.split(), Enabled=True)


class RepositoryCliTests(unittest.TestCase):
    def run_policy(self, case, language='sk', mode='plan', malformed=None, product='pbs'):
        spec = importlib.util.spec_from_file_location('policy_fixture', ROOT/'scripts/global/repository_policy.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        state = dict(files=[dict(path='/etc/apt/sources.list.d/pbs.sources', repositories=[repository('pbs-enterprise')]),
                            dict(path='/etc/apt/sources.list.d/debian.sources', repositories=[repository('main')])],
                     errors=[], digest='fixture', **{'standard-repos':[{'handle':'no-subscription'}]})
        status='notfound'; calls=[]
        if case=='inventory': state['errors']=['PRIVATE RAW DIAGNOSTIC']
        if case=='status': status='unknown'
        if case=='suite': state['files'][0]['repositories'][0]['Suites']=['bookworm']
        if case=='active': status='active'; state['files']=state['files'][1:]
        if case=='debian': state['files']=state['files'][:1]
        if case=='mixed': state['files'][0]['repositories'][0]['Components'].append('main')
        if case=='handle': state['standard-repos']=[]
        if case=='preserve': state['files'][0]['repositories'][0]['Components']=['pbs-no-subscription']
        original=copy.deepcopy(state)
        def run(args):
            calls.append(args)
            if args[0]=='proxmox-backup-manager': return json.dumps(dict(status=status, serverid='PRIVATE SERVER ID'))
            if 'create' in args:
                state['files'][0]['repositories'][0]['Enabled']=False
                if case=='partial': state['errors']=['PRIVATE RAW DIAGNOSTIC']
                return ''
            if 'set' in args:
                state['files'].append(dict(path='/etc/apt/sources.list.d/public.sources',repositories=[repository('pbs-no-subscription')]))
                return ''
            return json.dumps(state)
        with tempfile.TemporaryDirectory(prefix='pbs-policy-i18n-') as folder:
            module.BASE=Path(folder)
            (module.BASE/'lang').mkdir()
            (module.BASE/'config.json').write_text(json.dumps({'language':language}))
            catalog=(ROOT/'lang/sk.json').read_text() if malformed is None else malformed
            (module.BASE/'lang/sk.json').write_text(catalog)
            stdout,stderr=io.StringIO(),io.StringIO()
            suite='sid' if case=='unsupported' else 'trixie'
            with patch.object(module,'run',side_effect=run), patch.object(module.sys,'argv',['repository_policy.py',mode,suite,product]), contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):
                result=module.main()
            return result,stdout.getvalue(),stderr.getvalue(),calls,state,original

    def test_pbs_errors_are_localized_without_changing_decisions_or_exposing_raw_data(self):
        expectations={'inventory':'Zoznam repozitárov APT', 'status':'Stav predplatného',
                      'suite':'iné vydanie', 'active':'aktívne predplatné', 'debian':'základný repozitár Debianu',
                      'mixed':'spoločný záznam APT', 'handle':'no-subscription', 'unsupported':'Nepodporované vydanie',
                      'partial':'stav repozitárov je neznámy'}
        for case,expected in expectations.items():
            with self.subTest(case=case):
                result,out,error,calls,state,original=self.run_policy(case,mode='apply' if case=='partial' else 'plan')
                self.assertEqual(result,1); self.assertEqual(out,''); self.assertIn(expected,error)
                self.assertNotIn('PRIVATE',error); self.assertNotIn('credential.invalid',error)
                writes=[c for c in calls if 'create' in c or 'set' in c]
                if case=='partial':
                    self.assertEqual(len(writes),1)
                    self.assertFalse(state['files'][0]['repositories'][0]['Enabled'])
                    self.assertIn('Automatický návrat',error)
                else:
                    self.assertEqual(writes,[]); self.assertEqual(state,original)
                if case=='unsupported': self.assertEqual(calls,[])

    def test_english_error_and_stdout_tokens_remain_compatible(self):
        en=self.run_policy('unsupported',language='en')
        self.assertEqual(en[2],'Unsupported Proxmox suite; no repository changed.\n')
        pve=self.run_policy('unsupported',product='pve')
        self.assertEqual(pve[2],en[2])
        for mode,expected in [('plan','offer\n'),('apply','changed\n')]:
            result,out,error,*_=self.run_policy('offer',mode=mode)
            self.assertEqual((result,out,error),(0,expected,''))
        result,out,error,calls,*_=self.run_policy('preserve',mode='apply')
        self.assertEqual((result,out,error),(0,'preserve\n',''))
        self.assertFalse(any(c[0]=='proxmox-backup-manager' or 'set' in c or 'create' in c for c in calls))

    def test_bad_or_missing_translation_falls_back_to_original_english(self):
        for catalog in ('{}','not json','[]',json.dumps({'Unsupported Proxmox suite; no repository changed.':42}),
                        json.dumps({'Unsupported Proxmox suite; no repository changed.':'{unknown}'})):
            with self.subTest(catalog=catalog):
                result,out,error,calls,*_=self.run_policy('unsupported',malformed=catalog)
                self.assertEqual(result,1);self.assertEqual(out,'');self.assertEqual(calls,[])
                self.assertEqual(error,'Unsupported Proxmox suite; no repository changed.\n')

    def test_translation_cannot_drop_actual_repository_details(self):
        spec=importlib.util.spec_from_file_location('policy_format_fixture',ROOT/'scripts/global/repository_policy.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory(prefix='pbs-policy-format-') as folder:
            module.BASE=Path(folder);(module.BASE/'lang').mkdir()
            (module.BASE/'config.json').write_text('{"language":"sk"}')
            error=module.PolicyError('Inspect {ui}; no repository changed.',ui='Administration > Repositories')
            for invalid in ('Skontrolujte repozitáre.','{ui.__class__}','{other}','{ui:.0}','{ui!r}'):
                (module.BASE/'lang/sk.json').write_text(json.dumps({error.template:invalid}))
                self.assertEqual(module.cli_error(error,'pbs'),str(error))
            for invalid in ('not json','[]','{"language":"../../private"}'):
                (module.BASE/'config.json').write_text(invalid)
                self.assertEqual(module.cli_error(error,'pbs'),str(error))


UPDATE_HARNESS=r'''
BASE_DIR="$FIXTURE"
LANG_DIR="$REPO/lang"
SCRIPT_TITLE='fixture'
TAB='' BGN='' CL='' GN='' BL=''
mkdir -p "$FIXTURE/log" "$FIXTURE/tmp" "$FIXTURE/boot" "$FIXTURE/run"
: > "$FIXTURE/calls"
record() { printf '%s\n' "$*" >> "$FIXTURE/calls"; }
pmx_journal_context() { :; }
pmx_is_pbs() { [[ "$CASE" != pve ]]; }
pmx_platform_field() { [[ "$1" != supported ]] && printf '%s' "$SUITE" || printf true; }
ensure_pbs_repositories() { record repository-plan; return 0; }
dpkg-query() { [[ "$SUITE" == bookworm ]] && printf 3.4.0 || printf 4.0.1; }
apt-cache() { record apt-cache "$@"; printf '  Candidate: 4.0.2\n'; }
df() { printf 'Filesystem 1K-blocks Used Available Use%% Mounted\nfixture 10000 1000 %s 10%% /\n' "$([[ "$CASE" == disk ]] && echo 512000 || echo 4096000)"; }
apt-get() { record apt-get "$@"; [[ "$CASE" != refresh ]]; }
apt() {
    record apt "$@"
    if [[ "$*" == 'list --upgradable' ]]; then
        printf 'Listing...\n'
        [[ "$CASE" == current ]] || printf 'fixture/trixie 1.2 amd64 [upgradable from: 1.1]\n'
        return 0
    fi
    [[ "$CASE" != failure ]]
}
fixture_env() { "$@"; }
APT_ENV='fixture_env'
pmx_format_upgradable() { cat; }
pmx_record_execution() { record journal "$1"; }
pmx_dpkg_changes_since() { :; }
msg_error() { printf '%s\n' "$*"; }
msg_ok() { printf '%s\n' "$*"; }
msg_info2() { printf '%s\n' "$*"; }
msg_warn() { printf '%s\n' "$*"; }
msg_title() { :; }
clear() { :; }
show_proxmenux_logo() { :; }
whiptail() { printf '%s\n' "$*" >> "$FIXTURE/dialog"; [[ "$CASE" != cancel ]]; }
uname() { printf old-kernel; }
touch "$FIXTURE/boot/vmlinuz-new-kernel"
'''


class UpdateCliTests(unittest.TestCase):
    def run_update(self,case,language='sk',suite='trixie'):
        with tempfile.TemporaryDirectory(prefix='pbs-update-i18n-') as folder:
            body=function('scripts/global/update-pbs.sh','update_pbs')
            for old,new in [('/var/log/',folder+'/log/'),('/tmp/proxmenux_screen_capture_',folder+'/tmp/proxmenux_screen_capture_'),('/var/run/',folder+'/run/'),('/boot/',folder+'/boot/')]: body=body.replace(old,new)
            script=UPDATE_HARNESS+function('scripts/utils.sh','translate')+function('scripts/global/common-functions.sh','pmx_confirm_update')+body+'\nupdate_pbs\n'
            result=subprocess.run(['bash','-c',script],capture_output=True,text=True,timeout=15,
                                  env={**os.environ,'REPO':str(ROOT),'FIXTURE':folder,'CASE':case,'LANGUAGE':language,'SUITE':suite})
            files={str(p.relative_to(folder)):p.read_text() for p in Path(folder).rglob('*') if p.is_file()}
            return result,files

    def test_pve_guard_cannot_reach_repository_or_apt_calls(self):
        result,files=self.run_update('pve')
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertEqual(files['calls'],'')
        self.assertFalse(any(name.startswith('log/') for name in files))

    def test_disk_and_upgrade_errors_keep_their_actual_parameters(self):
        result,files=self.run_update('disk')
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertIn('Nedostatok miesta na disku. Dostupné:',result.stdout)
        self.assertIn('500MB',result.stdout)
        self.assertNotIn('apt',files['calls'])
        result,files=self.run_update('failure')
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertIn('Aktualizácia systému zlyhala. Skontrolujte denník:',result.stdout)
        self.assertIn('/log/proxmox-update-',result.stdout)
        self.assertNotIn('autoremove',files['calls'])

    def test_update_status_cancel_refresh_error_and_reboot_notice(self):
        for suite in ('bookworm','trixie'):
            for case in ('current','cancel','refresh','success'):
                with self.subTest(suite=suite,case=case):
                    result,files=self.run_update(case,suite=suite)
                    self.assertEqual(result.returncode,1 if case=='refresh' else 0,result.stderr)
                    if case!='success': self.assertNotIn('full-upgrade',files['calls'])
                    if case=='success': self.assertIn('reštartujte server',result.stdout)
                    if case in ('current','cancel'): self.assertIn('Aktuálna verzia PBS',files['dialog'])


class DialogTests(unittest.TestCase):
    def test_automated_confirmation_and_banner_cancel_do_not_run_actions(self):
        cases=[('scripts/menus/menu_post_install.sh','confirm_automated_script',
                ['repozitár no-subscription','upozornenie na predplatné','pamäť','jadro','sieť']),
               ('scripts/post_install/auto_post_install.sh','remove_subscription_banner',
                ['Proxmox Backup Server – odstránenie upozornenia na predplatné'])]
        for path,name,expected in cases:
            with tempfile.TemporaryDirectory(prefix='pbs-dialog-') as folder:
                script=function('scripts/utils.sh','translate')+function(path,name)+r'''
PMX_ON_PBS=true
LOCAL_SCRIPTS='/fixture/scripts'
clear() { :; }; sleep() { :; }; stop_spinner() { :; }
msg_warn() { printf '%s\n' "$*"; }
bash() { printf forbidden >> "$CAPTURE/actions"; }
register_tool() { printf forbidden >> "$CAPTURE/actions"; }
dialog() { printf '%s\n' "$*" >> "$CAPTURE/dialog"; return 1; }
whiptail() { dialog "$@"; }
'''+name+'\n'
                result=subprocess.run(['bash','-c',script],capture_output=True,text=True,timeout=15,
                                      env={**os.environ,'LANGUAGE':'sk','LANG_DIR':str(ROOT/'lang'),'CAPTURE':folder})
                self.assertEqual(result.returncode,1 if name=='remove_subscription_banner' else 0,result.stderr)
                dialog=(Path(folder)/'dialog').read_text()
                for text in expected:self.assertIn(text,dialog)
                self.assertFalse((Path(folder)/'actions').exists())
                if name=='remove_subscription_banner':self.assertIn('bolo zrušené používateľom',result.stdout)

    def test_community_labels_preserve_dispatch_names_and_translate_display(self):
        script=function('scripts/utils.sh','translate')+function('scripts/menus/menu_post_install.sh','post_install_label')+'\npost_install_label "$1"\n'
        for text,expected in [('Proxmox Backup Server Post Install','nastavenie po inštalácii'),
                              ('Proxmox Backup Server Microcode','mikrokód procesora')]:
            result=subprocess.run(['bash','-c',script,'bash',text],capture_output=True,text=True,timeout=15,
                                  env={**os.environ,'LANGUAGE':'sk','LANG_DIR':str(ROOT/'lang')})
            self.assertEqual(result.returncode,0,result.stderr);self.assertIn(expected,result.stdout)

    def test_failed_apt_hook_check_removes_only_fixture_hook_with_localized_warning(self):
        with tempfile.TemporaryDirectory(prefix='pbs-hook-') as folder:
            script=function('scripts/utils.sh','translate')+function('scripts/global/remove-banner-pve-v3.sh','create_apt_hook')+r'''
apt-config() { return 1; }
msg_warn() { printf '%s\n' "$*"; }
create_apt_hook
'''
            result=subprocess.run(['bash','-c',script],capture_output=True,text=True,timeout=15,
                                  env={**os.environ,'LANGUAGE':'sk','LANG_DIR':str(ROOT/'lang'),'APT_HOOK':folder+'/hook'})
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('Nesprávna syntax hooku APT',result.stdout)
            self.assertFalse((Path(folder)/'hook').exists())
