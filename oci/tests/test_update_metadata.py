"""Native image checks reuse immutable metadata only after a fresh digest lookup."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'remote'))
import oci_installation_state as state


def digest(value): return 'sha256:' + state.sha(value)


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.platform = json.dumps({'schemaVersion': 2, 'config': {'digest': 'sha256:' + 'c' * 64},
                                    'layers': [{'digest': 'sha256:' + 'd' * 64, 'size': 15}]}).encode()
        self.index = json.dumps({'schemaVersion': 2, 'manifests': [
            {'digest': digest(self.platform), 'platform': {'architecture': 'amd64', 'os': 'linux'}}]}).encode()
        self.config = json.dumps({'architecture': 'amd64', 'os': 'linux', 'created': '2026-10-18T00:00:00Z',
                                  'config': {'Labels': {'org.opencontainers.image.version': '2.0'}, 'Env': []}}).encode()
        self.known = {'manifest_digest': digest(self.platform), 'architecture': 'amd64',
                      'version': '1.0', 'created': '2026-10-01T00:00:00Z'}

    def test_unchanged_multiarch_image_requires_only_a_fresh_index_lookup(self):
        with patch.object(state, 'command', return_value=self.index) as command:
            candidate = state.resolve_candidate_metadata('ghcr.io/example/private:latest', 'amd64', self.known)
        command.assert_called_once_with('skopeo', 'inspect', '--raw', 'docker://ghcr.io/example/private:latest')
        self.assertEqual(candidate['manifest_digest'], self.known['manifest_digest'])
        self.assertEqual(candidate['version'], '1.0')
        self.assertEqual(candidate['registry_digest'], digest(self.index))

    def test_unchanged_singlearch_image_requires_only_a_fresh_manifest_lookup(self):
        with patch.object(state, 'command', return_value=self.platform) as command:
            candidate = state.resolve_candidate_metadata('example/app:latest', 'amd64', self.known)
        self.assertEqual(command.call_count, 1)
        self.assertEqual(candidate['version'], '1.0')

    def test_changed_digest_fetches_and_validates_new_metadata(self):
        old = dict(self.known, manifest_digest='sha256:' + 'a' * 64)
        with patch.object(state, 'command', side_effect=[self.index, self.platform, self.config]) as command:
            candidate = state.resolve_candidate_metadata('example/app:latest', 'amd64', old)
        self.assertEqual(command.call_count, 3)
        self.assertEqual(candidate['version'], '2.0')
        self.assertEqual(candidate['manifest_digest'], digest(self.platform))

    def test_different_architecture_cannot_reuse_metadata(self):
        known = dict(self.known, architecture='arm64')
        with patch.object(state, 'command', side_effect=[self.index, self.platform, self.config]) as command:
            candidate = state.resolve_candidate_metadata('example/app:latest', 'amd64', known)
        self.assertEqual(command.call_count, 3)
        self.assertEqual(candidate['version'], '2.0')

    def test_install_and_update_still_fetch_complete_verified_contract(self):
        with patch.object(state, 'command', side_effect=[self.index, self.platform, self.config]) as command:
            candidate = state.resolve_candidate('example/app:latest', 'amd64')
        self.assertEqual(command.call_count, 3)
        self.assertEqual(candidate['layers'], ['sha256:' + 'd' * 64])
        self.assertIn('Env', candidate['defaults'])

    def test_changed_manifest_must_still_match_the_registry_digest(self):
        with patch.object(state, 'command', side_effect=[self.index, b'{}']):
            with self.assertRaises(ValueError):
                state.resolve_candidate_metadata('example/app:latest', 'amd64', None)

    def test_registry_failure_cannot_be_hidden_by_saved_metadata(self):
        with patch.object(state, 'command', side_effect=RuntimeError('Registry unavailable')):
            with self.assertRaises(RuntimeError):
                state.resolve_candidate_metadata('example/app:latest', 'amd64', self.known)


if __name__ == '__main__': unittest.main()
