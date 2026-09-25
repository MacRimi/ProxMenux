// Source-extracted, inert UI/message seams; never source administrative scripts.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const cp = require('node:child_process');
const root = path.resolve(__dirname, '..');
const read = p => fs.readFileSync(path.join(root, p), 'utf8');
const bash = (code, env = {}) => {
  const r = cp.spawnSync('bash', ['-c', code], {encoding: 'utf8', env: {...process.env, ...env}});
  assert.equal(r.status, 0, `bash fixture failed: ${r.stderr}`);
  return r.stdout.trim();
};
const func = (source, name) => {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const m = source.match(new RegExp(`(?:^|\\n)(?:function )?${escaped}\\(\\) \\{[\\s\\S]*?\\n\\}`, 'm'));
  assert.ok(m, `function ${name} present`);
  return m[0];
};
const lookup = func(read('scripts/utils.sh'), 'translate');
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'pmx-tui-wording-'));
const it = JSON.parse(read('lang/it.json'));
const newKeys = [
  'Once finished, repeat the check ({check}) to review any remaining issues.',
  'Once finished, repeat the check ({check}) to review any remaining issues before starting the PVE 8 → PVE 9 upgrade.',
  'Once finished, repeat the check ({check}) to review any remaining issues before rebooting.',
  'GPU passthrough assistant not found. Later, open {menu} → {action} from the main menu to try again.',
];
const marker = Object.fromEntries(newKeys.map((k, i) => [k, i === 3
  ? 'TRADOTTO_3 {action} {menu}' : `TRADOTTO_${i} {check} fine`]));
