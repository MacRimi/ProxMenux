"""Guard Gonic's persistent data paths and first-run listener contract."""
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GonicRecipeTests(unittest.TestCase):
    def test_persistent_paths_and_listener_match_upstream_image(self):
        """Both shipped recipes must provide every configured data directory."""
        for family in ("apps", "curated"):
            with self.subTest(family=family):
                template = json.loads(
                    (ROOT / "catalog" / family / "gonic.json")
                    .read_text(encoding="utf-8")
                )
                service = template["compose_stack"]["services"][0]["compose"]
                environment = service["environment"]
                volume_paths = {
                    volume["container_path"]
                    for volume in template["container_contract"]["volumes"]
                }
                preparation_paths = {
                    item["container_path"]
                    for item in template["proxmox"]["installer_profile"]
                    ["volume_preparations"]
                }
                compose_volumes = set(service["volumes"])

                expected_paths = {"/data", "/music", "/podcasts", "/playlists", "/cache"}
                self.assertTrue(expected_paths <= volume_paths)
                self.assertTrue(expected_paths <= preparation_paths)
                self.assertTrue({
                    "./data:/data",
                    "./music:/music:ro",
                    "./podcasts:/podcasts",
                    "./playlists:/playlists",
                    "./cache:/cache",
                } <= compose_volumes)
                self.assertEqual(environment["GONIC_PODCAST_PATH"], "/podcasts")
                self.assertEqual(environment["GONIC_PLAYLISTS_PATH"], "/playlists")
                music = next(
                    volume for volume in template["container_contract"]["volumes"]
                    if volume["container_path"] == "/music"
                )
                self.assertTrue(music["read_only"])
                self.assertEqual(template["container_contract"]["ports"][0]["container_port"], 80)
                self.assertEqual(template["container_contract"]["ports"][0]["published_example"], 4747)
                self.assertEqual(template["first_run"]["endpoints"][0]["port"], 80)
                self.assertEqual(
                    template["proxmox"]["installer_profile"]["startup_healthcheck"]["port"],
                    80,
                )
                original = template["container_contract"]["original_compose"]
                for volume in compose_volumes:
                    self.assertIn(f"- {volume}", original)


if __name__ == "__main__":
    unittest.main()
