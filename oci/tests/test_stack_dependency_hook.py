"""The start hook of a multi-container application waits for a dependency
that is being backed up instead of failing the start."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "remote" / "stack_dependency_hook.sh"

PCT = r"""#!/bin/bash
state=$STUB_STATE
id=${2:-}
case $1 in
  status) echo "status: $(cat "$state/$id.status")" ;;
  config)
    [[ -f $state/$id.status ]] || exit 2
    echo "arch: amd64"
    if [[ -f $state/$id.lock ]]; then
      left=$(cat "$state/$id.left")
      if (( left <= 0 )); then
        rm -f "$state/$id.lock"
        [[ -f $state/$id.restarted-by-vzdump ]] && echo running >"$state/$id.status"
      else
        echo $((left - 1)) >"$state/$id.left"
        echo "lock: $(cat "$state/$id.lock")"
      fi
    fi
    ;;
  start)
    echo "start $id" >>"$state/calls"
    if [[ -f $state/$id.lock ]]; then echo "CT is locked ($(cat "$state/$id.lock"))" >&2; exit 1; fi
    echo running >"$state/$id.status"
    # Like the DHCP client Proxmox leaves running for the container.
    /bin/sleep 30 >/dev/null 2>&1 &
    echo $! >>"$state/left-running"
    ;;
  *) exit 0 ;;
