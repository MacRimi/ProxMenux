"""AI applications get RAM, cores and a context window that fit together and
fit the node; installed ones are offered the same only where nothing was changed."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from proxmenux_oci import host  # noqa: E402
from proxmenux_oci.catalog import Catalog  # noqa: E402
from proxmenux_oci.installer import (DEFAULT_MODE, InstallError, build_deployment,  # noqa: E402
                                     cache_size_factor, context_budget, fit_memory_to_host, proportional_cores,
                                     value_for_memory)
from proxmenux_oci.recommended import recommendation  # noqa: E402
from test_advanced_flow_order import RecordingUI, storages  # noqa: E402

CONTEXT = [[0, '8192'], [4096, '16384'], [6144, '32768'], [10240, '65536'], [24576, '131072']]


def env(template):
    return {item['name']: item for item in template['container_contract']['environment']}


class ResourceRules(unittest.TestCase):
    def test_memory_is_lowered_only_when_the_node_cannot_give_it(self):
        self.assertEqual(fit_memory_to_host(8192, 16000), (8192, None))
        self.assertEqual(fit_memory_to_host(8192, None), (8192, None))
        fitted, note = fit_memory_to_host(8192, 6000)
        self.assertEqual(fitted, 4352)
        self.assertIn('6000', note)

    def test_cores_follow_the_memory_within_the_node(self):
        self.assertEqual(proportional_cores(2, 8192, 16), 4)
        self.assertEqual(proportional_cores(2, 40960, 16), 8)
        self.assertEqual(proportional_cores(2, 40960, 4), 4)
        self.assertEqual(proportional_cores(4, 1024, 16), 4)
        self.assertEqual(proportional_cores(2, 1024, None), 2)

    def test_context_follows_the_container_memory(self):
        self.assertEqual(value_for_memory(CONTEXT, 3072), '8192')
        self.assertEqual(value_for_memory(CONTEXT, 4096), '16384')
        self.assertEqual(value_for_memory(CONTEXT, 8192), '32768')
        self.assertEqual(value_for_memory(CONTEXT, 12288), '65536')
        self.assertEqual(value_for_memory(CONTEXT, 32768), '131072')
        self.assertIsNone(value_for_memory(None, 8192))
        for bad in ([[0, 8192]], [['0', '8192']], [[True, '8192']], [[0]]):
            with self.subTest(bad=bad), self.assertRaises(InstallError):
                value_for_memory(bad, 8192)


class CatalogRecipes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog(ROOT)

    def profile_environment(self, template):
        return {p['id']: {e['name']: e['value'] for e in p.get('environment') or []}
                for p in template['proxmox']['installer_profile']['hardware_acceleration']['profiles']}

    def test_model_servers_get_memory_cores_and_a_memory_dependent_context(self):
        for app in ('ollama', 'open-webui-ollama'):
            with self.subTest(app=app):
                template = self.catalog.compose(app)
                defaults = template['proxmox']['defaults']
                self.assertEqual((defaults['memory_mb'], defaults['cores']), (8192, 4))
                self.assertEqual(env(template)['OLLAMA_CONTEXT_LENGTH']['default_by_memory_mb'], CONTEXT)
                self.assertEqual(self.catalog.schema_errors(template) or [], [])

    def test_ollama_compresses_its_cache_only_where_flash_attention_is_certain(self):
        # Ollama compresses keys and values together; without flash attention
        # the model does not load, so only the CPU profile, where it is always
        # available, sets it.
        profiles = self.profile_environment(self.catalog.compose('ollama'))
        self.assertEqual(profiles['cpu'].get('OLLAMA_KV_CACHE_TYPE'), 'q8_0')
        for profile in ('nvidia', 'vulkan', 'rocm'):
            self.assertNotIn('OLLAMA_KV_CACHE_TYPE', profiles[profile])
        self.assertNotIn('OLLAMA_KV_CACHE_TYPE', env(self.catalog.compose('ollama')))
        # The bundled server of Open WebUI has no GPU profile: it runs on the CPU.
        self.assertEqual(env(self.catalog.compose('open-webui-ollama'))['OLLAMA_KV_CACHE_TYPE']['example'], 'q8_0')

    def test_llamacpp_quantizes_values_only_on_the_cpu(self):
        template = self.catalog.compose('llamacpp')
        variables = env(template)
        self.assertEqual(variables['LLAMA_ARG_CTX_SIZE']['default_by_memory_mb'], CONTEXT)
        # Keys work quantized with or without flash attention.
        self.assertEqual(variables['LLAMA_ARG_CACHE_TYPE_K']['example'], 'q8_0')
        profiles = self.profile_environment(template)
        self.assertEqual(profiles['cpu'].get('LLAMA_ARG_CACHE_TYPE_V'), 'q8_0')
        for profile in ('nvidia', 'vulkan', 'rocm', 'intel'):
            self.assertNotIn('LLAMA_ARG_CACHE_TYPE_V', profiles[profile])
        # Measured on Intel UHD, Radeon 680M and Vega iGPUs: flash attention on
        # its own, moderate batches and F16 off are fast, and still load and do
        # not lose the device when flash attention turns itself off.
        self.assertNotIn('LLAMA_ARG_FLASH_ATTN', profiles['vulkan'])
        self.assertEqual((profiles['vulkan']['LLAMA_ARG_UBATCH'], profiles['vulkan']['LLAMA_ARG_BATCH'],
                          profiles['vulkan']['GGML_VK_DISABLE_F16']), ('128', '512', '1'))
        self.assertNotIn('GGML_VK_DISABLE_ASYNC', profiles['vulkan'])
        # 999 forced every layer and the cache into VRAM: a small GPU could not
        # load the model. auto lets llama.cpp split it with the CPU.
        self.assertEqual(variables['LLAMA_ARG_N_GPU_LAYERS']['example'], 'auto')
        self.assertEqual(self.catalog.schema_errors(template) or [], [])

    def test_agents_and_frontends_get_room_for_their_tools(self):
        for app in ('hermes', 'openclaw', 'anythingllm', 'open-webui', 'open-webui-cuda', 'faster-whisper'):
            with self.subTest(app=app):
                defaults = self.catalog.compose(app)['proxmox']['defaults']
                self.assertEqual((defaults['memory_mb'], defaults['cores']), (4096, 2))

    def test_an_added_variable_never_duplicates_one_the_template_has(self):
        names = [item['name'] for item in self.catalog.compose('llamacpp')['container_contract']['environment']]
        self.assertEqual(len(names), len(set(names)))


class InstalledApplications(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.latest = Catalog(ROOT).compose('ollama')

    def installed(self, memory=2048, cores=2, environment=(), profile='cpu'):
        old = copy.deepcopy(self.latest)
        old['proxmox']['defaults'].update(memory_mb=2048, cores=2)
        old['container_contract']['environment'] = [e for e in old['container_contract']['environment']
                                                    if e.get('source') != 'proxmenux-overlay']
        for entry in old['proxmox']['installer_profile']['hardware_acceleration']['profiles']:
            entry['environment'] = [e for e in entry.get('environment') or [] if e['name'] != 'OLLAMA_KV_CACHE_TYPE']
        return {'vmid': 101, 'template': old,
                'deployment': {'resources': {'memory_mb': memory, 'cores': cores}, 'hardware_profile': profile,
                               'environment': [dict(e) for e in environment]}}

    def values(self, offer):
        return {e['name']: e['value'] for e in offer['candidate']['deployment']['environment']}

    def test_untouched_defaults_are_offered_the_new_ones(self):
        offer = recommendation(self.installed(), self.latest, 16000, 16)
        self.assertEqual(offer['candidate']['deployment']['resources'],
                         {'memory_mb': 8192, 'cores': 4})
        self.assertEqual(self.values(offer), {'OLLAMA_CONTEXT_LENGTH': '32768', 'OLLAMA_KV_CACHE_TYPE': 'q8_0'})

    def test_a_gpu_installation_gets_its_vram_context_and_no_compressed_cache(self):
        offer = recommendation(self.installed(profile='nvidia'), self.latest, 64000, 16,
                                {'vendor': 'nvidia', 'dedicated_mb': 24576})
        self.assertEqual(self.values(offer), {'OLLAMA_CONTEXT_LENGTH': '65536'})

    def test_a_small_node_gets_what_fits(self):
        offer = recommendation(self.installed(), self.latest, 6000, 4)
        self.assertEqual(offer['candidate']['deployment']['resources']['memory_mb'], 4352)
        self.assertEqual(self.values(offer)['OLLAMA_CONTEXT_LENGTH'], '16384')

    def test_what_the_user_changed_is_kept(self):
        offer = recommendation(self.installed(memory=4096, cores=6,
                                              environment=[{'name': 'OLLAMA_CONTEXT_LENGTH', 'value': '16384',
                                                            'sensitive': False}]), self.latest, 16000, 16)
        self.assertEqual(offer['candidate']['deployment']['resources'], {'memory_mb': 4096, 'cores': 6})
        self.assertEqual(self.values(offer), {'OLLAMA_CONTEXT_LENGTH': '16384', 'OLLAMA_KV_CACHE_TYPE': 'q8_0'})

    def test_nothing_to_offer_is_no_offer(self):
        record = self.installed()
        record['template'] = copy.deepcopy(self.latest)
        record['deployment'].update(resources={'memory_mb': 8192, 'cores': 4},
                                    environment=[{'name': 'OLLAMA_CONTEXT_LENGTH', 'value': '32768'},
                                                 {'name': 'OLLAMA_KV_CACHE_TYPE', 'value': 'q8_0'}])
        self.assertIsNone(recommendation(record, self.latest, 16000, 16))

    def test_stacks_are_not_offered(self):
        record = self.installed()
        record['stack'] = {'id': 'x'}
        self.assertIsNone(recommendation(record, self.latest, 16000, 16))


class InstalledLlamaCpp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.latest = Catalog(ROOT).compose('llamacpp')

    def installed(self, layers='999', context='8192'):
        old = copy.deepcopy(self.latest)
        old['container_contract']['environment'] = [dict(e) for e in old['container_contract']['environment']
                                                    if e.get('source') != 'proxmenux-overlay']
        for item in old['container_contract']['environment']:
            item.pop('default_by_memory_mb', None)
            item['example'] = {'LLAMA_ARG_N_GPU_LAYERS': '999', 'LLAMA_ARG_CTX_SIZE': '8192'}.get(item['name'], item['example'])
        for entry in old['proxmox']['installer_profile']['hardware_acceleration']['profiles']:
            entry['environment'] = [e for e in entry.get('environment') or [] if e['name'] != 'LLAMA_ARG_CACHE_TYPE_V']
        old['proxmox']['defaults'].update(memory_mb=8192, cores=4)
        return {'vmid': 135, 'template': old, 'deployment': {
            'resources': {'memory_mb': 8192, 'cores': 4}, 'hardware_profile': 'nvidia',
            'environment': [{'name': 'LLAMA_ARG_N_GPU_LAYERS', 'value': layers, 'sensitive': False},
                            {'name': 'LLAMA_ARG_CTX_SIZE', 'value': context, 'sensitive': False}]}}

    def test_an_untouched_gpu_installation_gets_auto_layers_with_its_larger_context(self):
        offer = recommendation(self.installed(), self.latest, 64000, 12, {'vendor': 'nvidia', 'dedicated_mb': 4096})
        values = {e['name']: e['value'] for e in offer['candidate']['deployment']['environment']}
        self.assertEqual(values, {'LLAMA_ARG_N_GPU_LAYERS': 'auto', 'LLAMA_ARG_CTX_SIZE': '16384',
                                  'LLAMA_ARG_CACHE_TYPE_K': 'q8_0'})

    def test_tuned_values_are_kept(self):
        offer = recommendation(self.installed(layers='20', context='65536'), self.latest, 64000, 12,
                                {'vendor': 'nvidia', 'dedicated_mb': 4096})
        values = {e['name']: e['value'] for e in offer['candidate']['deployment']['environment']}
        self.assertEqual((values['LLAMA_ARG_N_GPU_LAYERS'], values['LLAMA_ARG_CTX_SIZE']), ('20', '65536'))


class GpuMemory(unittest.TestCase):
    def node(self, root, name, vendor, vram=None, gtt=None):
        device = Path(root) / 'sys/class/drm' / name / 'device'
        device.mkdir(parents=True)
        (device / 'vendor').write_text(vendor)
        for field, value in (('mem_info_vram_total', vram), ('mem_info_gtt_total', gtt)):
            if value is not None:
                (device / field).write_text(str(value))

    def test_each_gpu_reports_its_own_and_its_shared_memory(self):
        with tempfile.TemporaryDirectory() as root:
            self.node(root, 'renderD128', '0x1002', 16 * 2**30, 31 * 2**30)
            self.node(root, 'renderD129', '0x1002', 512 * 2**20, 7680 * 2**20)
            self.node(root, 'renderD130', '0x8086')
            dri = lambda n: [{'host_path': f'/dev/dri/renderD{n}'}]
            self.assertEqual(host.gpu_memory('rocm', dri(128), Path(root)),
                             {'vendor': 'amd', 'dedicated_mb': 16384, 'shared_mb': 31744})
            self.assertEqual(host.gpu_memory('vulkan', dri(129), Path(root)),
                             {'vendor': 'amd', 'dedicated_mb': 512, 'shared_mb': 7680})
            self.assertEqual(host.gpu_memory('vulkan', dri(130), Path(root)),
                             {'vendor': 'intel', 'dedicated_mb': 0, 'shared_mb': 0})
            self.assertEqual(host.gpu_memory('cpu', [], Path(root))['vendor'], None)

    def test_nvidia_memory_is_the_sum_of_its_gpus(self):
        done = type('Done', (), {'stdout': '12288\n12288\n'})()
        with patch.object(host.subprocess, 'run', return_value=done):
            self.assertEqual(host.gpu_memory_mb('nvidia', []), 24576)

    def test_the_cache_type_scales_the_memory_the_context_needs(self):
        self.assertEqual(cache_size_factor('OLLAMA_CONTEXT_LENGTH', [{'name': 'OLLAMA_KV_CACHE_TYPE', 'value': 'q8_0'}]), 1)
        self.assertEqual(cache_size_factor('OLLAMA_CONTEXT_LENGTH', []), 2)
        self.assertEqual(cache_size_factor('LLAMA_ARG_CTX_SIZE', [{'name': 'LLAMA_ARG_CACHE_TYPE_K', 'value': 'q8_0'}]), 1.5)
        self.assertEqual(cache_size_factor('LLAMA_ARG_CTX_SIZE', [{'name': 'LLAMA_ARG_CACHE_TYPE_K', 'value': 'q8_0'},
                                                                  {'name': 'LLAMA_ARG_CACHE_TYPE_V', 'value': 'q8_0'}]), 1)

    def test_the_context_follows_where_the_model_really_lives(self):
        self.assertEqual(context_budget(8192, None), 8192)
        self.assertEqual(context_budget(8192, {'vendor': 'nvidia', 'dedicated_mb': 24576}), 24576)
        self.assertEqual(context_budget(8192, {'vendor': 'nvidia', 'dedicated_mb': 4096}), 8192)
        self.assertEqual(context_budget(8192, {'vendor': 'amd', 'dedicated_mb': 16384, 'shared_mb': 31744}), 16384)
        # An AMD APU maps system memory outside the container.
        self.assertEqual(context_budget(8192, {'vendor': 'amd', 'dedicated_mb': 512, 'shared_mb': 3800}), 3800)
        # An Intel iGPU allocates inside the container, next to the CPU's copy.
        self.assertEqual(context_budget(12288, {'vendor': 'intel', 'dedicated_mb': 0}), 8192)


@patch('proxmenux_oci.installer.host.gpus', return_value={'intel': [], 'amd': [], 'nvidia': True})
@patch('proxmenux_oci.installer._profile_usable', return_value=True)
@patch('proxmenux_oci.i18n.language', return_value='en')
@patch('proxmenux_oci.installer.host.storages', side_effect=storages)
@patch('proxmenux_oci.installer.host.bridges', return_value=[{'iface': 'vmbr0', 'cidr': '192.0.2.10/24'}])
@patch('proxmenux_oci.installer.host.timezone', return_value='Europe/Madrid')
@patch('proxmenux_oci.installer.host.memory_total_mb', return_value=32768)
@patch('proxmenux_oci.installer.host.cpu_count', return_value=16)
class InstallationPlan(unittest.TestCase):
    catalog = Catalog(ROOT)

    def plan(self, app, profile, gpu):
        template = self.catalog.compose(app)
        prompt = template['proxmox']['installer_profile']['hardware_acceleration']['prompt']
        with patch('proxmenux_oci.installer.host.gpu_memory', return_value=gpu):
            plan = build_deployment(template, RecordingUI({prompt: profile}), DEFAULT_MODE)
        return plan, {e['name']: e['value'] for e in plan['environment']}

    def test_the_context_is_decided_after_the_gpu_is_chosen(self, *_):
        plan, values = self.plan('ollama', 'cpu', {'vendor': None})
        self.assertEqual((plan['resources']['memory_mb'], plan['resources']['cores']), (8192, 4))
        self.assertEqual((values['OLLAMA_CONTEXT_LENGTH'], values['OLLAMA_KV_CACHE_TYPE']), ('32768', 'q8_0'))
        # An uncompressed cache takes twice the memory the tables are measured with.
        _, values = self.plan('ollama', 'nvidia', {'vendor': 'nvidia', 'dedicated_mb': 24576})
        self.assertEqual(values['OLLAMA_CONTEXT_LENGTH'], '65536')
        self.assertNotIn('OLLAMA_KV_CACHE_TYPE', values)
        # Keys compressed, values not: 1.5 times the measured cache.
        _, values = self.plan('llamacpp', 'vulkan', {'vendor': 'amd', 'dedicated_mb': 16384, 'shared_mb': 31744})
        self.assertEqual((values['LLAMA_ARG_CTX_SIZE'], values['LLAMA_ARG_CACHE_TYPE_K']), ('65536', 'q8_0'))
        self.assertNotIn('LLAMA_ARG_CACHE_TYPE_V', values)

    def test_an_intel_integrated_gpu_gets_room_in_the_container(self, *_):
        plan, values = self.plan('ollama', 'vulkan', {'vendor': 'intel', 'dedicated_mb': 0, 'shared_mb': 0})
        self.assertEqual((plan['resources']['memory_mb'], plan['resources']['cores']), (12288, 6))
        self.assertEqual(values['OLLAMA_CONTEXT_LENGTH'], '16384')

    def test_an_amd_integrated_gpu_uses_the_memory_it_maps(self, *_):
        plan, values = self.plan('ollama', 'vulkan', {'vendor': 'amd', 'dedicated_mb': 512, 'shared_mb': 14560})
        self.assertEqual(plan['resources']['memory_mb'], 8192)
        self.assertEqual(values['OLLAMA_CONTEXT_LENGTH'], '32768')

    def test_a_small_node_gets_less_memory_and_a_context_that_fits(self, *mocks):
        with patch('proxmenux_oci.installer.host.memory_total_mb', return_value=6000):
            plan, values = self.plan('llamacpp', 'cpu', {'vendor': None})
        self.assertEqual(plan['resources']['memory_mb'], 4352)
        self.assertEqual((values['LLAMA_ARG_CTX_SIZE'], values['LLAMA_ARG_CACHE_TYPE_V']), ('16384', 'q8_0'))

    def test_a_large_gpu_image_gets_the_disk_it_needs(self, *_):
        for profile, minimum in (('intel', 16), ('rocm', 32)):
            with self.subTest(profile=profile):
                plan, _ = self.plan('llamacpp', profile, {'vendor': None})
                declared = next(p for p in self.catalog.compose('llamacpp')['proxmox']['installer_profile'][
                    'hardware_acceleration']['profiles'] if p['id'] == profile).get('rootfs_minimum_gb')
                self.assertGreaterEqual(plan['rootfs']['size_gb'], declared or 8)
                if minimum:
                    self.assertEqual(declared, minimum)


if __name__ == '__main__':
    unittest.main()