const setup = `LANG_DIR=${JSON.stringify(temp)}; LANGUAGE="${'${LANGUAGE:-en}'}"; ${lookup}\nmsg_warn() { printf '%s\\n' "$1"; }; msg_info2() { printf '%s\\n' "$1"; }; msg_title() { printf '%s\\n' "$1"; };`;
const store = (locale, entries) => fs.writeFileSync(path.join(temp, `${locale}.json`), JSON.stringify(entries));
store('it', it); store('synthetic', {
  ...marker,
  'Run PVE 8 to 9 check': 'CONTROLLO_LOCALIZZATO',
  'Hardware: GPUs and Coral-TPU': 'HARDWARE_LOCALIZZATO',
  'Add GPU to VM    (Intel | AMD | NVIDIA)': 'AZIONE_LOCALIZZATA',
  'Stop that VM, then choose:': 'SCELTA_LOCALIZZATA:',
});
const menuSrc = read('scripts/utilities/upgrade_pve8_to_pve9.sh');
const menuLines = menuSrc.split('\n').filter(l => /(?:^|\s)(?:3|"3") "\$\(translate .*PVE 8 to 9/.test(l));
assert.equal(menuLines.length, 2, 'both actual menu consumers');
const renderMenu = locale => menuLines.map(l => bash(setup + '\nprintf \'%s\\n\' ' + l.trim().replace(/\\$/, '').replace(/^(?:3|"3") /, '') + '\n', {LANGUAGE: locale}));
assert.deepEqual(renderMenu('en'), ['Run PVE 8 to 9 check', 'Run PVE 8 to 9 check']);
assert.deepEqual(renderMenu('it'), [it['Run PVE 8 to 9 check'], it['Run PVE 8 to 9 check']]);
assert.deepEqual(renderMenu('synthetic'), ['CONTROLLO_LOCALIZZATO', 'CONTROLLO_LOCALIZZATO']);
const locales = ['es', 'fr', 'de', 'it', 'pt', 'sk', 'sv'];
for (const locale of locales) {
  const catalog = JSON.parse(read(`lang/${locale}.json`));
  store(locale, catalog);
  const label = catalog['Run PVE 8 to 9 check'] || 'Run PVE 8 to 9 check';
  assert.deepEqual(renderMenu(locale), [label, label], `${locale}: both menus`);
}
const checker = read('scripts/utilities/pve8to9_check.sh');
const title = checker.split('\n').find(l => /^msg_title "\$\(translate "Run PVE 8 to 9 check"\)"$/.test(l));
assert.ok(title);
const checkHelp = checker.match(/^\s*check_help="\$\(translate "Once finished,[^\n]+\n(?:[^\n]*\n){2}\s*msg_info2 "\$check_help"/m)?.[0];
const upgradeHelp = [...menuSrc.matchAll(/^\s*check_help="\$\(translate "Once finished,[^\n]+\n(?:[^\n]*\n){2}\s*msg_info2 "\$check_help"/gm)].map(m => m[0]);
assert.equal(upgradeHelp.length, 2);
const helpLines = [checkHelp, ...upgradeHelp];
const renderHelp = (locale, entries) => {
  if (entries) store(locale, entries);
  return helpLines.map(l => bash(setup + '\n' + l.trim() + '\n', {LANGUAGE: locale}));
};
const helpEn = renderHelp('en');
assert.equal(helpEn.length, 3);
for (const line of helpEn) {
  assert.ok(line.includes('Run PVE 8 to 9 check'), line);
  assert.ok(line.includes('repeat the check (Run PVE 8 to 9 check) to review any remaining issues'), line);
  assert.ok(!line.includes('{check}') && !line.includes('all issues are resolved') && !line.includes('run Run'), line);
}
const helpIt = renderHelp('it'); // New keys absent from shipped Italian cache: complete English fallback.
for (const line of helpIt) assert.ok(line.includes(it['Run PVE 8 to 9 check']), line);
for (const locale of locales) {
  const catalog = JSON.parse(read(`lang/${locale}.json`));
  store(locale, catalog);
  const label = catalog['Run PVE 8 to 9 check'] || 'Run PVE 8 to 9 check';
  for (const line of renderHelp(locale)) assert.ok(line.includes(`(${label})`) && !line.includes('{check}'), `${locale}: ${line}`);
}
const helpSynthetic = renderHelp('synthetic');
for (const [i, line] of helpSynthetic.entries()) assert.equal(line, `TRADOTTO_${i} CONTROLLO_LOCALIZZATO fine`);
const brokenHelp = renderHelp('malformed', {...marker, 'Run PVE 8 to 9 check': 'CONTROLLO_LOCALIZZATO', [newKeys[0]]: 'NON_VALIDA {wrong}'});
assert.ok(brokenHelp[0].includes('Once finished, repeat the check (CONTROLLO_LOCALIZZATO)'), brokenHelp[0]);
const vmPaths = ['scripts/vm/synology.sh', 'scripts/vm/vm_creator.sh', 'scripts/vm/zimaos.sh'];
const vmFunctions = vmPaths.map(p => func(read(p), 'run_gpu_passthrough_wizard'));
const renderVm = locale => vmFunctions.map(fn => bash(setup + `\nLOCAL_SCRIPTS=${JSON.stringify(path.join(temp, 'absent'))}; WIZARD_ADD_GPU=yes; ` + fn + '\nrun_gpu_passthrough_wizard\n', {LANGUAGE: locale}));
for (const line of renderVm('en')) {
  assert.ok(line.includes('Hardware: GPUs and Coral-TPU → Add GPU to VM    (Intel | AMD | NVIDIA)'), line);
  assert.ok(!line.includes('Hardware Graphics') && !line.includes('{menu}') && !line.includes('{action}'), line);
}
for (const line of renderVm('it')) {
  assert.ok(line.includes(`${it['Hardware: GPUs and Coral-TPU']} → ${it['Add GPU to VM    (Intel | AMD | NVIDIA)']}`), line);
  assert.ok(!line.includes('Hardware Graphics'), line);
}
for (const locale of locales) {
  const catalog = JSON.parse(read(`lang/${locale}.json`));
  const menu = catalog['Hardware: GPUs and Coral-TPU'] || 'Hardware: GPUs and Coral-TPU';
  const action = catalog['Add GPU to VM    (Intel | AMD | NVIDIA)'] || 'Add GPU to VM    (Intel | AMD | NVIDIA)';
  for (const line of renderVm(locale)) assert.ok(line.includes(`${menu} → ${action}`) && !line.includes('{menu}') && !line.includes('{action}'), `${locale}: ${line}`);
}
for (const line of renderVm('synthetic')) assert.ok(line.includes('AZIONE_LOCALIZZATA HARDWARE_LOCALIZZATO'), line);
store('malformed', {...marker, 'Hardware: GPUs and Coral-TPU': 'MENU', 'Add GPU to VM    (Intel | AMD | NVIDIA)': 'ACTION', [newKeys[3]]: 'BROKEN {menu} {wrong}'});
for (const line of renderVm('malformed')) assert.ok(line.startsWith('GPU passthrough assistant not found.') && line.includes('MENU → ACTION'), line);
store('malformed', {...marker, 'Hardware: GPUs and Coral-TPU': 'MENU', 'Add GPU to VM    (Intel | AMD | NVIDIA)': 'ACTION', [newKeys[3]]: 'BROKEN {action} {wrong}'});
for (const line of renderVm('malformed')) assert.ok(line.startsWith('GPU passthrough assistant not found.') && line.includes('MENU → ACTION'), line);
store('malformed', {...marker, 'Hardware: GPUs and Coral-TPU': 'MENU', 'Add GPU to VM    (Intel | AMD | NVIDIA)': 'ACTION', [newKeys[3]]: 'BROKEN {wrong}'});
for (const line of renderVm('malformed')) assert.ok(line.startsWith('GPU passthrough assistant not found.') && line.includes('MENU → ACTION'), line);
const additionalLead = read('scripts/gpu_tpu/add_gpu_vm.sh').split('\n').find(l => l.includes('Stop that VM, then choose:') && l.includes('msg+='));
assert.ok(additionalLead, 'busy-VM guidance has a standalone instruction before the rendered labels');
assert.equal(bash(setup + '\n' + additionalLead.trim() + '\nprintf \'%b\\n\' "$msg"', {LANGUAGE: 'synthetic'}), 'SCELTA_LOCALIZZATA:');
assert.ok(!read('scripts/gpu_tpu/add_gpu_vm.sh').includes("msg+=\"$(translate 'to move the GPU safely.')\""), 'no clipped tail follows the route');
const additionalNav = read('scripts/gpu_tpu/add_gpu_vm.sh').split('\n').find(l => l.includes('→') && l.includes('Add GPU to VM') && l.includes('msg+='));
assert.ok(additionalNav?.includes("$(translate 'Hardware: GPUs and Coral-TPU')"), 'busy-VM guidance uses actual menu label');
assert.ok(additionalNav?.includes("$(translate 'Add GPU to VM    (Intel | AMD | NVIDIA)')"), 'busy-VM guidance uses actual action label');
for (const locale of ['en', 'it', 'synthetic']) {
  const label = locale === 'en' ? 'Hardware: GPUs and Coral-TPU' : locale === 'it' ? it['Hardware: GPUs and Coral-TPU'] : 'HARDWARE_LOCALIZZATO';
  const action = locale === 'en' ? 'Add GPU to VM    (Intel | AMD | NVIDIA)' : locale === 'it' ? it['Add GPU to VM    (Intel | AMD | NVIDIA)'] : 'AZIONE_LOCALIZZATA';
  const rendered = bash(setup + `\nmsg=''; ${additionalNav.trim()}; printf '%b\\n' "$msg"`, {LANGUAGE: locale});
  assert.equal(rendered, `${label} → ${action}`);
}
// Actual checker disables localization before both title and help; no behavior changed here.
const bypass = func(checker, 'disable_translation_post_upgrade');
assert.equal(bash(setup + `\n${bypass}\ndisable_translation_post_upgrade\n` + title), 'Run PVE 8 to 9 check');
assert.equal(bash(setup + `\n${bypass}\ndisable_translation_post_upgrade\n` + checkHelp), helpEn[0]);
const extraction = cp.spawnSync('python3', ['-c', `import importlib.util,pathlib
p=pathlib.Path('.github/scripts/build_translation_cache.py'); s=importlib.util.spec_from_file_location('cache',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
keys=set(m.extract_translate_texts(pathlib.Path('scripts')))
required=${JSON.stringify(['Run PVE 8 to 9 check', ...newKeys, 'Hardware: GPUs and Coral-TPU', 'Add GPU to VM    (Intel | AMD | NVIDIA)'])}
assert set(required)<=keys, set(required)-keys
print('EXTRACTED',len(required))`], {cwd: root, encoding: 'utf8'});
assert.equal(extraction.status, 0, extraction.stderr);
// No source catalog edits; synthetic translation and malformed placeholders only live in scratch.
assert.ok(!Object.keys(it).some(k => newKeys.includes(k)));
fs.rmSync(temp, {recursive: true, force: true});
console.log('PASS: extracted upgrade/GPU consumers, seven caches/fallbacks, synthetic and malformed placeholders, real extractor');
