#!/usr/bin/env python3
"""Offline extracted Bash message contracts; never sources admin scripts."""
import importlib.util, json, pathlib, re, shlex, subprocess, tempfile, unittest
R = pathlib.Path(__file__).resolve().parents[1]
SOURCE = R / 'scripts/share/samba_client.sh'
# Credentials never reach the operational write path in these fixtures.
# Remove its redirection as well as the command: shell redirects before calling.
CREDENTIAL_WRITE = '''                            TEMP_CRED="/tmp/validate_cred_$$"
                            cat > "$TEMP_CRED" << EOF
username=$USERNAME
password=$PASSWORD
EOF'''

def functions():
    source = SOURCE.read_text()
    bounded = source[source.index('validate_guest_access() {'):source.index('select_samba_share() {')]
    assert bounded.count(CREDENTIAL_WRITE) == 1
    return bounded.replace(CREDENTIAL_WRITE, "printf 'FORBIDDEN:credential-write\\n' >&4; exit 91")

def lookup():
    source = (R / 'scripts/utils.sh').read_text()
    return re.search(r'^translate\(\) \{.*?^\}', source, re.M | re.S).group()

def init_fixture(fixture):
    name, status, listing, tests, expected = fixture
    values = {'LIST_STATUS': status, 'LISTING': listing}
    for i in range(3):
        values.update({f'STATUS{i}': tests[i][0] if i < len(tests) else 91,
                       f'OUTPUT{i}': tests[i][1] if i < len(tests) else 'FORBIDDEN:unexpected-share'})
    return '\n'.join(k + '=' + shlex.quote(str(v)) for k, v in values.items())

def run_fixture(fixture, caller=False, extra='', language='en', lang_dir='/nonexistent', tail=None):
    script = PRELUDE + '\n' + lookup() + '\n' + init_fixture(fixture) + '\n' + functions()
    script += '\nLANGUAGE=' + shlex.quote(language) + '\nLANG_DIR=' + shlex.quote(str(lang_dir)) + '\n'
    # jq is the actual parser, constrained to this fixture/catalog only.
    script += '''
jq() {
 [[ "$#" == 6 && "$1" == -r && "$2" == --arg && "$3" == text && "$5" == '.[$text] // empty' && "$6" == "$LANG_DIR/$LANGUAGE.json" ]] || { printf 'FORBIDDEN:jq-args\\n' >&4; exit 91; }
 /usr/bin/jq "$@"
}
'''
    script += extra + '\n'
    call = 'get_samba_credentials' if caller else 'validate_guest_access example.invalid'
    script += tail if tail is not None else call + ' <<< ""\nrc=$?\nprintf "RETURN:%s\\nVALIDATED:%q\\nUSE_GUEST:%s\\n" "$rc" "$VALIDATED_GUEST_SHARES" "$USE_GUEST"\n'
    p = subprocess.run(['/bin/bash', '--noprofile', '--norc'], input=script, text=True,
                       capture_output=True, env={'PATH': '/nonexistent', 'LANG': 'C'}, timeout=5)
    assert p.returncode == 0 and not p.stderr and 'FORBIDDEN:' not in p.stdout, (p.returncode, p.stdout, p.stderr)
    return p.stdout