esac
"""


@unittest.skipUnless(shutil.which("flock") and shutil.which("jq"), "needs flock and jq")
class StackDependencyHook(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.state = self.root / "state"
        bin_dir = self.root / "bin"
        for directory in (self.state, bin_dir, self.root / "priv", self.root / "lock", self.root / "lxc"):
            directory.mkdir()
        (bin_dir / "pct").write_text(PCT)
        (bin_dir / "sleep").write_text("#!/bin/bash\nexit 0\n")
        (bin_dir / "lxc-info").write_text("#!/bin/bash\necho 4242\n")
        (bin_dir / "nsenter").write_text(
            '#!/bin/bash\necho "$*" >>"$STUB_STATE/nsenter"\n[[ -z ${STUB_NSENTER_FAILS:-} ]]\n')
        for name in ("pct", "sleep", "lxc-info", "nsenter"):
            (bin_dir / name).chmod(0o755)
        script = HOOK.read_text()
        for old, new in (("PATH=/usr/sbin:/usr/bin:/sbin:/bin", f"PATH={bin_dir}:{os.environ['PATH']}"),
                         ("/etc/pve/priv/", f"{self.root}/priv/"), ("/run/lock/", f"{self.root}/lock/"),
                         ("LXC_CONFIGS=/etc/pve/lxc", f"LXC_CONFIGS={self.root}/lxc")):
            self.assertIn(old, script)
            script = script.replace(old, new)
        self.hook = self.root / "hook.sh"
        self.hook.write_text(script)
        (self.root / "priv" / "proxmenux-stack-110.json").write_text(json.dumps({"schema": 1, "dependencies": [
            {"vmid": 112, "label": "PostgreSQL", "healthcheck": {"type": "running", "timeout_seconds": 10}},
            {"vmid": 111, "label": "Immich Machine Learning",
             "healthcheck": {"type": "running", "timeout_seconds": 10}}]}))
        for vmid in (110, 111, 112):
            self.container(vmid, "running")
        self.addCleanup(self.stop_left_running)

    def stop_left_running(self):
        path = self.state / "left-running"
        for pid in path.read_text().split() if path.exists() else []:
            subprocess.run(["kill", pid], capture_output=True)

    def container(self, vmid, status, lock=None, polls=0, restarted_by_vzdump=False):
        (self.state / f"{vmid}.status").write_text(status + "\n")
        if lock:
            (self.state / f"{vmid}.lock").write_text(lock + "\n")
            (self.state / f"{vmid}.left").write_text(f"{polls}\n")
        if restarted_by_vzdump:
            (self.state / f"{vmid}.restarted-by-vzdump").touch()

    def start(self, **environment):
        env = dict(os.environ, STUB_STATE=str(self.state), **environment)
        return subprocess.run(["bash", str(self.hook), "110", "pre-start"], capture_output=True, text=True, env=env)

    def calls(self):
        path = self.state / "calls"
        return path.read_text().split("\n")[:-1] if path.exists() else []

    def test_a_dependency_stopped_for_its_backup_is_waited_for_and_then_started(self):
        self.container(111, "stopped", lock="backup", polls=3)
        result = self.start()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("is locked (backup); waiting until it is released", result.stdout)
        self.assertIn("Immich Machine Learning (CT 111): ready.", result.stdout)
        self.assertEqual(self.calls(), ["start 111"])

    def test_what_a_started_dependency_leaves_running_does_not_keep_the_lock(self):
        self.container(111, "stopped")
        result = self.start()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), ["start 111"])
        free = subprocess.run(["flock", "-n", str(self.root / "lock" / "proxmenux-stack-110.lock"), "true"])
        self.assertEqual(free.returncode, 0)

    def test_a_dependency_that_vzdump_starts_again_is_not_started_twice(self):
        self.container(111, "stopped", lock="backup", polls=2, restarted_by_vzdump=True)
        result = self.start()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls(), [])

    def test_a_lock_that_is_never_released_ends_the_wait(self):
        self.container(111, "stopped", lock="mounted", polls=1000)
        result = self.start(PROXMENUX_STACK_OTHER_LOCK_WAIT="20")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is still locked (mounted) after 20s", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_running_dependencies_are_not_waited_for(self):
        self.container(112, "running", lock="backup", polls=1000)
        result = self.start()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("waiting", result.stdout)

    def stack_network(self, dependency_gateway):
        lxc = self.root / "lxc"
        (lxc / "110.conf").write_text(
            "hookscript: local:snippets/proxmenux-stack-dependencies.sh\n"
            "net0: name=eth0,bridge=vmbr15,firewall=1,host-managed=1,ip=10.77.5.30/24,type=veth\n"
            "net1: name=eth1,bridge=vmbr0,firewall=1,host-managed=1,ip=dhcp,type=veth\n")
        gateway = f",gw={dependency_gateway}" if dependency_gateway else ""
        (lxc / "111.conf").write_text(
            f"net0: name=eth0,bridge=vmbr15,firewall=1{gateway},host-managed=1,ip=10.77.5.31/24,type=veth\n"
            "\n[before-update]\nnet0: name=eth0,bridge=vmbr15,gw=10.77.5.30,ip=10.77.5.31/24,type=veth\n")

    def post_start(self, **environment):
        env = dict(os.environ, STUB_STATE=str(self.state), **environment)
        return subprocess.run(["bash", str(self.hook), "110", "post-start"], capture_output=True, text=True, env=env)

    def namespace_commands(self):
        path = self.state / "nsenter"
        return path.read_text().splitlines() if path.exists() else []

    def test_members_routed_through_the_main_container_get_outbound_access(self):
        self.stack_network("10.77.5.30")
        result = self.post_start()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Outbound access enabled for the private network 10.77.5.0/24 through CT 110.", result.stdout)
        commands = self.namespace_commands()
        self.assertTrue(all(command.startswith("--target 4242 --net ") for command in commands))
        self.assertIn("--target 4242 --net sysctl -qw net.ipv4.ip_forward=1", commands)
        self.assertIn("--target 4242 --net iptables -w -A PROXMENUX-EGRESS -i eth0 -o eth1 -s 10.77.5.0/24 -j ACCEPT",
                      commands)
        self.assertEqual(commands[-2], "--target 4242 --net iptables -w -A PROXMENUX-EGRESS -j DROP")
        self.assertIn("-t nat -A POSTROUTING -o eth1 -s 10.77.5.0/24 -j MASQUERADE", commands[-1])

    def test_a_private_network_without_routed_members_is_left_alone(self):
        # Only the current configuration counts, not a snapshot.
        self.stack_network(None)
        result = self.post_start()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.namespace_commands(), [])

    def test_a_gateway_that_only_shares_a_prefix_does_not_count(self):
        self.stack_network("10.77.5.3")
        result = self.post_start()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.namespace_commands(), [])

    def test_a_failed_outbound_setup_does_not_fail_the_start(self):
        self.stack_network("10.77.5.30")
        result = self.post_start(STUB_NSENTER_FAILS="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("could not be enabled", result.stderr)

    def test_updates_replace_only_published_copies_of_the_hook(self):
        script = HOOK.read_text()
        self.assertIn("--refresh", script)
        for digest in ("c28b69acd7cc8e66d3aec3e8b2ec86bda0e4f91193ec78549f1965f2c859c0d1",
                       "02c50ef17f2411ef22f4d382c51b34a7a0974a446d4a155ecb63fb1e805a7c59"):
            self.assertIn(digest, script)
        for installer in ("install_proxmenux.sh", "install_proxmenux_beta.sh"):
            self.assertIn("stack_dependency_hook.sh\" --refresh", (ROOT.parent / installer).read_text())


if __name__ == "__main__":
    unittest.main()
