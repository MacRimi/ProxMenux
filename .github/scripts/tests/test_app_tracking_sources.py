"""Source layout regressions for the Helper-Scripts/core repository split."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

SCRIPT = Path(__file__).resolve().parents[1] / "generate_app_tracking_catalog.py"
SPEC = importlib.util.spec_from_file_location("tracking_sources_under_test", SCRIPT)
generator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = generator
SPEC.loader.exec_module(generator)

NORMALIZE = '''  app_lc="$(echo "${app,,}" | tr -d ' ')"'''
READ_BODY = NORMALIZE + '''
  current_file="$HOME/.${app_lc}"
  current="$(<"$current_file")"
'''
WRITE_BODY = NORMALIZE + '''
  version_file="$HOME/.${app_lc}"
  echo "$version" >"$version_file"
'''


def function(name, body):
    return f"{name}() {{\n{body}\n}}\n"


LEGACY = (
    function("check_for_gh_release", READ_BODY.replace('  current_file=', '  local current_file='))
    + function("fetch_and_deploy_gh_release", WRITE_BODY.replace('  version_file=', '  local version_file='))
)
SPLIT = (
    function("check_for_gh_release", '  check_for_release github "$1" "$2" "${3:-}"')
    + function("fetch_and_deploy_gh_release", '  fetch_and_deploy_release github "$1" "$2" "${3:-tarball}"')
    + function("check_for_release", READ_BODY)
    + function("fetch_and_deploy_release", WRITE_BODY)
)


class TrackingSourcesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.apps = self.root / "apps"
        self.core = self.root / "core"
        self.write(self.apps / "ct/example.sh", '''APP="Example"
check_for_gh_release "Example" "example/example"
''')
        self.write(self.apps / "install/example-install.sh", '''
fetch_and_deploy_gh_release "Example" "example/example" "tarball" "latest"
''')

    def write(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def run_main(self, *extra):
        output = self.root / "output.json"
        args = ["--source-dir", str(self.apps), "--output", str(output),
                "--include-helper-markers",
                "--audit-output", str(self.root / "audit.json"),
                "--v2-output", str(self.root / "v2.json"), *extra]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = generator.main(args)
        return result, output

    def test_legacy_monolithic_contract_is_supported(self):
        self.write(self.apps / "misc/tools.func", LEGACY)
        result, output = self.run_main()
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.read_text())["example"]["file_path"], "/root/.example")

    def test_split_contract_builds_catalog_and_records_actual_evidence(self):
        self.write(self.core / "lib/forge.func", SPLIT)
        result, output = self.run_main("--core-source-dir", str(self.core))
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.read_text())["example"]["repo"], "example/example")
        audit = json.loads((self.root / "audit.json").read_text())
        self.assertEqual(audit["provenance"]["core"]["source_dir"], str(self.core.resolve()))
        v2 = (self.root / "v2.json").read_text()
        self.assertIn("core/lib/forge.func", v2)
        self.assertNotIn("misc/tools.func", v2)

    def test_unsplit_core_tools_library_is_supported(self):
        path = self.write(self.core / "lib/tools.func", LEGACY)
        self.assertEqual(generator.shared_helper_path(self.apps, self.core), path)
        generator.verify_shared_helper(path)

    def test_changed_contract_never_overwrites_existing_outputs(self):
        for old, new in [('echo "$version" >"$version_file"', 'echo "$version" >/tmp/version'),
                         ('current_file="$HOME/.${app_lc}"', 'current_file="/tmp/version"'),
                         ('tr -d \' \'', 'tr -d \'-\'')]:
            with self.subTest(change=old):
                self.write(self.core / "lib/forge.func", SPLIT.replace(old, new))
                output = self.write(self.root / "output.json", '{"keep": true}\n')
                result, _ = self.run_main("--core-source-dir", str(self.core))
                self.assertEqual(result, 1)
                self.assertEqual(output.read_text(), '{"keep": true}\n')

    def test_matching_text_in_unrelated_functions_is_not_evidence(self):
        path = self.write(self.core / "lib/forge.func", SPLIT.replace(
            function("check_for_release", READ_BODY), function("unrelated", READ_BODY)))
        with self.assertRaises(generator.CatalogError):
            generator.verify_shared_helper(path)

    def test_split_local_tree_requires_explicit_local_core_without_network(self):
        with patch.object(generator.GitHubClient, "request", side_effect=AssertionError("Network")):
            result, output = self.run_main()
        self.assertEqual(result, 1)
        self.assertFalse(output.exists())

    def test_invalid_local_core_fails_without_writing_a_catalog(self):
        result, output = self.run_main("--core-source-dir", str(self.core))
        self.assertEqual(result, 1)
        self.assertFalse(output.exists())

    def test_snapshot_cache_accepts_core_without_ct_directory(self):
        sha = "a" * 40
        source = self.root / "cache/community-scripts--core" / sha
        self.write(source / "lib/forge.func", SPLIT)
        self.write(source / ".snapshot-complete", "archive-hash\n")
        client = Mock()
        client.json.return_value = {"sha": sha}
        path, commit, archive = generator.obtain_snapshot(
            client, "community-scripts/core", "main", self.root / "cache",
            required_paths=("lib/forge.func",))
        self.assertEqual((path, commit, archive), (source, sha, "archive-hash"))
        client.request.assert_not_called()

    def test_remote_split_source_pins_both_repositories(self):
        self.write(self.core / "lib/forge.func", SPLIT)
        output = self.root / "remote.json"
        with patch.object(generator, "obtain_snapshot", side_effect=[
            (self.apps, "a" * 40, "apps-archive"),
            (self.core, "b" * 40, "core-archive"),
        ]) as snapshots, contextlib.redirect_stdout(io.StringIO()):
            result = generator.main([
                "--output", str(output), "--include-helper-markers",
                "--audit-output", str(self.root / "remote-audit.json"),
                "--v2-output", str(self.root / "remote-v2.json"),
            ])
        self.assertEqual(result, 0)
        provenance = json.loads((self.root / "remote-audit.json").read_text())["provenance"]
        self.assertEqual(provenance["commit_sha"], "a" * 40)
        self.assertEqual(provenance["core"]["commit_sha"], "b" * 40)
        self.assertEqual(provenance["core"]["archive_sha256"], "core-archive")
        self.assertEqual(snapshots.call_args_list[1].args[1], "community-scripts/core")
        self.assertEqual(snapshots.call_args_list[1].kwargs["required_paths"], ("lib/forge.func",))

    def test_invalid_download_is_not_marked_complete(self):
        client = Mock()
        client.json.return_value = {"sha": "b" * 40}
        client.request.return_value = b"invalid-layout"
        with patch.object(generator, "safe_extract_tar"):
            with self.assertRaises(generator.CatalogError):
                generator.obtain_snapshot(client, "community-scripts/core", "main", self.root / "cache",
                                          required_paths=("lib/forge.func",))
        self.assertEqual(list((self.root / "cache").rglob(".snapshot-complete")), [])


if __name__ == "__main__":
    unittest.main()