class GuestOutcomeTests(unittest.TestCase):
    def test_each_replacement_is_emitted(self):
        outputs = '\n'.join(run_fixture(fixture, True) for fixture in FIXTURES)
        for text in (
            'Testing guest listing and share access on server',
            'Guest Listing Failed', 'Guest share listing failed.',
            'Try username and password authentication.', 'No Shares to Test',
            'No disk shares were selected from the guest listing.',
            'Shares selected from guest listing:', 'Guest access test failed for share:',
            'Test output mentions authentication or access denial.',
            'Test output reports permission denied.', 'The guest access test did not succeed.',
            'Guest share access tests failed:',
            'No share access test succeeded with guest authentication.',
            'Samba access setup did not complete.',
        ):
            with self.subTest(message=text):
                self.assertIn(text, outputs)

    def test_outcome_matrix(self):
        for fixture in FIXTURES:
            name, ls, listing, tests, status = fixture
            for caller in (False, True):
                with self.subTest(case=name, caller=caller):
                    out = run_fixture(fixture, caller)
                    self.assertIn(f'RETURN:{status}\n', out)
                    calls = [x for x in out.splitlines() if x.startswith('SMB\t')]
                    self.assertEqual(len(calls), 1 + len(tests))
                    self.assertEqual(calls[0], 'SMB\t-L\texample.invalid\t-N')
                    self.assertEqual(calls[1:], [f'SMB\t//example.invalid/share{i}\t-N\t-c\tls' for i in range(len(tests))])
                    success = [f'share{i}' for i, t in enumerate(tests) if t[0] == 0]
                    encoded = ''.join(x + '\\\\n' for x in success) if success else "''"
                    self.assertIn('VALIDATED:' + encoded + '\n', out)
                    self.assertIn('Testing guest listing and share access on server example.invalid...', out)
                    if ls:
                        self.assertIn('Guest Listing Failed', out)
                        self.assertIn('Guest share listing failed.', out)
                        self.assertNotIn('Guest share listing successful', out)
                        if name == 'listing-error-denial-text':
                            self.assertIn('Try username and password authentication.', out)
                            self.assertNotIn('Error details:', out)
                        else:
                            self.assertIn('Error details:', out)
                    elif not tests:
                        self.assertIn('No Shares to Test', out)
                        self.assertIn('No disk shares were selected from the guest listing.', out)
                    else:
                        self.assertIn(f'Shares selected from guest listing: {len(tests)}', out)
                        self.assertLess(out.index('Shares selected from guest listing:'), out.index('SMB\t//'))
                        self.assertIn(f'Shares found: {len(tests)}', out)
                        self.assertIn(f'Guest accessible: {len(success)}', out)
                        self.assertIn(f'Guest share access tests failed: {len(tests) - len(success)}', out)
                        for i, (rc, diagnostic) in enumerate(tests):
                            label = 'Guest access confirmed for share:' if rc == 0 else 'Guest access test failed for share:'
                            self.assertIn(f'{label} share{i}', out)
                            self.assertLess(out.index(f'SMB\t//example.invalid/share{i}'), out.index(f'{label} share{i}'))
                        if success:
                            self.assertIn('Guest access validated successfully!', out)
                            self.assertNotIn('No share access test succeeded', out)
                        else:
                            self.assertIn('No share access test succeeded with guest authentication.', out)
                            self.assertIn('Try username and password authentication.', out)
                    if name == 'failed-auth-text':
                        self.assertIn('Test output mentions authentication or access denial.', out)
                    if name in ('failed-status-token', 'all-failed-generic'):
                        self.assertIn('The guest access test did not succeed.', out)
                        self.assertNotIn('Test output mentions authentication', out)
                    if name == 'partial':
                        self.assertIn('Test output reports permission denied.', out)
                    if caller:
                        self.assertEqual('Samba access setup did not complete.' in out, status == 1)
                        self.assertIn(f'USE_GUEST:{str(status == 0).lower()}', out)

    def test_retry_yes_new_selection_then_cancel(self):
        # Each menu is a subshell: consume choices from an inherited FD, not a
        # variable counter that would reset at every command substitution.
        extra = '''
exec 5<<< $'2\\n1\\ncancel'
whiptail() {
 { printf 'DIALOG'; printf '\\t%s' "$@"; printf '\\n'; } >&4
 if [[ "$1" == --title && "$2" == 'Samba Credentials' ]]; then
   IFS= read -r next <&5
   [[ "$next" != cancel ]] || return 1
   printf '%s' "$next" >&2; return 0
 fi
 [[ "$1" != --inputbox ]] || return 1
 return 0
}
'''
        out = run_fixture(FIXTURES[0], True, extra)
        self.assertIn('RETURN:1', out)
        self.assertEqual(out.count('Samba access setup did not complete.'), 2)
        self.assertEqual(out.count('DIALOG\t--title\tSamba Credentials'), 3)
        self.assertIn('Enter username for Samba server:', out)
        self.assertIn('USE_GUEST:false', out)
        self.assertEqual(out.count('SMB\t'), 1)

    def test_real_translation_and_extractor(self):
        spec = importlib.util.spec_from_file_location('cache_builder', R / '.github/scripts/build_translation_cache.py')
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        discovered = set(builder.extract_translate_texts(R / 'scripts/share'))
        keys = set(re.findall(r'translate "([^"\n]+)"', functions()))
        self.assertTrue(keys <= discovered)
        with tempfile.TemporaryDirectory(prefix='samba-guest-lookup-') as directory:
            lang_dir = pathlib.Path(directory)
            (lang_dir / 'missing.json').write_text('{}')
            synthetic = {key: 'SYNTHETIC ' + key + ' translated' for key in keys}
            (lang_dir / 'xx.json').write_text(json.dumps(synthetic))
            shipped = json.loads((R / 'lang/it.json').read_text())
            for language, location, catalog in (
                ('en', lang_dir, {}), ('absent', lang_dir, {}),
                ('missing', lang_dir, {}), ('it', R / 'lang', shipped),
                ('xx', lang_dir, synthetic),
            ):
                # Directly check every lookup using the actual Bash function.
                calls = '\n'.join('translate ' + shlex.quote(key) for key in sorted(keys))
                expected = '\n'.join(catalog.get(key) or key for key in sorted(keys)) + '\n'
                with self.subTest(language=language, scope='lookup'):
                    self.assertEqual(run_fixture(FIXTURES[0], language=language,
                                                 lang_dir=location, tail=calls), expected)
                for fixture in FIXTURES:
                    for caller in (False, True):
                        with self.subTest(language=language, case=fixture[0], caller=caller):
                            baseline = run_fixture(fixture, caller)
                            out = run_fixture(fixture, caller, language=language, lang_dir=location)
                            # Replace complete literals longest-first, once in a regex pass:
                            # substitutions cannot recursively retranslate synthetic values.
                            pattern = '|'.join(re.escape(key) for key in sorted(keys, key=len, reverse=True))
                            expected = re.sub(pattern, lambda match: catalog.get(match[0]) or match[0], baseline)
                            self.assertEqual(out, expected)

    def test_noncompleted_password_path(self):
        extra = '''
exec 5<<< $'fixture-user-not-a-secret\\ncancel'
exec 6<<< $'fixture-password-not-a-secret\\ncancel\\ncancel'
whiptail() {
 { printf 'DIALOG'; printf '\\t%s' "$@"; printf '\\n'; } >&4
 if [[ "$1" == --title && "$2" == 'Samba Credentials' ]]; then printf '1' >&2; return 0; fi
 if [[ "$1" == --inputbox ]]; then
   IFS= read -r next <&5
   [[ "$next" != cancel ]] || return 1
   printf '%s' "$next" >&2; return 0
 fi
 if [[ "$1" == --passwordbox ]]; then
   IFS= read -r next <&6
   [[ "$next" != cancel ]] || return 1
   printf '%s' "$next" >&2; return 0
 fi
 [[ "$1" != --yesno ]] || return 1
 printf 'FORBIDDEN:dialog\\n' >&4; return 91
}
'''
        out = run_fixture(FIXTURES[0], True, extra)
        self.assertIn('Enter password for fixture-user-not-a-secret:', out)
        self.assertIn('Confirm password for fixture-user-not-a-secret:', out)
        self.assertNotIn('fixture-password-not-a-secret', out)
        self.assertIn('Samba access setup did not complete.', out)
        self.assertIn('RETURN:1', out)
        self.assertNotIn('SMB\t', out)
        self.assertNotIn('Authentication failed.', out)

