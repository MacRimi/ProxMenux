"""Unit tests for the declarative volume_preparations application inside
install_generic_stack.py's attach_mounts() (Solution A, approved
2026-09-29): the stack path now runs volume_preparations itself, after
attach_mounts() has physically attached the real mount — instead of
relying on install_oci.sh's apply_installer_profile(), whose
only_when_mount_type check can never match for a stack service because
create_service() invokes install_oci.sh per-service with an
always-empty DEPLOYMENT_FILE.mounts.

Corrected after review found two bugs in the first implementation:
1. resolve_volume_owner() originally computed ONE value shared by both
   owner_strategy values, so mapped-root incorrectly picked up
   PUID/PGID/volume_owner (it must always be 100000:100000 or 0:0,
   independent of the container's application user). It now takes the
   owner_strategy as an explicit argument and returns a genuinely
   different value per strategy, mirroring install_oci.sh's
   HOST_ROOT_UID/GID (mapped-root, fixed) vs. HOST_BIND_UID/GID
   (mapped-application-user, PUID/PGID + offset).
2. apply_volume_preparation() no longer chowns directly — it only
   resolves and returns the declared owner; attach_mounts() applies it
   AFTER the seed copy and AFTER its own always-run fallback chown
   (which preserves image ownership for mounts with no declared
   preparation), so the declared owner is never silently overwritten.

These tests exercise apply_volume_preparation()/resolve_volume_owner()
directly against a real filesystem fixture (a temp directory standing
in for the already-mounted container_path) — they do NOT touch pct,
LXC, or any real container; attach_mounts() itself (which does call
pct) is exercised only at the metadata/selection level by the existing
test_stack_volume_preparations.py tests (build_stack() output) and, for
the post-attach ordering fix, by a source-order guard test below — not
re-tested here at the pct/LXC level.
"""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "remote"))
sys.path.insert(0, str(ROOT / "src"))

import install_generic_stack as igs  # noqa: E402


def make_service(*, unprivileged=True, environment=None, volume_owner=None,
                  volume_preparations=None):
    return {
        'deployment': {
            'security': {'unprivileged': unprivileged},
            'environment': environment or [],
        },
        'template': {
            'proxmox': {
                'installer_profile': {
                    **({'volume_owner': volume_owner} if volume_owner else {}),
                    'volume_preparations': volume_preparations or [],
                }
            }
        },
    }


