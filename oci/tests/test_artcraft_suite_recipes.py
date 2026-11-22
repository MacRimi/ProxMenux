"""Shared files, image identity and desktop runtime survive catalog composition."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'remote'),str(ROOT/'tests')]
from proxmenux_oci.catalog import Catalog
from proxmenux_oci.custom import template_from_oci_compose
from proxmenux_oci.installer import build_deployment,DEFAULT_MODE,ADVANCED_MODE
from test_advanced_flow_order import RecordingUI,storages,addresses
APPS=('cadcraft','deckcraft','designcraft','effectcraft','figcraft','filmcraft','gridcraft','lightcraft','pdfcraft','photocraft','soundcraft','vectorcraft','wordcraft')

class ArtCraftRecipeTests(unittest.TestCase):
 def test_native_images_remain_distinct_from_flatpak_and_wasm_builds(self):
  catalog=Catalog(ROOT)
  for app in APPS:
   with self.subTest(app=app):
    t=catalog.compose(app);catalog.validate(t)
    self.assertEqual(t['container_contract']['image']['reference'],'docker.io/junkerderprovinz/'+app+':latest')
    self.assertEqual(t['catalog_ui']['author'],'junkerderprovinz')
    self.assertEqual(t['catalog_ui']['repository'],'https://github.com/storytold/'+app)
    self.assertEqual(t['catalog_ui']['architectures'],['amd64','arm64'])
    self.assertEqual(t['proxmox']['image_metadata_policy']['entrypoint'],'import-from-oci-image')
    self.assertTrue(t['catalog_ui']['icon'].endswith('/'+app+'.png'))
    self.assertFalse(t['compatibility']['validated'])

 def test_import_preserves_document_storage_backup_and_runtime_mounts(self):
  catalog=Catalog(ROOT)
  for app in APPS:
   with self.subTest(app=app):
    t=template_from_oci_compose(json.dumps(catalog.compose(app)));catalog.validate(t)
    volumes={m['container_path']:m for m in t['container_contract']['volumes']}
    self.assertEqual(set(volumes),{'/config','/storage'})
    self.assertEqual(volumes['/config']['installation_choice'],['managed-volume'])
    self.assertEqual(volumes['/storage']['installation_choice'],['managed-volume','host-bind'])
    self.assertTrue(all(m['managed_volume']['backup'] and not m['read_only'] for m in volumes.values()))
    runtime={m['container_path']:m for m in t['proxmox']['installer_profile']['tmpfs_mounts']}
    self.assertEqual(runtime['/dev/shm']['default_size_mb'],1024)
    self.assertIn('/run/nginx',runtime)
    self.assertEqual(t['proxmox']['installer_profile']['startup_healthcheck']['port'],3000)
    self.assertEqual(t['catalog_ui']['launch']['port'],3001)

 def test_both_wizards_offer_shared_documents_without_exposing_private_config(self):
  from contextlib import ExitStack
  with ExitStack() as stack:
   for target,value in [('proxmenux_oci.installer.host.storages',storages),('proxmenux_oci.installer.access.ask_addresses',addresses)]:stack.enter_context(patch(target,side_effect=value))
   stack.enter_context(patch('proxmenux_oci.i18n.language',return_value='en'))
   stack.enter_context(patch('proxmenux_oci.installer.host.bridges',return_value=[{'iface':'vmbr0','cidr':'192.0.2.10/24'}]))
   stack.enter_context(patch('proxmenux_oci.installer.host.timezone',return_value='Europe/Madrid'))
   stack.enter_context(patch('proxmenux_oci.installer.host.gpus',return_value={'intel':[],'amd':[],'nvidia':False}))
   stack.enter_context(patch('proxmenux_oci.installer.access.ask_ipv4',return_value=('dhcp',None)))
   for app in APPS:
    for mode in (DEFAULT_MODE,ADVANCED_MODE):
     with self.subTest(app=app,mode=mode):
      plan=build_deployment(Catalog(ROOT).compose(app),RecordingUI({'Where to store /storage':'host-bind'}),mode)
      mounts={m['container_path']:m for m in plan['mounts']}
      self.assertEqual(mounts['/config']['type'],'managed-volume')
      self.assertTrue(mounts['/config']['backup'])
      self.assertEqual(mounts['/storage']['type'],'host-bind')
      self.assertFalse(mounts['/storage']['backup'])
      self.assertTrue(plan['security']['unprivileged'])

if __name__=='__main__':unittest.main()