PRELUDE = r'''
set -u
export PATH=/nonexistent
exec 4>&1
command_not_found_handle() { printf 'FORBIDDEN:%s\n' "$*" >&4; return 127; }
show_proxmenux_logo() { :; }
cleanup() { :; }
clear() { :; }
sleep() { [[ "$*" == 1 || "$*" == 2 ]] || { printf 'FORBIDDEN:sleep\n' >&4; exit 91; }; }
awk() { [[ "$#" == 1 && "$1" == '/Disk/ && !/IPC\$/ && !/ADMIN\$/ && !/print\$/ {print $1}' ]] || { printf 'FORBIDDEN:awk\n' >&4; exit 91; }; /usr/bin/awk "$@"; }
grep() { [[ "$#" == 2 && ( "$*" == '-v ^$' || "$*" == '-qi access denied\|logon failure' || "$*" == '-qi access denied\|logon failure\|authentication' || "$*" == '-qi permission denied' ) ]] || { printf 'FORBIDDEN:grep\n' >&4; exit 91; }; /usr/bin/grep "$@"; }
wc() { [[ "$*" == '-l' ]] || { printf 'FORBIDDEN:wc\n' >&4; exit 91; }; /usr/bin/wc "$@"; }
head() { [[ "$*" == '-3' ]] || { printf 'FORBIDDEN:head\n' >&4; exit 91; }; /usr/bin/head "$@"; }
whiptail() {
 { printf 'DIALOG'; printf '\t%s' "$@"; printf '\n'; } >&4
 if [[ "$1" == --title && "$3" == --menu ]]; then printf '2' >&2; return 0; fi
 if [[ "$1" == --yesno ]]; then return 1; fi
 return 0
}
smbclient() {
 { printf 'SMB'; printf '\t%s' "$@"; printf '\n'; } >&4
 if [[ "$#" == 4 && "$1" == -L && "$2" == example.invalid && "$3" == -N ]]; then printf 'FORBIDDEN:argc\n' >&4; exit 91; fi
 if [[ "$#" == 3 && "$*" == '-L example.invalid -N' ]]; then printf '%s' "$LISTING"; return "$LIST_STATUS"; fi
 if [[ "$#" == 4 && "$1" == //example.invalid/share* && "$2" == -N && "$3" == -c && "$4" == ls ]]; then
   case "$1" in
    //example.invalid/share0) printf '%s' "$OUTPUT0"; return "$STATUS0";;
    //example.invalid/share1) printf '%s' "$OUTPUT1"; return "$STATUS1";;
    //example.invalid/share2) printf '%s' "$OUTPUT2"; return "$STATUS2";;
   esac
 fi
 printf 'FORBIDDEN:smbclient:%s\n' "$*" >&4; exit 91
}
TAB='' BGN='' CL='' BL='' GN='' YW='' BOLD=''
VALIDATED_GUEST_SHARES='' SAMBA_SERVER=example.invalid USE_GUEST=false

msg_info() { printf "msg_info:%s\n" "$*" >&4; }

msg_info2() { printf "msg_info2:%s\n" "$*" >&4; }

msg_ok() { printf "msg_ok:%s\n" "$*" >&4; }

msg_error() { printf "msg_error:%s\n" "$*" >&4; }

msg_warn() { printf "msg_warn:%s\n" "$*" >&4; }

msg_success() { printf "msg_success:%s\n" "$*" >&4; }
'''
FIXTURES = [('listing-empty', 0, '', [], 1),
 ('listing-filtered-only', 0, 'IPC$ IPC fixture\nADMIN$ Disk fixture\nprint$ Disk fixture', [], 1),
 ('listing-error-generic', 1, 'Connection timed out', [], 1),
 ('listing-error-denial-text', 1, 'access denied', [], 1),
 ('listing-error-status-token', 1, 'NT_STATUS_ACCESS_DENIED', [], 1),
 ('one-success', 0, 'share0 Disk fixture', [(0, '')], 0),
 ('three-success',
  0,
  'share0 Disk fixture\nshare1 Disk fixture\nshare2 Disk fixture',
  [(0, ''), (0, ''), (0, '')],
  0),
 ('partial',
  0,
  'share0 Disk fixture\nshare1 Disk fixture\nshare2 Disk fixture',
  [(0, ''), (1, 'Connection timed out'), (1, 'permission denied')],
  0),
 ('all-failed-generic',
  0,
  'share0 Disk fixture\nshare1 Disk fixture\nshare2 Disk fixture',
  [(1, 'Connection timed out'), (1, 'Connection timed out'), (1, 'Connection timed out')],
  1),
 ('failed-auth-text', 0, 'share0 Disk fixture', [(1, 'authentication service unavailable')], 1),
 ('failed-status-token', 0, 'share0 Disk fixture', [(1, 'NT_STATUS_LOGON_FAILURE')], 1),
 ('listing-nonzero-with-disk', 1, 'share0 Disk fixture', [], 1)]

if __name__ == '__main__':
    unittest.main()
