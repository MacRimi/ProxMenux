import sys
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import MagicMock, patch


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "AppImage" / "scripts"))

import lxc_apps  # noqa: E402
import managed_installs  # noqa: E402


class UpdateStrategyValidationTests(unittest.TestCase):
    def test_custom_command_defaults_to_override(self):
        ok, config = lxc_apps.validate_config({
            "name": "Jellyfin",
            "update_command": "systemctl restart jellyfin",
        })
        self.assertTrue(ok, config)
        self.assertEqual(config["update_strategy"], "custom_override")

    def test_legacy_helper_then_custom_is_normalised_to_override(self):
        ok, config = lxc_apps.validate_config({
            "name": "Jellyfin",
            "update_command": "systemctl restart jellyfin",
            "update_strategy": "helper_then_custom",
        })
        self.assertTrue(ok, config)
        self.assertEqual(config["update_strategy"], "custom_override")

    def test_unknown_strategy_is_ignored_and_normalised(self):
        ok, config = lxc_apps.validate_config({
            "name": "Jellyfin",
            "update_command": "true",
            "update_strategy": "run-everything",
        })
        self.assertTrue(ok, config)
        self.assertEqual(config["update_strategy"], "custom_override")


class HelperEvidenceTests(unittest.TestCase):
    def test_legacy_literal_wrapper_slug_is_supported(self):
        wrapper = (
            'bash -c "$(curl -fsSL '
            'https://raw.githubusercontent.com/community-scripts/ProxmoxVE/'
            'main/ct/jellyfin.sh)"'
        )
        self.assertEqual(
            managed_installs._extract_helper_slug_from_update_wrapper(wrapper),
            "jellyfin",
        )

    def test_current_generated_wrapper_slug_is_supported(self):
        wrapper = """#!/usr/bin/env bash
# Community-Scripts update entrypoint (generated - do not edit by hand).
# Regenerated on install and on every successful update.
export SCRIPT_SLUG="nginxproxymanager"
export UPDATE_SCRIPT_NAME="nginxproxymanager"
export COMMUNITY_SCRIPTS_URL="https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main"
bash -c "$(curl -fsSL "${COMMUNITY_SCRIPTS_URL}/ct/${UPDATE_SCRIPT_NAME}.sh")"
"""
        self.assertEqual(
            managed_installs._extract_helper_slug_from_update_wrapper(wrapper),
            "nginxproxymanager",
        )

    def test_update_script_name_is_a_compatible_fallback(self):
        wrapper = "export UPDATE_SCRIPT_NAME='qbittorrent'"
        self.assertEqual(
            managed_installs._extract_helper_slug_from_update_wrapper(wrapper),
            "qbittorrent",
        )

    def test_dynamic_or_command_chained_assignments_are_rejected(self):
        for wrapper in (
            'export SCRIPT_SLUG="$(touch /tmp/unsafe)"',
            'export SCRIPT_SLUG="jellyfin"; touch /tmp/unsafe',
            'export UPDATE_SCRIPT_NAME="${UNTRUSTED}"',
        ):
            with self.subTest(wrapper=wrapper):
                self.assertIsNone(
                    managed_installs._extract_helper_slug_from_update_wrapper(wrapper)
                )

    def test_wrapper_is_executable_evidence(self):
        with patch.object(managed_installs, "_probe_helper_scripts_slug", return_value="jellyfin"):
            slug, source = managed_installs._identify_helper_slug("101", "media")
        self.assertEqual((slug, source), ("jellyfin", "update_wrapper"))

    def test_tag_hostname_is_suggestion_only(self):
        with patch.object(managed_installs, "_probe_helper_scripts_slug", return_value=None), \
             patch.object(managed_installs, "_probe_lxc_tags", return_value={"community-scripts"}), \
             patch.object(managed_installs, "_guess_helper_slug_from_hostname", return_value="jellyfin"):
            slug, source = managed_installs._identify_helper_slug("101", "jellyfin")
        self.assertEqual((slug, source), ("jellyfin", "tag_hostname"))

    def _detect_one(self, source, slug="jellyfin"):
        patches = (
            patch.object(managed_installs, "_lxc_updates_detection_enabled", return_value=True),
            patch.object(managed_installs, "_read_registry", return_value={"items": []}),
            patch.object(managed_installs, "_list_pve_lxcs", return_value=[{
                "vmid": "101", "status": "running", "name": "jellyfin",
            }]),
            patch.object(managed_installs, "_get_oci_managed_vmids", return_value={}),
            patch.object(managed_installs, "_probe_lxc_is_oci", return_value=False),
            patch.object(managed_installs, "_probe_lxc_os", return_value="debian"),
            patch.object(managed_installs, "_identify_helper_slug", return_value=(slug, source)),
            patch.object(managed_installs, "_fetch_helpers_cache", return_value={
                slug: {"name": "Jellyfin", "updateable": True},
            }),
        )
        for ctx in patches:
            ctx.start()
        try:
            return managed_installs._detect_lxc_containers()[0]
        finally:
            for ctx in reversed(patches):
                ctx.stop()

    def test_hostname_guess_never_enables_updater(self):
        item = self._detect_one("tag_hostname")
        self.assertFalse(item["_has_app_updater"])
        self.assertEqual(item["_helper_slug_source"], "tag_hostname")

    def test_valid_wrapper_enables_updateable_app(self):
        item = self._detect_one("update_wrapper")
        self.assertTrue(item["_has_app_updater"])

    def test_base_os_wrapper_never_enables_app_updater(self):
        item = self._detect_one("update_wrapper", slug="debian")
        self.assertFalse(item["_has_app_updater"])


