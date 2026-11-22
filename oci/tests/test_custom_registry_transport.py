"""Registry queries accept pinned tag@digest images without rewriting recipes."""
from pathlib import Path
import json
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from proxmenux_oci import custom
from proxmenux_oci.converter import ConversionError

DIGEST = 'sha256:' + 'a' * 64
REFERENCE = 'registry.test:5443/team/app:release@' + DIGEST
LOOKUP = 'registry.test:5443/team/app@' + DIGEST

class CustomRegistryTransportTests(unittest.TestCase):
    def test_existing_image_parser_keeps_ports_and_pinned_digest(self):
        pairs = [(REFERENCE, LOOKUP), ('[::1]:5443/team/app:release@' + DIGEST,
                                      '[::1]:5443/team/app@' + DIGEST),
                 ('alpine:3', 'alpine:3'), ('registry.test:5443/team/app', 'registry.test:5443/team/app'),
                 ('ghcr.io/team/app@' + DIGEST, 'ghcr.io/team/app@' + DIGEST)]
        for written, expected in pairs:
            with self.subTest(written=written):
                self.assertEqual(custom._registry_lookup(written), expected)

    def test_registry_report_normalizes_raw_and_platform_detail_queries(self):
        responses = [SimpleNamespace(returncode=0, stdout='{"schemaVersion":2}'),
                     SimpleNamespace(returncode=0, stdout='{"Architecture":"amd64"}')]
        with patch.object(custom.subprocess, 'run', side_effect=responses) as run:
            available, report = custom.registry_report(REFERENCE)
        self.assertTrue(available)
        self.assertIn('amd64', report)
        self.assertEqual([call.args[0][-1] for call in run.call_args_list], ['docker://' + LOOKUP] * 2)

    def test_failed_registry_report_keeps_the_written_reference(self):
        with patch.object(custom.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stdout='')):
            available, report = custom.registry_report(REFERENCE)
        self.assertFalse(available)
        self.assertIn(REFERENCE, report)

    def test_image_metadata_cache_and_entrypoint_identity_keep_written_reference(self):
        document = {'services': {'worker': {'image': REFERENCE}, 'worker2': {'image': REFERENCE}}}
        defaults = {'config': {'Entrypoint': ['image-entrypoint'], 'ExposedPorts': {'8080/tcp': {}},
                               'Healthcheck': {'Test': ['CMD', 'healthcheck']}}}
        entrypoints = {}
        with patch.object(custom.subprocess, 'run', return_value=SimpleNamespace(
                returncode=0, stdout=json.dumps(defaults))) as run:
            enriched = custom.enrich_image_defaults(None, document, image_entrypoints=entrypoints)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][-1], 'docker://' + LOOKUP)
        self.assertEqual(entrypoints, {REFERENCE: ['image-entrypoint']})
        self.assertTrue(all(service['image'] == REFERENCE for service in enriched['services'].values()))
        self.assertEqual(enriched['services']['worker']['healthcheck']['test'], ['CMD', 'healthcheck'])

    def test_image_to_compose_queries_digest_but_preserves_written_image(self):
        with patch.object(custom.subprocess, 'run', return_value=SimpleNamespace(
                returncode=0, stdout='{"config":{}}')) as run:
            document = yaml.safe_load(custom.compose_from_image(REFERENCE))
        self.assertEqual(run.call_args.args[0][-1], 'docker://' + LOOKUP)
        self.assertEqual(next(iter(document['services'].values()))['image'], REFERENCE)

    def test_private_registry_refusal_uses_the_same_transport(self):
        with patch.object(custom.subprocess, 'run', return_value=SimpleNamespace(
                returncode=1, stderr='unauthorized: authentication required')) as run:
            self.assertTrue(custom._registry_refused(REFERENCE))
        self.assertEqual(run.call_args.args[0][-1], 'docker://' + LOOKUP)

    def test_invalid_references_are_rejected_before_any_registry_query(self):
        for reference in ('ghcr.io/app@sha256:short', 'user:token@ghcr.io/app', 'ghcr.io/app;id'):
            with self.subTest(reference=reference), patch.object(custom.subprocess, 'run') as run:
                with self.assertRaises(ConversionError):
                    custom._registry_lookup(reference)
                with self.assertRaises(ConversionError):
                    custom.registry_report(reference)
                self.assertFalse(custom._registry_refused(reference))
                run.assert_not_called()
