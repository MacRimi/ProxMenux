"""Real translate and display-only shell calls; never source a VM creator."""
from pathlib import Path
import importlib.util,json,os,re,shlex,subprocess,tempfile,unittest
from html.parser import HTMLParser

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('official_i18n',ROOT/'.github/scripts/build_translation_cache.py')
OFFICIAL=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(OFFICIAL)
TRANSLATE=re.search(r'(?ms)^translate\(\) \{.*?^\}',(ROOT/'scripts/utils.sh').read_text()).group()
FILES=('scripts/vm/synology.sh','scripts/utilities/uup_dump_iso_creator.sh')
DISPLAY=re.compile(r'^\s*(?:msg_(?:info2?|ok|warn|error|success|title)|echo -[en])\s+".*"\s*(?:>&2)?\s*$')

def display_calls(source):
    return [line for line in source.splitlines() if DISPLAY.fullmatch(line) and not re.search(r'\$\((?!(?:translate|printf|basename)\b)',line)]

def render(calls,language):
    with tempfile.TemporaryDirectory(prefix='remaining-sk-display-') as tmp:
        blocked=Path(tmp)/'blocked';blocked.write_text('')
        definitions='\n'.join(name+'() { printf "%s\\n" "$1"; }' for name in ('msg_info','msg_info2','msg_ok','msg_warn','msg_error','msg_success','msg_title'))
        forbidden='\n'.join(name+'() { echo '+shlex.quote(name)+' >> '+shlex.quote(str(blocked))+'; return 97; }' for name in ('qm','pct','pvesh','apt-get','curl','wget','mount','reboot','systemctl','rm','touch','mkdir','chmod'))
        values={'NAME':'Synology VM','VMID':'999','IMAGES_DIR':'/fixture/images','EFI_STORAGE':'efi-store','LOADER_STORAGE':'loader-store','STORAGE':'data-store','STORAGE_TYPE':'zfspool','LOADER_NAME':'Arc','LOADER_FILE':'/fixture/loader.img','FILE':'loader.img','DISK_NUM':'2','SATA_ID':'sata2','SIZE':'32','DISK_MODEL':'Fixture SSD','DISK_SIZE':'32G','DISK_ID':'sata3','DISK':'/dev/fixture','PCI_DEV':'0000:01:00.0','HOSTPCI_INDEX':'0','HN':'fixture-vm','CORE_COUNT':'2','RAM_SIZE':'4096','BRG':'vmbr0','MAC':'02:00:00:00:00:01','VLAN1':'Default','MTU1':'Default','SERIAL_PORT':'socket','START_VM':'no','MACH':'q35','OUT_DIR':'/fixture/iso','BUILD_ID':'fixture','EDITION':'professional','ARCH':'amd64','DEFAULT_TMP':'/fixture/tmp','TMP_DIR':'/fixture/tmp','ISO_FILE':'fixture.iso','user_path':'/fixture'}
        catalog={} if language=='en' else json.loads((ROOT/'lang'/f'{language}.json').read_text())
        values.update({key:catalog.get('Default','Default') for key in ('VLAN1','MTU1')})
        assignments='\n'.join(key+'='+shlex.quote(value) for key,value in values.items())
        script='LANGUAGE='+shlex.quote(language)+'\nLANG_DIR='+shlex.quote(str(ROOT/'lang'))+'\n'+TRANSLATE+'\n'+definitions+'\n'+forbidden+'\n'+assignments+'\n'+'\n'.join(calls)+'\n'
        result=subprocess.run(['bash','-c',script],text=True,capture_output=True,timeout=15,check=True)
        assert blocked.read_text()==''
        return result.stdout+result.stderr