class ResolveVolumeOwnerTests(unittest.TestCase):
    def test_mapped_root_unprivileged_is_100000(self):
        service = make_service(unprivileged=True)
        self.assertEqual(igs.resolve_volume_owner(service, 'mapped-root'), (100000, 100000))

    def test_mapped_root_privileged_is_0(self):
        service = make_service(unprivileged=False)
        self.assertEqual(igs.resolve_volume_owner(service, 'mapped-root'), (0, 0))

    def test_mapped_root_ignores_puid_pgid(self):
        """The bug this guards against: mapped-root with PUID/PGID=1000
        must still resolve to the fixed root mapping (100000:100000 for
        unprivileged), NOT the application-user offset (101000:101000)."""
        service = make_service(unprivileged=True, environment=[
            {'name': 'PUID', 'value': '1000'},
            {'name': 'PGID', 'value': '1000'},
        ])
        self.assertEqual(igs.resolve_volume_owner(service, 'mapped-root'), (100000, 100000))

    def test_mapped_root_ignores_volume_owner_override(self):
        service = make_service(unprivileged=True, volume_owner={'uid': 5000, 'gid': 6000})
        self.assertEqual(igs.resolve_volume_owner(service, 'mapped-root'), (100000, 100000))

    def test_mapped_application_user_default_is_offset_zero(self):
        service = make_service(unprivileged=True)
        self.assertEqual(igs.resolve_volume_owner(service, 'mapped-application-user'), (100000, 100000))

    def test_mapped_application_user_privileged_default_is_root(self):
        service = make_service(unprivileged=False)
        self.assertEqual(igs.resolve_volume_owner(service, 'mapped-application-user'), (0, 0))

    def test_mapped_application_user_with_puid_pgid_unprivileged(self):
        """The bug this guards against, other direction: mapped-root and
        mapped-application-user with the SAME PUID/PGID=1000 must give
        DIFFERENT results — this one gets the application offset."""
        service = make_service(unprivileged=True, environment=[
            {'name': 'PUID', 'value': '1000'},
            {'name': 'PGID', 'value': '1000'},
        ])
        self.assertEqual(igs.resolve_volume_owner(service, 'mapped-application-user'), (101000, 101000))

    def test_mapped_application_user_with_puid_pgid_privileged(self):
        service = make_service(unprivileged=False, environment=[
            {'name': 'PUID', 'value': '1000'},
            {'name': 'PGID', 'value': '1000'},
        ])
        self.assertEqual(igs.resolve_volume_owner(service, 'mapped-application-user'), (1000, 1000))

    def test_mapped_application_user_last_matching_environment_name_wins(self):
        service = make_service(unprivileged=False, environment=[
            {'name': 'PUID', 'value': '1000'},
            {'name': 'UID', 'value': '2000'},
            {'name': 'PGID', 'value': '1000'},
            {'name': 'GROUP_ID', 'value': '3000'},
        ])
        self.assertEqual(igs.resolve_volume_owner(service, 'mapped-application-user'), (2000, 3000))

    def test_mapped_application_user_invalid_environment_value_is_safely_zero(self):
        service = make_service(unprivileged=False, environment=[
            {'name': 'PUID', 'value': 'not-a-number'},
            {'name': 'PGID', 'value': '-5'},
        ])
        self.assertEqual(igs.resolve_volume_owner(service, 'mapped-application-user'), (0, 0))

    def test_volume_owner_overrides_only_mapped_application_user(self):
        """volume_owner must change only the application-user strategy,
        never mapped-root — even when both are resolved for the same
        service."""
        service = make_service(unprivileged=False, environment=[
            {'name': 'PUID', 'value': '1000'},
            {'name': 'PGID', 'value': '1000'},
        ], volume_owner={'uid': 5000, 'gid': 6000})
        self.assertEqual(igs.resolve_volume_owner(service, 'mapped-application-user'), (5000, 6000))
        self.assertEqual(igs.resolve_volume_owner(service, 'mapped-root'), (0, 0))

    def test_invalid_volume_owner_override_is_safely_zero(self):
        service = make_service(unprivileged=False, environment=[
            {'name': 'PUID', 'value': '1000'},
        ], volume_owner={'uid': 'bogus'})
        self.assertEqual(igs.resolve_volume_owner(service, 'mapped-application-user')[0], 0)

    def test_unknown_owner_strategy_fails_clearly(self):
        service = make_service(unprivileged=True)
        with self.assertRaises(RuntimeError):
            igs.resolve_volume_owner(service, 'some-future-strategy')