class BulkUpdateConfigTests(unittest.TestCase):
    def test_os_is_mandatory_and_a_second_target_is_required(self):
        ok, error = lxc_apps.validate_bulk_update({"targets": ["app:abc"]})
        self.assertFalse(ok)
        self.assertIn("OS", error)
        ok, error = lxc_apps.validate_bulk_update({"targets": ["os"]})
        self.assertFalse(ok)
        self.assertIn("application", error)

    def test_targets_are_deduplicated_and_normalised(self):
        ok, config = lxc_apps.validate_bulk_update({
            "targets": ["docker-engine", "os", "app:abc", "docker-engine"],
        })
        self.assertTrue(ok, config)
        self.assertEqual(config["targets"], ["os", "app:abc", "docker-engine"])

    def test_only_opaque_docker_units_are_allowed(self):
        ok, _ = lxc_apps.validate_bulk_update({
            "targets": ["os", "docker-compose:media"],
        })
        self.assertFalse(ok)
        ok, config = lxc_apps.validate_bulk_update({
            "targets": ["os", "docker-unit:0123456789abcdefabcd"],
        })
        self.assertTrue(ok, config)

    def test_bulk_config_round_trips_separately_from_schedule(self):
        with tempfile.TemporaryDirectory() as temp_dir, \
             patch.object(lxc_apps, "_APPS_DIR", temp_dir):
            ok, _ = lxc_apps.update_schedule(101, {
                "enabled": False,
                "cron": "",
                "target": "os",
                "targets": ["os"],
            })
            self.assertTrue(ok)
            ok, _ = lxc_apps.update_bulk_update(101, {
                "targets": ["os", "docker-engine"],
            })
            self.assertTrue(ok)
            self.assertEqual(lxc_apps.get_bulk_update(101)["targets"], ["os", "docker-engine"])
            self.assertEqual(lxc_apps.get_schedule(101)["targets"], ["os"])
            self.assertTrue(lxc_apps.delete_bulk_update(101))
            self.assertIsNone(lxc_apps.get_bulk_update(101))
            self.assertIsNotNone(lxc_apps.get_schedule(101))


