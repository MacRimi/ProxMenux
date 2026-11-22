"""Compose inputs are explicit, deterministic, and never taken from the host."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from proxmenux_oci.compose_input import Interpolator, dotenv, prepare, resolve_document
from proxmenux_oci.converter import ConversionError
from proxmenux_oci.custom import template_from_compose, _dump


class ComposeInputs(unittest.TestCase):
    def test_default_required_alternative_nested_and_escaped_dollar(self):
        expand = Interpolator({'EMPTY': '', 'SET': 'value'}).expand
        for source, expected in [
            ('${MISSING:-fallback}', 'fallback'), ('${EMPTY:-fallback}', 'fallback'),
            ('${EMPTY-fallback}', ''), ('${SET:+yes}', 'yes'), ('${MISSING+yes}', ''),
            ('${EMPTY+yes}', 'yes'), ('${MISSING:-${SET}}', 'value'),
            ('$$HOME $SET ${SET}', '$HOME value value'), ('$5', '$5')]:
            with self.subTest(source=source):
                self.assertEqual(expand(source), expected)
        for source in ['${MISSING?needed}', '${EMPTY:?needed}', '${NO}', '${BAD', '${X:=bad}']:
            with self.subTest(source=source), self.assertRaises(ConversionError):
                expand(source)

    def test_never_reads_host_environment(self):
        with patch.dict(os.environ, {'COMPOSE_SECRET': 'must-not-inherit'}):
            with self.assertRaises(ConversionError):
                Interpolator().expand('${COMPOSE_SECRET}')

    def test_dotenv_quotes_comments_interpolation_and_no_shell_execution(self):
        parsed = dotenv('''A=hello
B="${A} world" # note
C='literal$NO'
D=unquoted # comment
E=$(touch /tmp/should-not-exist)
F=
G
''', Interpolator())
        self.assertEqual(parsed['B'], 'hello world')
        self.assertEqual(parsed['C'], 'literal$NO')
        self.assertEqual(parsed['D'], 'unquoted')
        self.assertEqual(parsed['E'], '$(touch /tmp/should-not-exist)')
        self.assertEqual(parsed['F'], '')
        self.assertIsNone(parsed['G'])
        for text in ['NOT A KEY=value', 'A="x" junk', "A='unterminated"]:
            with self.subTest(text=text), self.assertRaises(ConversionError):
                dotenv(text, Interpolator())

    def test_file_merge_order_and_environment_override(self):
        doc = {'services': {'app': {'image': 'example:${VERSION:-stable}',
               'env_file': ['first.env', {'path':'optional.env', 'required':False}, 'second.env'],
               'environment': {'A':'explicit', 'B':None}}}}
        result = resolve_document(doc, {'B':'inherited-explicitly'},
                                  {'first.env':'A=one\nB=first\nC=first', 'second.env':'C=second'})
        self.assertEqual(result['services']['app']['image'], 'example:stable')
        self.assertEqual(result['services']['app']['environment'],
                         {'A':'explicit', 'B':'inherited-explicitly', 'C':'second'})
        self.assertNotIn('env_file', result['services']['app'])
        self.assertIn('env_file', doc['services']['app'])

    def test_unset_bare_variables_are_removed_and_optional_file_is_not_prompted(self):
        class UI:
            def ask(self, *args, **kwargs): raise AssertionError('Optional input must not be required')
        document={'services': {'app': {'image':'example:1', 'env_file':[{'path':'missing.env','required':False}],
                                       'environment':['UNSET', 'EMPTY=']}}}
        with tempfile.TemporaryDirectory() as directory:
            result=prepare(UI(),document,directory)
        self.assertEqual(result['services']['app']['environment'],{'EMPTY':''})

    def test_single_quoted_escape_and_dollar_value_are_literal(self):
        self.assertEqual(dotenv("PASSWORD='it\\'s$literal'", Interpolator())['PASSWORD'],"it's$literal")

    def test_selinux_mount_labels_are_normalized_with_explicit_host_guard_metadata(self):
        class UI:
            def ask(self,*args,**kwargs): raise AssertionError('No input required')
        doc={'services':{'app':{'image':'example:1','volumes':['shared:/data:ro,z']},
                         'worker':{'image':'example:1','volumes':['shared:/data:Z']}}}
        metadata={}
        result=prepare(UI(),doc,metadata=metadata)
        self.assertTrue(metadata['selinux_labels'])
        self.assertEqual(result['services']['app']['volumes'],[{'source':'shared','target':'/data','read_only':True}])
        self.assertEqual(result['services']['worker']['volumes'][0]['read_only'],False)
        template=template_from_compose(_dump({'services':{'app':{'image':'adminer:4','ports':['8080:8080']},
                    'db':{'image':'postgres:16','environment':{'POSTGRES_PASSWORD':'test-only'}}}}),
                    interpolated=True,input_metadata=metadata)
        self.assertTrue(template['proxmox']['custom_compose_selinux_labels'])

    def test_literal_secret_is_not_expanded_again_by_stack_compiler(self):
        document = {'services': {'db': {'image':'postgres:16',
                    'environment':{'POSTGRES_PASSWORD':'${PASSWORD}'}},
                    'app':{'image':'adminer:4','ports':['8080:8080'],
                           'environment':{'DATABASE_URL':'postgres://user:${PASSWORD}@db/test'}}}}
        resolved = resolve_document(document, {'PASSWORD':'literal$PASSWORD${ALSO_LITERAL}'})
        template = template_from_compose(_dump(resolved), interpolated=True)
        self.assertTrue(template['compatibility']['automatic_install_candidate'], template['compatibility'])
        db = next(s for s in template['compose_stack']['services'] if s['name']=='db')
        self.assertEqual(db['compose']['environment']['POSTGRES_PASSWORD'], 'literal$PASSWORD${ALSO_LITERAL}')

    def test_companion_dotenv_and_env_file_read_from_explicit_source_directory(self):
        class UI:
            def ask(self, *args, **kwargs):
                raise AssertionError('No extra input needed for supplied companion files')
            password = ask
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, '.env').write_text('VERSION=16\nPASSWORD=test-only\n')
            Path(directory, 'db.env').write_text('POSTGRES_PASSWORD=${PASSWORD}\n')
            doc = {'services':{'db':{'image':'postgres:${VERSION}', 'env_file':'db.env'},
                               'app':{'image':'adminer:4','ports':['8080:8080']}}}
            result = prepare(UI(), doc, directory)
        self.assertEqual(result['services']['db']['image'], 'postgres:16')
        self.assertEqual(result['services']['db']['environment']['POSTGRES_PASSWORD'], 'test-only')

    def test_missing_values_are_asked_once_and_secrets_use_password_input(self):
        class UI:
            def __init__(self): self.prompts=[]
            def ask(self, prompt, default='', **kwargs):
                return ''
            def password(self, prompt, **kwargs):
                self.prompts.append(prompt); return 'synthetic-secret'
        ui=UI()
        doc={'services':{'one':{'image':'example:1','environment':{'PASSWORD':'${PASSWORD}'}},
                         'two':{'image':'example:2','environment':{'PASSWORD':'${PASSWORD}'}}}}
        result=prepare(ui,doc)
        self.assertEqual(len(ui.prompts),1)
        self.assertEqual(result['services']['one']['environment'],result['services']['two']['environment'])


if __name__ == '__main__': unittest.main()
