// Execute the actual printable-report generator, without mounting the app.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '../../../..');
const source = fs.readFileSync(path.join(root, 'AppImage/components/security.tsx'), 'utf8');
const begin = source.indexOf('  const generatePrintableReport = (report: LynisReport) => {');
const end = source.indexOf('\n  const loadSslStatus =', begin);
assert(begin > 0 && end > begin, 'print consumer not found');
const body = source.slice(begin, end)
  .replace('(report: LynisReport)', '(report)')
  .replace('(raw: unknown): string', '(raw)');
const lang = process.env.LYNIS_FIXTURE_LANG || 'en';
assert(['en','de','es','fr','it','pt','sk','sv'].includes(lang));
const catalog = require(path.join(root, `AppImage/messages/${lang}/common.json`));
const translate = (key, params = {}) => {
  const value = key.split('.').reduce((v, k) => v?.[k], catalog.securityPage);
  assert.equal(typeof value, 'string', `missing ${lang} key ${key}`);
  return value.replace(/\{(\w+)\}/g, (_, k) => String(params[k]));
};
const context = {
  st: translate,
  window: { location: { origin: 'https://offline.invalid' } },
  document: { documentElement: { lang } },
  getLynisScoreState: () => ({rawScore: 80, displayScore: 80, reportComplete: true, hasAdjustment: false}),
  getActionableCount: (total, expected) => Math.max(0, total - expected),
  lynisCountText: (key, count) => translate(`lynis.counts.${key}.${count === 1 ? 'one' : 'many'}`, { count }),
};
const render = vm.runInNewContext(`${body}\ngeneratePrintableReport`, context);
const report = {
  hostname: 'inert', os_name: 'Linux', os_version: '', os_fullname: 'Linux',
  kernel_version: 'test', lynis_version: 'test', datetime_start: '2026-01-01',
  hardening_index: 80, tests_performed: 1,
  warnings: [
    {test_id: 'EXPECTED-W', description: 'expected warning', solution: '', proxmox_expected: true},
    {test_id: 'ACTION-W', description: 'actionable warning', solution: '', proxmox_expected: false},
  ],
  suggestions: [
    {test_id: 'EXPECTED-S', description: 'expected suggestion', solution: '', proxmox_expected: true},
    {test_id: 'ACTION-S', description: 'actionable suggestion', solution: '', proxmox_expected: false},
  ],
  proxmox_expected_warnings: 1, proxmox_expected_suggestions: 1, sections: [],
};
const html = render(report);
if (process.env.LYNIS_FIXTURE_HTML) fs.writeFileSync(process.env.LYNIS_FIXTURE_HTML, html);
for (const id of ['EXPECTED-W', 'ACTION-W', 'EXPECTED-S', 'ACTION-S']) {
  assert(html.includes(id), `missing actual finding ${id}`);
}
assert.match(html, /finding f-pve[\s\S]*?EXPECTED-W[\s\S]*?f-tag-pve/);
assert.match(html, /finding f-pve[\s\S]*?EXPECTED-S[\s\S]*?f-tag-pve/);
for (const key of ['lynis.report.warningsDescription', 'lynis.report.suggestionsDescription']) {
  const description = translate(key);
  assert(!/hidden|nascosti|ocult|caché|skryt|dold|versteckt/i.test(description));
  assert(html.includes(description), `missing rendered description ${key}`);
}
console.log(`print HTML (${lang}): expected/actionable findings shown and badged`);
