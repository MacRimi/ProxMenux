"""Tailscale keeps starting once its web client is on: the LAN interface listens
on the address of eth0, not on 0.0.0.0, and subnet routes get forwarding."""
import copy
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'remote'))

import oci_instance_transaction as transaction  # noqa: E402


def recipe():
    return json.loads((ROOT / 'catalog/apps/tailscale.json').read_text())


class RecipeTests(unittest.TestCase):
    def test_the_recipe_and_its_overlay_carry_the_current_command(self):
        template = recipe()
        self.assertEqual(template['proxmox']['installer_profile']['runtime']['compose_entrypoint'],
                         transaction.TAILSCALE_ENTRYPOINT)
        self.assertEqual(template['compose_stack']['services'][0]['compose']['entrypoint'],
                         transaction.TAILSCALE_ENTRYPOINT)
        overlay = json.loads((ROOT / 'catalog/overlays/tailscale.json').read_text())
        self.assertEqual(overlay['proxmox']['installer_profile']['runtime']['compose_entrypoint'],
                         transaction.TAILSCALE_ENTRYPOINT)

    def test_a_saved_recipe_with_the_previous_command_gets_the_current_one(self):
        template = recipe()
        template['proxmox']['installer_profile']['runtime']['compose_entrypoint'] = \
            transaction.TAILSCALE_PREVIOUS_ENTRYPOINT
        contract = transaction.with_default_healthcheck({'template': template})
        self.assertEqual(contract['template']['proxmox']['installer_profile']['runtime']['compose_entrypoint'],
                         transaction.TAILSCALE_ENTRYPOINT)

    def test_other_commands_and_applications_are_left_alone(self):
        for template in ({'id': 'image-tailscale', 'proxmox': {'installer_profile': {'runtime': {
                              'compose_entrypoint': '/bin/sh -c "tailscaled & tailscale web --listen 0.0.0.0:8080"'}}}},
                         {'id': 'image-other', 'proxmox': {'installer_profile': {'runtime': {
                              'compose_entrypoint': transaction.TAILSCALE_PREVIOUS_ENTRYPOINT}}}}):
            before = copy.deepcopy(template)
            transaction.current_recipe(template)
            self.assertEqual(template, before)


class CommandTests(unittest.TestCase):
    def run_command(self, address):
        with tempfile.TemporaryDirectory() as temp:
            stubs = Path(temp)
            inet = f'    inet {address}/24 brd 192.0.2.255 scope global eth0' if address else ''
            for name, body in (('sysctl', 'echo "sysctl $*" >> "$TRACE"'), ('tailscaled', 'echo tailscaled >> "$TRACE"'),
                               ('sleep', ':'), ('ip', f"printf '%s\\n' '{inet}'"),
                               ('tailscale', 'echo "tailscale $*" >> "$TRACE"')):
                path = stubs / name
                path.write_text(f'#!/bin/sh\n{body}\n')
                path.chmod(0o755)
            trace = stubs / 'trace'
            argv = shlex.split(transaction.TAILSCALE_ENTRYPOINT)
            subprocess.run(argv, env=dict(os.environ, PATH=f'{stubs}:/usr/bin:/bin', TRACE=str(trace)),
                           check=True, timeout=30)
            return trace.read_text().splitlines()

    def test_the_web_interface_listens_on_the_lan_address(self):
        trace = self.run_command('192.0.2.5')
        self.assertIn('sysctl -w net.ipv4.ip_forward=1 net.ipv6.conf.all.forwarding=1', trace)
        self.assertIn('tailscaled', trace)
        self.assertEqual(trace[-1], 'tailscale web --listen 192.0.2.5:5252')

    def test_without_an_address_it_listens_everywhere_as_before(self):
        self.assertEqual(self.run_command('')[-1], 'tailscale web --listen 0.0.0.0:5252')


if __name__ == '__main__':
    unittest.main()
