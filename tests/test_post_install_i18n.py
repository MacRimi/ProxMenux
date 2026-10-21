"""Run the real wrapper only against inert flow scripts and temporary markers."""
from pathlib import Path
import os,re,shlex,subprocess,tempfile,unittest

ROOT=Path(__file__).resolve().parents[1]
FILE='scripts/post_install/update_post_install_function.sh'
TRANSLATE=re.search(r'(?ms)^translate\(\) \{.*?^\}',(ROOT/'scripts/utils.sh').read_text()).group()

def run(source,params,language='en',utilities=True):
    with tempfile.TemporaryDirectory(prefix='postinstall-i18n-') as temp:
        tmp=Path(temp);base=tmp/'base';flow=base/'scripts/post_install';flow.mkdir(parents=True)
        trace=tmp/'trace';trace.write_text('');blocked=tmp/'blocked';blocked.write_text('')
        for name in ('auto_post_install.sh','customizable_post_install.sh'):
            (flow/name).write_text('fixture_ok() { echo ok >> "$FIXTURE_TRACE"; return 0; }\nfixture_fail() { echo fail >> "$FIXTURE_TRACE"; return 7; }\n')
        if utilities:
            (base/'utils.sh').write_text('load_language(){ LANGUAGE="$FIXTURE_LANG"; }; initialize_cache(){ :; }; show_proxmenux_logo(){ :; }; LANG_DIR='+shlex.quote(str(ROOT/'lang'))+'\n'+TRANSLATE+'\n'+'\n'.join(name+'(){ printf "%s\\n" "$1"; }' for name in ('msg_info2','msg_error','msg_ok','msg_warn','msg_success'))+'\n')
        binary=tmp/'bin';binary.mkdir()
        for name in ('qm','pct','pvesh','pvesm','apt-get','curl','wget','mount','systemctl','reboot'):
            p=binary/name;p.write_text('#!/bin/sh\necho '+shlex.quote(name)+' >> "$FIXTURE_BLOCKED"\nexit 97\n');p.chmod(0o755)
        rewritten=source.replace('/usr/local/share/proxmenux',str(base)).replace('/var/run/proxmenux-update-',str(tmp/'proxmenux-update-'))
        script=tmp/'wrapper.sh';script.write_text(rewritten)
        env={**os.environ,'PATH':str(binary)+':'+os.environ['PATH'],'FIXTURE_TRACE':str(trace),'FIXTURE_BLOCKED':str(blocked),'FIXTURE_LANG':language,'SOURCE_TYPE':'','FUNCTION_NAME':'','TOOL_KEY':'','FUNCTIONS_BATCH':'',**params}
        result=subprocess.run(['bash',str(script)],input='\n',text=True,capture_output=True,env=env,timeout=10)
        assert blocked.read_text()=='','Forbidden host command'
        assert not (tmp/'proxmenux-update-in-progress').exists(),'Marker cleanup'
        return result.returncode,result.stdout+result.stderr,trace.read_text()

class PostInstallI18n(unittest.TestCase):
    def test_existing_single_batch_failures_and_fallback_contract(self):
        before=(ROOT/'tests/fixtures/cli-before-i18n/update_post_install_function.sh').read_text();after=(ROOT/FILE).read_text()
        cases=[{}, {'SOURCE_TYPE':'auto','FUNCTION_NAME':'fixture_ok','TOOL_KEY':'fixture'}, {'SOURCE_TYPE':'detected','FUNCTION_NAME':'fixture_ok','TOOL_KEY':'fixture'}, {'SOURCE_TYPE':'custom','FUNCTION_NAME':'missing_fn','TOOL_KEY':'fixture'}, {'SOURCE_TYPE':'wrong','FUNCTION_NAME':'fixture_ok'}, {'FUNCTIONS_BATCH':'auto:fixture_ok:one\ncustom:fixture_fail:two\nauto:missing_fn:three\ndetected:fixture_ok:four'}]
        for utilities in (False,True):
            for params in cases:
                with self.subTest(utilities=utilities,params=params):self.assertEqual(run(before,params,utilities=utilities),run(after,params,utilities=utilities))
    def test_slovak_missing_failure_summary_and_no_real_host_calls(self):
        source=(ROOT/FILE).read_text()
        code,text,trace=run(source,{'FUNCTIONS_BATCH':'auto:fixture_ok:one\ncustom:fixture_fail:two\nauto:missing_fn:three'},language='sk')
        self.assertEqual(code,1);self.assertEqual(trace,'ok\nfail\n')
        self.assertIn('Aktualizácia one je dokončená.',text)
        self.assertIn('Aktualizácia two skončila s návratovým kódom 7.',text)
        self.assertIn("Funkcia 'missing_fn' nie je definovaná v postupe auto.",text)
        self.assertIn('Zlyhalo 2 z 3 aktualizácií',text)
        self.assertIn('Stlač Enter na zatvorenie terminálu',text)
    def test_syntax(self):subprocess.run(['bash','-n',str(ROOT/FILE)],check=True)

if __name__=='__main__':unittest.main()