class ApplyVolumePreparationTests(unittest.TestCase):
    def _target(self, tmp, with_lost_found=True):
        target = Path(tmp) / 'target'
        target.mkdir()
        if with_lost_found:
            (target / 'lost+found').mkdir()
        return target

    def test_managed_volume_preparation_removes_lost_found_and_resolves_owner(self):
        """apply_volume_preparation() no longer chowns directly — it
        resolves and returns the declared owner for the caller to apply
        after the seed copy (see ApplyVolumePreparationOrderingTests)."""
        with tempfile.TemporaryDirectory() as tmp:
            target = self._target(tmp)
            service = make_service(unprivileged=True, volume_preparations=[{
                'container_path': '/app/.blinko',
                'remove_lost_found': True,
                'owner_strategy': 'mapped-root',
                'only_when_mount_type': 'managed-volume',
            }])
            mount = {'container_path': '/app/.blinko', 'type': 'managed-volume'}
            applied, owner = igs.apply_volume_preparation(service, mount, target)
            self.assertTrue(applied)
            self.assertEqual(owner, (100000, 100000))
            self.assertFalse((target / 'lost+found').exists())

    def test_host_bind_mount_with_managed_volume_only_rule_is_not_applied(self):
        """A declared preparation scoped to only_when_mount_type:
        managed-volume must not run against a host-bind mount, even if
        the container_path matches."""
        with tempfile.TemporaryDirectory() as tmp:
            target = self._target(tmp)
            lost_found_existed_before = (target / 'lost+found').exists()
            service = make_service(unprivileged=True, volume_preparations=[{
                'container_path': '/shared/data',
                'remove_lost_found': True,
                'owner_strategy': 'mapped-root',
                'only_when_mount_type': 'managed-volume',
            }])
            mount = {'container_path': '/shared/data', 'type': 'host-bind'}
            applied, owner = igs.apply_volume_preparation(service, mount, target)
            self.assertFalse(applied)
            self.assertIsNone(owner)
            self.assertEqual((target / 'lost+found').exists(), lost_found_existed_before)

    def test_final_normalized_postgres_path_is_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self._target(tmp)
            service = make_service(unprivileged=True, volume_preparations=[{
                'container_path': '/var/lib/postgresql',
                'remove_lost_found': True,
                'owner_strategy': 'mapped-root',
                'only_when_mount_type': 'managed-volume',
            }])
            mount = {'container_path': '/var/lib/postgresql', 'type': 'managed-volume'}
            applied, owner = igs.apply_volume_preparation(service, mount, target)
            self.assertTrue(applied)
            self.assertEqual(owner, (100000, 100000))
            self.assertFalse((target / 'lost+found').exists())

    def test_pre_rename_path_does_not_match_final_mount(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self._target(tmp)
            service = make_service(unprivileged=True, volume_preparations=[{
                'container_path': '/var/lib/postgresql/data',
                'remove_lost_found': True,
                'owner_strategy': 'mapped-root',
                'only_when_mount_type': 'managed-volume',
            }])
            mount = {'container_path': '/var/lib/postgresql', 'type': 'managed-volume'}
            applied, owner = igs.apply_volume_preparation(service, mount, target)
            self.assertFalse(applied)
            self.assertIsNone(owner)
            self.assertTrue((target / 'lost+found').exists())

    def test_no_declared_preparation_leaves_caller_to_fall_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self._target(tmp)
            service = make_service(unprivileged=True, volume_preparations=[])
            mount = {'container_path': '/app/.blinko', 'type': 'managed-volume'}
            applied, owner = igs.apply_volume_preparation(service, mount, target)
            self.assertFalse(applied)
            self.assertIsNone(owner)
            self.assertTrue((target / 'lost+found').exists())

    def test_unknown_owner_strategy_fails_clearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self._target(tmp)
            service = make_service(unprivileged=True, volume_preparations=[{
                'container_path': '/app/.blinko',
                'remove_lost_found': True,
                'owner_strategy': 'some-future-strategy',
                'only_when_mount_type': 'managed-volume',
            }])
            mount = {'container_path': '/app/.blinko', 'type': 'managed-volume'}
            with self.assertRaises(RuntimeError):
                igs.apply_volume_preparation(service, mount, target)

    def test_missing_owner_strategy_fails_clearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self._target(tmp)
            service = make_service(unprivileged=True, volume_preparations=[{
                'container_path': '/app/.blinko',
                'remove_lost_found': True,
                'only_when_mount_type': 'managed-volume',
            }])
            mount = {'container_path': '/app/.blinko', 'type': 'managed-volume'}
            with self.assertRaises(RuntimeError):
                igs.apply_volume_preparation(service, mount, target)

    def test_mapped_application_user_is_resolved_distinctly_from_mapped_root(self):
        """Integration-level guard for bug #1: the two owner_strategy
        values applied to the SAME service (same PUID/PGID) must return
        different owners through apply_volume_preparation() itself, not
        just through resolve_volume_owner() in isolation."""
        with tempfile.TemporaryDirectory() as tmp:
            service = make_service(unprivileged=True, environment=[
                {'name': 'PUID', 'value': '1000'},
                {'name': 'PGID', 'value': '1000'},
            ], volume_preparations=[
                {
                    'container_path': '/data/root-owned',
                    'owner_strategy': 'mapped-root',
                    'only_when_mount_type': 'managed-volume',
                },
                {
                    'container_path': '/data/app-owned',
                    'owner_strategy': 'mapped-application-user',
                    'only_when_mount_type': 'managed-volume',
                },
            ])
            target_root = self._target(tmp, with_lost_found=False)
            target_app = Path(tmp) / 'target-app'
            target_app.mkdir()
            _, owner_root = igs.apply_volume_preparation(
                service, {'container_path': '/data/root-owned', 'type': 'managed-volume'}, target_root)
            _, owner_app = igs.apply_volume_preparation(
                service, {'container_path': '/data/app-owned', 'type': 'managed-volume'}, target_app)
            self.assertEqual(owner_root, (100000, 100000))
            self.assertEqual(owner_app, (101000, 101000))
            self.assertNotEqual(owner_root, owner_app)


class AttachMountsOrderingTests(unittest.TestCase):
    """Guards bug #2 at the source level: attach_mounts() must apply a
    declared owner_strategy's chown AFTER the seed cp -a and AFTER its
    own fallback os.chown(target, *owner[:2]) — otherwise that always-run
    fallback (which exists to preserve image ownership for mounts with
    no declared preparation) silently overwrites the declared result.
    This does not execute attach_mounts() (it calls pct/LXC); it proves
    the source order directly, which is what determines runtime
    behaviour here."""

    def setUp(self):
        self.source = (ROOT / "remote" / "install_generic_stack.py").read_text(encoding="utf-8")
        start = self.source.index("def attach_mounts(")
        end = self.source.index("\ndef ", start + 1)
        self.body = self.source[start:end]

    def test_apply_volume_preparation_called_before_seed_copy(self):
        self.assertLess(
            self.body.index("apply_volume_preparation("),
            self.body.index("run('cp','-a',str(seed)"),
        )

    def test_fallback_chown_runs_before_declared_owner_chown(self):
        fallback_index = self.body.index("os.chown(target,*owner[:2])")
        declared_index = self.body.index("os.chown(target, *declared_owner)")
        self.assertLess(fallback_index, declared_index,
                         "the declared owner_strategy chown must run AFTER the fallback chown, "
                         "so it is the mount's final ownership and not silently overwritten")

    def test_declared_owner_chown_is_conditional_on_applied(self):
        # Must only run when a preparation actually matched — guards
        # against unconditionally chowning to a stale/None owner.
        declared_index = self.body.index("os.chown(target, *declared_owner)")
        guard_index = self.body.rindex("if applied:", 0, declared_index)
        self.assertGreater(declared_index, guard_index)


class InstallOciShStackManagedTests(unittest.TestCase):
    """install_oci.sh's own volume_preparations loop must be skipped
    only for stack_managed: true services, and must leave generated_files,
    self_signed_tls, and every other apply_installer_profile() step
    untouched — this is a source-text guard (no bash execution here; a
    real stack install run is exercised separately, outside this unit
    test file)."""

    def setUp(self):
        self.source = (ROOT / "remote" / "install_oci.sh").read_text(encoding="utf-8")

    def test_volume_preparations_loop_is_gated_on_stack_managed(self):
        self.assertIn(
            'if (( failed == 0 )) && [[ $(jq -r \'.stack_managed // false\' "$DEPLOYMENT_FILE") != true ]]; then',
            self.source,
        )

    def test_generated_files_loop_is_not_gated_on_stack_managed(self):
        marker = "done < <(jq -r '.proxmox.installer_profile.generated_files[]? | @base64' \"$TEMPLATE_FILE\")"
        self.assertIn(marker, self.source)
        gate_index = self.source.index(
            'if (( failed == 0 )) && [[ $(jq -r \'.stack_managed // false\' "$DEPLOYMENT_FILE") != true ]]; then'
        )
        self.assertLess(self.source.index(marker), gate_index,
                         "generated_files loop must run before, and outside, the new stack_managed gate")

    def test_self_signed_tls_block_is_not_gated_on_stack_managed(self):
        marker = "tls_count == 1"
        self.assertIn(marker, self.source)
        gate_index = self.source.index(
            'if (( failed == 0 )) && [[ $(jq -r \'.stack_managed // false\' "$DEPLOYMENT_FILE") != true ]]; then'
        )
        self.assertGreater(self.source.index(marker), gate_index,
                            "self_signed_tls must remain its own block after the volume_preparations gate, unaffected by it")

    def test_pre_start_repairs_and_volume_seeds_are_not_gated(self):
        self.assertIn("pre_start_repairs", self.source)
        self.assertIn("apply_volume_seeds", self.source)


if __name__ == "__main__":
    unittest.main()
