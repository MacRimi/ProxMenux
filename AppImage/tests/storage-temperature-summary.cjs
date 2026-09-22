// Run from AppImage: node tests/storage-temperature-summary.cjs
// Execute the actual summary seam without mounting effects or contacting a host.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const ts = require('typescript');
const root = path.resolve(__dirname, '..');
const read = p => fs.readFileSync(path.join(root, p), 'utf8');
const source = read('components/storage-overview.tsx');
const seam = source.slice(source.indexOf('  const getDiskHealthBreakdown ='), source.indexOf('  const getDiskTypesBreakdown ='));
const thresholds = read('lib/health-thresholds.ts');
const defaults = thresholds.slice(thresholds.indexOf('export const DEFAULT_DISK_TEMP'), thresholds.indexOf('const CACHE_TTL_MS')).replaceAll('export ', '');
const program = read('lib/disk-type.ts').replaceAll('export ', '') + '\n' + defaults + '\nlet storageData; let dtThresholds = DEFAULT_DISK_TEMP;\n' + seam + '\n globalThis.run = (disks, custom) => { storageData = {disks}; dtThresholds = custom || DEFAULT_DISK_TEMP; return getDiskHealthBreakdown(); };';
const context = vm.createContext({});
vm.runInContext(ts.transpileModule(program, {compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText, context);
function check(label, disks, expected, custom) {
  assert.deepEqual(JSON.parse(JSON.stringify(context.run(disks, custom))), expected, label);
}
check('missing reading is unavailable, not normal', [{name:'sda', temperature:0}], {normal:0, warning:0, critical:0, unavailable:1});
console.log('PASS missing reading is unavailable');
for (const temperature of [undefined, null, -1, NaN, Infinity, -Infinity, '30'])
  check(`unavailable ${temperature}`, [{name:'sda', temperature}], {normal:0,warning:0,critical:0,unavailable:1});
for (const temperature of [30, 90])
  check('standby suppresses stale reading', [{name:'sda',temperature,standby:true}], {normal:0,warning:0,critical:0,unavailable:1});
check('empty', [], {normal:0,warning:0,critical:0,unavailable:0});
check('mixed coverage and alerts', [{name:'sda',rotation_rate:7200,temperature:30},{name:'sdb',rotation_rate:7200,temperature:60},{name:'sdc',rotation_rate:7200,temperature:65},{name:'sdd',temperature:0}], {normal:1,warning:1,critical:1,unavailable:1});
for (const [name, rotation_rate, values] of [['sda',7200,[59.9,60,64.9,65]],['sdb',0,[69.9,70,74.9,75]],['nvme0n1',0,[79.9,80,84.9,85]]]) {
  for (const [index, temperature] of values.entries()) {
    const expected = [{normal:1,warning:0,critical:0,unavailable:0},{normal:0,warning:1,critical:0,unavailable:0},{normal:0,warning:1,critical:0,unavailable:0},{normal:0,warning:0,critical:1,unavailable:0}][index];
    check(`${name} exact default ${temperature}`, [{name,rotation_rate,temperature}], expected);
    check(`${name} exact custom ${temperature - 20}`, [{name,rotation_rate,temperature:temperature-20}], expected, {HDD:{warn:40,hot:45},SSD:{warn:50,hot:55},NVMe:{warn:60,hot:65}});
  }
}
console.log('PASS availability, mixed counts, default/custom boundaries');

// Render the actual Physical Disks JSX with the real Card/Badge and provider lookup.
const React = require('react');
const {renderToStaticMarkup} = require('react-dom/server');
function load(file) {
  if (!file.endsWith('.tsx') && !file.endsWith('.ts')) file += fs.existsSync(file+'.tsx') ? '.tsx' : '.ts';
  const module = {exports:{}};
  const code = ts.transpileModule(fs.readFileSync(file,'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React}}).outputText;
  const localRequire = id => id.startsWith('@/') ? load(path.join(root,id.slice(2))) : require(id);
  vm.runInNewContext(code, {module,exports:module.exports,require:localRequire,React});
  return module.exports;
}
const provider = read('lib/i18n/provider.tsx');
const pure = provider.slice(provider.indexOf('function getMessage('),provider.indexOf('export function I18nProvider'));
const translator = provider.slice(provider.indexOf('    (key: string, params?: TranslationParams) => {'),provider.indexOf('\n    [language],')).trim().replace(/,$/,'');
const en = JSON.parse(read('messages/en/common.json'));
function translation(locale) {
  const ctx = vm.createContext({MESSAGE_CATALOG:{en,test:locale},language:'test'});
  vm.runInContext(ts.transpileModule(pure+'\nglobalThis.t = '+translator,{}).outputText,ctx);
  return ctx.t;
}
const start = source.indexOf('        {(() => {',source.indexOf('/* ── Physical Disks'));
const end = source.indexOf('        })()}',start);
assert.ok(start >= 0 && end > start, 'actual JSX seam exists');
const jsx = source.slice(start,end+'        })()}'.length).trim().slice(1,-1);
function render(disks, locale = {}) {
  const t = translation(locale);
  const ctx = {React,...load(path.join(root,'components/ui/card')),...load(path.join(root,'components/ui/badge')),HardDrive:()=>null,
    storageData:{disks,disk_count:disks.length}, diskHealthBreakdown:context.run(disks),diskTypesBreakdown:{nvme:0,ssd:0,hdd:disks.length,usb:0},diskCountLabel:()=> 'disks',t};
  return renderToStaticMarkup(vm.runInNewContext(ts.transpileModule('const result = '+jsx+'; result;', {compilerOptions:{jsx:ts.JsxEmit.React}}).outputText,ctx));
}
const empty = render([]);
assert.ok(empty.includes('No disks'), 'empty array must show neutral No disks');
assert.ok(!empty.includes('text-green-500'), 'empty is not green');
console.log('PASS empty JSX is neutral');
const disk = temperature => ({name:'sda',rotation_rate:7200,temperature});
const fixtures = [
  [[], ['No disks'], 'neutral'],
  [[disk(30)], ['Temperatures normal'], 'green'],
  [[disk(30),disk(35)], ['Temperatures normal'], 'green'],
  [[disk(0)], ['Temperatures unavailable','Unavailable: 1'], 'neutral'],
  // /api/storage can pair cached positive SMART values with current policy flags.
  [[{...disk(30),excluded:true}], ['Temperatures unavailable','Unavailable: 1'], 'neutral'],
  [[{...disk(90),excluded:true}], ['Temperatures unavailable','Unavailable: 1'], 'neutral'],
  [[disk(30),{...disk(90),excluded:true}], ['Temperature data incomplete','Unavailable: 1'], 'neutral'],
  [[disk(60),{...disk(90),excluded:true},{...disk(90),idle:true}], ['High temperatures: 1','Unavailable: 2'], 'yellow'],
  [[disk(65),{...disk(90),excluded:true,idle:true,standby:true}], ['Critical temperatures: 1','Unavailable: 1'], 'red'],
  [[{...disk(30),idle:true}], ['Temperatures unavailable','Unavailable: 1'], 'neutral'],
  [[{...disk(90),idle:true}], ['Temperatures unavailable','Unavailable: 1'], 'neutral'],
  [[disk(30),{...disk(90),idle:true}], ['Temperature data incomplete','Unavailable: 1'], 'neutral'],
  [[disk(0),{...disk(90),standby:true}], ['Temperatures unavailable','Unavailable: 2'], 'neutral'],
  [[disk(30),disk(0)], ['Temperature data incomplete','Unavailable: 1'], 'neutral'],
  [[disk(60),disk(0)], ['High temperatures: 1','Unavailable: 1'], 'yellow'],
  [[disk(65),disk(60),disk(60),disk(0)], ['Critical temperatures: 1','High temperatures: 2','Unavailable: 1'], 'red'],
];
for (const [disks,messages,tone] of fixtures) {
  const html = render(disks);
  for(const message of messages) assert.ok(html.includes(message), `actual JSX: ${message}`);
  assert.equal(html.includes('text-green-500'),tone==='green');
  assert.equal(html.includes('High temperatures:'), messages.some(message => message.startsWith('High temperatures:')), 'suppressed readings cannot add warning alerts');
  assert.equal(html.includes('Critical temperatures:'), messages.some(message => message.startsWith('Critical temperatures:')), 'suppressed readings cannot add critical alerts');
  if(tone !== 'neutral') assert.ok(html.includes(`text-${tone}-500`));
  assert.ok(!html.includes('all healthy'));
}
const synthetic = {storage:{temperatureNoDisks:'SYN empty',temperatureNormal:'SYN normal',temperatureUnavailable:'SYN unavailable',temperatureIncomplete:'SYN incomplete',temperatureHighCount:'SYN high {count}',temperatureCriticalCount:'SYN critical {count}',temperatureUnavailableCount:'SYN missing {count}'}};
for (const [disks] of fixtures) {
  const html = render(disks,synthetic);
  assert.ok(html.includes('SYN'), 'consumer uses localized whole messages');
  assert.ok(!html.includes('Temperatures') && !html.includes('High temperatures') && !html.includes('Critical temperatures') && !html.includes('Unavailable:'));
  assert.ok(!html.includes('{count}'));
}
const mixedTranslated = render([disk(65),disk(60),disk(60),disk(0)],synthetic);
for (const text of ['SYN critical 1','SYN high 2','SYN missing 1']) assert.ok(mixedTranslated.includes(text));
for (const key of Object.keys(synthetic.storage)) {
  assert.equal(translation({})(`storage.${key}`,{count:12}),en.storage[key].replace('{count}','12'), 'unconditional missing-new-key English fallback');
}
console.log('PASS complete thermal JSX, mixed counts, translated messages and missing-key fallback');
for (const disks of [undefined,null,{}]) {
  check('invalid list is safe before error rendering',disks,{normal:0,warning:0,critical:0,unavailable:0});
}
const errorGuard = source.match(/  if \((!storageData \|\| storageData\.error[^\n]*)\) \{/)[1];
for (const storageData of [null,{},{disks:{}},{disks:null},{disks:[],error:'fixture failure'}])
  assert.equal(Boolean(vm.runInNewContext(errorGuard,{storageData})),true,'invalid/failed payload renders error');
assert.equal(Boolean(vm.runInNewContext(errorGuard,{storageData:{disks:[]}})),false,'valid empty is not error');
console.log('PASS invalid payload remains error, not empty');