class RemainingCliI18n(unittest.TestCase):
    def test_badges_remain_valid_with_hostile_translations_without_host_calls(self):
        source=(ROOT/FILES[0]).read_text()
        html=re.search(r'(?ms)^HTML_DESC=".*?^</div>"',source).group()
        class Images(HTMLParser):
            def __init__(self):super().__init__();self.images=[]
            def handle_starttag(self,tag,attrs):
                if tag=='img':self.images.append(dict(attrs))
        with tempfile.TemporaryDirectory() as tmp:
            blocked=Path(tmp)/'blocked';blocked.write_text('')
            forbidden='\n'.join(name+'(){ echo '+shlex.quote(name)+' >> '+shlex.quote(str(blocked))+'; return 97; }' for name in ('qm','pct','pvesh','curl','wget','mount','reboot','systemctl'))
            script=forbidden+'\ntranslate(){ printf "%s" "O\'Brien & <label> / ? #"; }; LOADER_URL=https://fixture.invalid/loader; LOADER_NAME=fixture; DISK_INFO=;\n'+html+'\nprintf "%s" "$HTML_DESC"'
            result=subprocess.run(['bash','-c',script],text=True,capture_output=True,timeout=10,check=True)
            self.assertEqual(blocked.read_text(),'')
            parser=Images();parser.feed(result.stdout)
            badges=[image for image in parser.images if image.get('src','').startswith('https://img.shields.io/')]
            self.assertEqual([badge.get('alt') for badge in badges],['Docs','Code','Loader','Ko-fi'])
            for badge in badges:
                self.assertNotIn('Brien',badge['src'])
                self.assertNotIn('<label>',badge['src'])
    def test_real_default_and_advanced_wizard_cancel_before_host_calls(self):
        source=(ROOT/'scripts/vm/synology.sh').read_text()
        functions='\n'.join(re.search(r'(?ms)^function '+name+r'\(\) \{.*?^\}',source).group() for name in ('default_settings','select_disk_type','_build_storage_plan_summary','advanced_settings','exit_script'))
        for action in ('default_settings','advanced_settings'):
            with tempfile.TemporaryDirectory(prefix='remaining-sk-cancel-') as tmp:
                blocked=Path(tmp)/'blocked';blocked.write_text('');dialog_log=Path(tmp)/'dialog';dialog_log.write_text('')
                forbidden='\n'.join(name+'() { echo '+shlex.quote(name)+' >> '+shlex.quote(str(blocked))+'; return 97; }' for name in ('qm','pct','pvesh','pvesm','curl','wget','apt-get','mount','systemctl','reboot','select_loader'))
                script='LANGUAGE=sk\nLANG_DIR='+shlex.quote(str(ROOT/'lang'))+'\n'+TRANSLATE+'\n'+forbidden+'\n'+functions+'\nclear(){ :; }; sleep(){ :; }; header_info(){ :; }; msg_warn(){ echo "$1"; }; whiptail(){ printf "%s\\n" "$*" >> '+shlex.quote(str(dialog_log))+'; return 1; }; NAME="Synology VM"; NEXTID=999; GEN_MAC="02:00:00:00:00:01"; '+action
                result=subprocess.run(['bash','-c',script],text=True,capture_output=True,timeout=10)
                self.assertEqual(blocked.read_text(),'')
                self.assertIn('Zrušiť' if action=='default_settings' else 'Ukončiť skript',dialog_log.read_text())
                self.assertNotIn('command not found',result.stderr)
    def test_generated_uup_helper_is_localized_and_valid_without_execution(self):
        source=(ROOT/FILES[1]).read_text();body=source.split('cat > uup_download_linux.sh <<EOF\n',1)[1].split('\nEOF',1)[0]
        script='LANGUAGE=sk\nLANG_DIR='+shlex.quote(str(ROOT/'lang'))+'\n'+TRANSLATE+'\ncat <<EOF\n'+body+'\nEOF\n'
        generated=subprocess.check_output(['bash','-c',script],text=True,timeout=10)
        self.assertIn('Príkaz sa nenašiel.',generated);self.assertIn('Vytvorenie zoznamu súborov UUP',generated)
        subprocess.run(['bash','-n'],input=generated,text=True,check=True)
    def test_slovak_display_errors_without_host_calls(self):
        for file in FILES:
            translated=render(display_calls((ROOT/file).read_text()),'sk')
            if file.endswith('synology.sh'):
                self.assertIn('Priradenie disku 2 (sata2) na data-store zlyhalo',translated)
                self.assertIn('Nenašlo sa použiteľné úložisko.',translated)
                self.assertNotIn('Failed to configure EFI disk',translated)
                self.assertIn('/fixture/images',translated)
                self.assertIn('Veľkosť MTU rozhrania: Predvolené',translated)
                self.assertNotIn('Default',translated)
    def test_official_extractor_and_placeholders(self):
        catalog=json.loads((ROOT/'lang/sk.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            keys=OFFICIAL.extract_translate_texts(Path(tmp),[ROOT/file for file in FILES])
        self.assertGreater(len(keys),90)
        self.assertEqual([key for key in keys if not catalog.get(key)],[])
        for key in keys:
            self.assertEqual(re.findall(r'%(?:[0-9]+\$)?[sd]',key),re.findall(r'%(?:[0-9]+\$)?[sd]',catalog[key]),key)
        self.assertEqual(catalog['Boot disk:'],'Zavádzací disk:')
        self.assertEqual(catalog['Mount point:'],'Bod pripojenia:')
    def test_shell_syntax(self):
        for file in FILES:subprocess.run(['bash','-n',str(ROOT/file)],check=True)

if __name__=='__main__':unittest.main()