class ScheduledReleaseTargetTests(unittest.TestCase):
    def test_untracked_custom_app_is_not_release_gated(self):
        gated, remaining = lxc_apps.partition_scheduled_release_targets(
            ["app:links"],
            [{
                "id": "links",
                "name": "Links only",
                "update_command": "systemctl restart links",
            }],
        )
        self.assertEqual(gated, set())
        self.assertEqual(remaining, ["app:links"])

    def test_deferred_tracked_app_does_not_block_untracked_or_os(self):
        gated, remaining = lxc_apps.partition_scheduled_release_targets(
            ["os", "app:tracked", "app:links"],
            [
                {"id": "tracked", "installed_via": "binary"},
                {"id": "links", "update_command": "true"},
            ],
        )
        self.assertEqual(gated, {"tracked"})
        self.assertEqual(remaining, ["os", "app:links"])

    def test_legacy_apps_target_keeps_only_untracked_when_gate_defers(self):
        gated, remaining = lxc_apps.partition_scheduled_release_targets(
            ["os", "apps"],
            [
                {"id": "tracked", "installed_via": "file"},
                {"id": "links", "update_command": "true"},
                {"id": "docker", "installed_via": "binary", "helper_slug": "docker"},
            ],
        )
        self.assertEqual(gated, {"tracked"})
        self.assertEqual(remaining, ["os", "app:links"])


class AppCacheWriteThroughContractTests(unittest.TestCase):
    def test_successful_mutations_publish_the_complete_sidecar(self):
        cache_source = (REPO_ROOT / "AppImage" / "lib" / "lxc-apps-cache.ts").read_text()
        panel_source = (REPO_ROOT / "AppImage" / "components" / "lxc-app-panel.tsx").read_text()
        server_source = (REPO_ROOT / "AppImage" / "scripts" / "flask_server.py").read_text()
        self.assertIn("export function setLxcAppsCached", cache_source)
        self.assertGreaterEqual(panel_source.count("setLxcAppsCached(vmid, r, suggestions)"), 6)
        self.assertNotIn("_vm_cache_put(_vm_apps_cache", server_source)
        self.assertIn("lxc_apps.load_sidecar(vmid)", server_source)

    def test_post_apply_revalidates_without_evicting_render_seed(self):
        source = (REPO_ROOT / "AppImage" / "components" / "virtual-machines.tsx").read_text()
        apply_block = source[source.index("const handleApplyComplete"):source.index("const getAggregateUpdateCheck")]
        self.assertIn("void fetchLxcApps(applyVmid)", apply_block)
        self.assertNotIn("invalidateLxcApps(applyVmid)", apply_block)

    def test_apply_completion_is_owned_by_the_backend_and_idempotent(self):
        server_source = (REPO_ROOT / "AppImage" / "scripts" / "flask_server.py").read_text()
        terminal_source = (REPO_ROOT / "AppImage" / "scripts" / "flask_terminal_routes.py").read_text()
        endpoint_block = server_source[
            server_source.index("def api_lxc_updates_applied"):
            server_source.index("@app.route('/api/health/thresholds'")
        ]
        finalizer_block = server_source[
            server_source.index("def _finalize_lxc_update"):
            server_source.index("def _terminal_lxc_update_completed")
        ]

        self.assertIn("set_script_completion_hook(_terminal_lxc_update_completed)", server_source)
        self.assertIn("params.get('RUN_ID')", server_source)
        self.assertIn("_run_script_completion_hook", terminal_source)
        self.assertIn("_lxc_update_finalizations", finalizer_block)
        self.assertIn("managed_installs.refresh_lxc(vmid)", finalizer_block)
        self.assertNotIn("managed_installs.check_for_updates(force=True)", endpoint_block)
        self.assertIn("entity_id=f'{vmid}:{safe_run_id}'", finalizer_block)

    def test_scheduled_updates_use_the_shared_finalizer(self):
        source = (REPO_ROOT / "AppImage" / "scripts" / "flask_server.py").read_text()
        scheduler_block = source[
            source.index("def _run_scheduled_update"):
            source.index("def _scheduler_loop")
        ]
        self.assertIn("_finalize_lxc_update(", scheduler_block)
        self.assertIn("return finish('partial'", scheduler_block)
        self.assertIn("before_snapshot=before", scheduler_block)


