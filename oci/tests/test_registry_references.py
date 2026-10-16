from pathlib import Path
import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "remote"))
from proxmenux_oci.registry_auth import RegistryError, validate_registry, validate_image


class ReferenceTests(unittest.TestCase):
    def test_native_image_importer_preserves_registry_port_and_digest(self):
        from proxmenux_oci import custom
        import yaml
        for reference in ('registry.test:5443/team/app:stable',
                          '[::1]:5443/team/app@sha256:' + 'a' * 64):
            with self.subTest(reference=reference), \
                    patch.object(custom.subprocess, 'run', return_value=SimpleNamespace(
                        returncode=0, stdout=json.dumps({'config': {}}))) as run:
                compose = yaml.safe_load(custom.compose_from_image(reference))
            self.assertEqual(next(iter(compose['services'].values()))['image'], reference)
            self.assertEqual(run.call_args.args[0][-1], 'docker://' + reference)

    def test_private_registries_with_ports_and_digest_references_are_valid(self):
        for reference in ('ghcr.io/team/app:latest', 'registry.local:5000/team/app:stable',
                          '[::1]:5000/team/app:latest', 'ghcr.io/team/app@sha256:' + 'a' * 64):
            self.assertEqual(validate_image(reference), reference)

    def test_credentials_and_urls_cannot_be_used_as_image_references(self):
        for reference in ('https://ghcr.io/team/app', 'user:token@ghcr.io/app', 'ghcr.io/app;id',
                          'ghcr.io/../app', 'ghcr.io/app@sha256:short'):
            with self.assertRaises(RegistryError):
                validate_image(reference)

    def test_registry_authorities_do_not_accept_image_paths_or_credentials(self):
        for registry in ('https://ghcr.io', 'ghcr.io/team', 'user:token@ghcr.io', 'host:99999'):
            with self.assertRaises(RegistryError):
                validate_registry(registry)


if __name__ == '__main__':
    unittest.main()
