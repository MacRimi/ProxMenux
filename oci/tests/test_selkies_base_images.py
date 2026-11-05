"""An image built on the LinuxServer Selkies base, but published by someone
else, receives the same GPU profile as the LinuxServer Selkies images."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from proxmenux_oci.catalog import Catalog
from proxmenux_oci.gpu import apply_selkies_contract

ARTCRAFT = ('cadcraft', 'deckcraft', 'designcraft', 'effectcraft', 'figcraft', 'filmcraft', 'gridcraft',
            'lightcraft', 'pdfcraft', 'photocraft', 'soundcraft', 'vectorcraft', 'wordcraft')


def template(reference, base):
    return {'container_contract': {'image': {'reference': reference}, 'environment': []},
            'proxmox': {'installer_profile': {'selkies': {'base': base}}}}


class SelkiesBaseImageTests(unittest.TestCase):
    def test_an_image_built_on_the_selkies_base_gets_the_gpu_profile(self):
        built = template('docker.io/junkerderprovinz/photocraft:latest',
                         'FROM ghcr.io/linuxserver/baseimage-selkies:ubunturesolute')
        apply_selkies_contract(built)
        profiles = built['proxmox']['installer_profile']['hardware_acceleration']['profiles']
        self.assertEqual([item['id'] for item in profiles], ['none', 'vaapi', 'nvidia'])

    def test_any_other_image_is_still_refused(self):
        other = template('docker.io/someone/desktop:latest', 'FROM ubuntu:24.04')
        with self.assertRaises(ValueError):
            apply_selkies_contract(copy.deepcopy(other))

    def test_every_artcraft_app_offers_the_gpu_to_its_desktop(self):
        catalog = Catalog(ROOT)
        for app in ARTCRAFT:
            with self.subTest(app=app):
                profile = catalog.compose(app)['proxmox']['installer_profile']
                vaapi = next(item for item in profile['hardware_acceleration']['profiles'] if item['id'] == 'vaapi')
                self.assertEqual(set(vaapi['environment_from_devices']),
                                 {'DRINODE', 'DRI_NODE', 'ATTACHED_DEVICES_PERMS'})
                self.assertEqual(profile['device_permissions']['environment'], 'ATTACHED_DEVICES_PERMS')
                self.assertEqual(profile['hardware_acceleration']['default'], 'none')


if __name__ == '__main__':
    unittest.main()