class DockerStackNotificationTests(unittest.TestCase):
    def _docker_app(self):
        return {
            "id": "docker",
            "name": "Docker",
            "helper_slug": "docker",
            "notifications_enabled": True,
            "state": {
                "installed_version": "27.4.0",
                "latest_version": "29.7.2",
                "update_available": True,
            },
        }

    def _inventory(self, reference="portainer/portainer-ce:latest", digest="sha256:new"):
        return {
            "available": True,
            "images": [{
                "reference": reference,
                "installed_version": "2.19.4",
                "available_version": "2.39.6",
                "remote_digest": digest,
                "update_available": True,
            }],
        }

    def test_engine_and_images_share_one_payload(self):
        payload = lxc_apps._docker_stack_notification_payload(
            101, self._docker_app(), self._inventory(), "docker",
        )
        self.assertEqual(payload["count"], 2)
        self.assertIn("Docker Engine: 27.4.0 → 29.7.2", payload["details"])
        self.assertIn("portainer/portainer-ce:latest: 2.19.4 → 2.39.6", payload["details"])

    def test_signature_changes_when_pending_identity_changes_at_same_count(self):
        first = lxc_apps._docker_stack_notification_payload(
            101, {**self._docker_app(), "state": {}}, self._inventory(), "docker",
        )
        second = lxc_apps._docker_stack_notification_payload(
            101,
            {**self._docker_app(), "state": {}},
            self._inventory("library/nginx:latest", "sha256:other"),
            "docker",
        )
        self.assertEqual(first["count"], second["count"])
        self.assertNotEqual(first["signature"], second["signature"])

    def test_generic_app_event_does_not_duplicate_docker_stack_event(self):
        emitter = MagicMock()
        fake_module = SimpleNamespace(notification_manager=emitter)
        with patch.dict(sys.modules, {"notification_manager": fake_module}):
            lxc_apps._fire_update_notification(101, self._docker_app())
        emitter.emit_event.assert_not_called()


class DockerInventoryCachePolicyTests(unittest.TestCase):
    def setUp(self):
        self.original_cache = lxc_apps._docker_inventory_cache
        lxc_apps._docker_inventory_cache = {}

    def tearDown(self):
        lxc_apps._docker_inventory_cache = self.original_cache

    def _inventory(self, available=True):
        return {
            "vmid": 101,
            "available": available,
            "images": [],
            "checked_at_unix": 1_000_000,
        }

    def test_available_inventory_uses_24_hour_cache(self):
        self.assertEqual(lxc_apps._DOCKER_INVENTORY_TTL_SEC, 24 * 3600)
        lxc_apps._docker_inventory_cache["101"] = self._inventory()
        fresh_scan = self._inventory()
        fresh_scan["engine_version"] = "new-scan"

        with patch.object(lxc_apps.time, "time", return_value=1_000_000 + 3600), \
             patch.object(lxc_apps, "_docker_inventory_from_ct", return_value=fresh_scan) as scan:
            cached = lxc_apps.get_docker_inventory(101)

        self.assertNotIn("engine_version", cached)
        scan.assert_not_called()

    def test_available_inventory_refreshes_after_24_hours(self):
        lxc_apps._docker_inventory_cache["101"] = self._inventory()
        fresh_scan = self._inventory()
        fresh_scan["engine_version"] = "new-scan"

        with patch.object(lxc_apps.time, "time", return_value=1_000_000 + 24 * 3600 + 1), \
             patch.object(lxc_apps, "_docker_inventory_from_ct", return_value=fresh_scan) as scan:
            refreshed = lxc_apps.get_docker_inventory(101)

        self.assertEqual(refreshed["engine_version"], "new-scan")
        scan.assert_called_once_with(101)

    def test_unavailable_inventory_retries_after_30_seconds(self):
        lxc_apps._docker_inventory_cache["101"] = self._inventory(available=False)
        fresh_scan = self._inventory(available=True)

        with patch.object(lxc_apps.time, "time", return_value=1_000_029), \
             patch.object(lxc_apps, "_docker_inventory_from_ct", return_value=fresh_scan) as scan:
            lxc_apps.get_docker_inventory(101)
        scan.assert_not_called()

        with patch.object(lxc_apps.time, "time", return_value=1_000_031), \
             patch.object(lxc_apps, "_docker_inventory_from_ct", return_value=fresh_scan) as scan:
            lxc_apps.get_docker_inventory(101)
        scan.assert_called_once_with(101)

    def test_force_failure_preserves_docker_unit_identity_as_refreshing(self):
        previous = self._inventory(available=True)
        previous.update({
            "images": [{"reference": "demo/app:latest", "update_available": True}],
            "update_units": [{
                "id": "docker-unit:0123456789abcdefabcd",
                "display_name": "Demo",
                "update_available": True,
            }],
        })
        lxc_apps._docker_inventory_cache["101"] = previous
        failed_scan = {
            "vmid": 101,
            "available": False,
            "images": [],
            "update_count": 0,
            "error": "Docker is not ready",
        }

        with patch.object(lxc_apps.time, "time", return_value=1_000_100), \
             patch.object(lxc_apps, "_docker_inventory_from_ct", return_value=failed_scan):
            result = lxc_apps.get_docker_inventory(101, force=True)

        self.assertFalse(result["available"])
        self.assertTrue(result["refreshing"])
        self.assertEqual(result["update_units"][0]["display_name"], "Demo")
        self.assertEqual(result["update_units"][0]["id"], "docker-unit:0123456789abcdefabcd")

    def test_force_failure_preserves_empty_lifecycle_pending_state(self):
        pending = self._inventory(available=False)
        pending.update({
            "refreshing": True,
            "images": [],
            "update_units": [],
            "error": None,
        })
        lxc_apps._docker_inventory_cache["101"] = pending
        failed_scan = {
            "vmid": 101,
            "available": False,
            "images": [],
            "update_units": [],
            "update_count": 0,
            "error": "Docker is not ready",
        }

        with patch.object(lxc_apps.time, "time", return_value=1_000_100), \
             patch.object(lxc_apps, "_docker_inventory_from_ct", return_value=failed_scan):
            result = lxc_apps.get_docker_inventory(101, force=True)

        self.assertFalse(result["available"])
        self.assertTrue(result["refreshing"])
        self.assertEqual(result["images"], [])
        self.assertEqual(result["update_units"], [])

    def test_lifecycle_transition_keeps_ids_but_clears_old_update_state(self):
        previous = self._inventory(available=True)
        previous.update({
            "images": [{"reference": "demo/app:latest", "update_available": True}],
            "update_units": [{
                "id": "docker-unit:0123456789abcdefabcd",
                "display_name": "Demo",
                "update_available": True,
            }],
        })
        lxc_apps._docker_inventory_cache["101"] = previous

        pending = lxc_apps.mark_docker_inventory_refreshing(101)

        self.assertFalse(pending["available"])
        self.assertTrue(pending["refreshing"])
        self.assertIsNone(pending["images"][0]["update_available"])
        self.assertIsNone(pending["update_units"][0]["update_available"])
        self.assertTrue(previous["images"][0]["update_available"])

    def test_docker_ps_timeout_is_not_reported_as_an_empty_inventory(self):
        with patch.object(lxc_apps, "_pct_exec", side_effect=[
            (0, "27.4.0\n", ""),
            (124, "", "timed out after 10s"),
        ]):
            result = lxc_apps._docker_inventory_from_ct(101)

        self.assertFalse(result["available"])
        self.assertEqual(result["images"], [])
        self.assertIn("not ready", result["error"])

    def test_docker_image_ls_timeout_is_not_reported_as_empty(self):
        with patch.object(lxc_apps, "_pct_exec", side_effect=[
            (0, "27.4.0\n", ""),
            (0, "", ""),
            (124, "", "timed out after 15s"),
        ]):
            result = lxc_apps._docker_inventory_from_ct(101)

        self.assertFalse(result["available"])
        self.assertEqual(result["images"], [])
        self.assertIn("timed out", result["error"])

    def test_pct_exec_timeout_kills_the_complete_local_process_group(self):
        process = MagicMock()
        process.pid = 4321
        process.communicate.side_effect = [
            subprocess.TimeoutExpired(cmd="pct", timeout=1),
            ("", ""),
        ]
        with patch.object(lxc_apps.subprocess, "Popen", return_value=process), \
             patch.object(lxc_apps.os, "killpg") as killpg:
            rc, out, err = lxc_apps._pct_exec(101, ["docker", "version"], timeout=1)

        self.assertEqual((rc, out), (124, ""))
        self.assertIn("timed out", err)
        killpg.assert_called_once_with(4321, lxc_apps.signal.SIGKILL)

    def test_inventory_does_not_define_disk_persistence(self):
        source = (REPO_ROOT / "AppImage" / "scripts" / "lxc_apps.py").read_text()
        self.assertNotIn("docker_inventory.json", source)
        self.assertNotIn("_save_docker_inventory_disk", source)

    def test_daily_collector_and_ui_force_points_are_explicit(self):
        notification_source = (REPO_ROOT / "AppImage" / "scripts" / "notification_events.py").read_text()
        frontend_source = (REPO_ROOT / "AppImage" / "components" / "virtual-machines.tsx").read_text()
        automatic_block = frontend_source[
            frontend_source.index("// Docker drift is opt-in"):
            frontend_source.index("const refreshDockerInventory")
        ]
        manual_block = frontend_source[
            frontend_source.index("const refreshDockerInventory"):
            frontend_source.index("const closeCustomCmdEditor")
        ]

        self.assertIn("refresh_docker_inventories(force=True)", notification_source)
        self.assertIn("/docker/inventory`", automatic_block)
        self.assertNotIn("?force=1", automatic_block)
        self.assertIn("/docker/inventory?force=1", manual_block)

    def test_startup_and_lifecycle_rebuild_memory_inventory_without_blank_gap(self):
        server_source = (REPO_ROOT / "AppImage" / "scripts" / "flask_server.py").read_text()
        lifecycle_block = server_source[
            server_source.index("def _refresh_started_guest"):
            server_source.index("def _schedule_started_guest_refresh")
        ]
        startup_block = server_source[
            server_source.index("def _deferred_startup_inits"):
            server_source.index("threading.Thread(target=_deferred_startup_inits")
        ]

        self.assertIn("refresh_docker_inventories(force=True)", startup_block)
        self.assertIn("mark_docker_inventory_refreshing(vmid)", lifecycle_block)
        self.assertIn("get_docker_inventory(vmid, force=True)", lifecycle_block)
        self.assertIn("docker_refresh_pending", lifecycle_block)
        self.assertIn("time.monotonic() + 7 * 60", lifecycle_block)
        self.assertIn("Docker ready in", lifecycle_block)
        self.assertLess(
            lifecycle_block.index("get_docker_inventory(vmid, force=True)"),
            lifecycle_block.index("get_suggestions(vmid, force=True)"),
        )
        self.assertLess(
            lifecycle_block.index("_publish_guest_modal_cache_revision(vmid)"),
            lifecycle_block.index("get_suggestions(vmid, force=True)"),
        )

    def test_manual_docker_refresh_publishes_endpoint_result_without_full_vm_wait(self):
        frontend_source = (REPO_ROOT / "AppImage" / "components" / "virtual-machines.tsx").read_text()
        manual_block = frontend_source[
            frontend_source.index("const refreshDockerInventory"):
            frontend_source.index("const closeCustomCmdEditor")
        ]

        self.assertIn("const inventory = await fetchApi<LxcDockerInventory>", manual_block)
        self.assertIn("docker_inventory: inventory", manual_block)
        self.assertIn("{ revalidate: false }", manual_block)
        self.assertNotIn("await mutate()", manual_block)

    def test_bulk_ui_does_not_expose_internal_docker_ids_while_refreshing(self):
        frontend_source = (REPO_ROOT / "AppImage" / "components" / "virtual-machines.tsx").read_text()
        bulk_block = frontend_source[
            frontend_source.index("const pendingDockerBulkTargets"):
            frontend_source.index("{/* Options card")
        ]

        self.assertIn("vmLxc.bulkUpdate.dockerInventoryPending", bulk_block)
        self.assertIn("vmLxc.bulkUpdate.missingDockerTarget", bulk_block)
        self.assertIn("pendingDockerBulkTargets.length > 0", bulk_block)
        self.assertNotIn("{target}\n", bulk_block)

if __name__ == "__main__":
    unittest.main()
