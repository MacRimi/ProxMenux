// Offline actual JSX/provider seams. No component imports or effects.
// NODE_PATH may point to an isolated TypeScript installation.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const root = path.resolve(__dirname, '..');
const read = p => fs.readFileSync(path.join(root, p), 'utf8');
const parse = p => ts.createSourceFile(p, read(p), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const print = ts.createPrinter();
const emit = (node, source) => print.printNode(ts.EmitHint.Unspecified, node, source);
const compile = code => ts.transpileModule(code, {compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.React,
}}).outputText;
const provider = parse('AppImage/lib/i18n/provider.tsx');
const helpers = provider.statements.filter(n => ts.isFunctionDeclaration(n) && ['getMessage', 'interpolate'].includes(n.name?.text));
assert.equal(helpers.length, 2);
let lookup;
function walk(node, fn) { fn(node); ts.forEachChild(node, n => walk(n, fn)); }
walk(provider, n => {
  if (ts.isVariableDeclaration(n) && n.name.getText(provider) === 't' &&
      n.initializer && ts.isCallExpression(n.initializer) && n.initializer.expression.getText(provider) === 'useCallback') lookup = n.initializer.arguments[0];
});
assert.ok(lookup);
const catalogs = Object.fromEntries(fs.readdirSync(path.join(root, 'AppImage/messages')).filter(locale => fs.existsSync(path.join(root, 'AppImage/messages', locale, 'common.json'))).map(locale =>
  [locale, JSON.parse(read(`AppImage/messages/${locale}/common.json`))]));
// Only trusted checked-out source enters Function bodies; fixture/catalog values are arguments.
const translator = (language, messages = catalogs) => new Function('MESSAGE_CATALOG', 'language',
  compile(helpers.map(n => emit(n, provider)).join('\n') + '\nconst t = ' + emit(lookup, provider)) + '\nreturn t;')(messages, language);
const source = parse('AppImage/components/storage-overview.tsx');
let badge;
walk(source, n => {
  if (ts.isJsxExpression(n) && n.expression && ts.isBinaryExpression(n.expression) &&
      n.expression.left.getText(source) === 'smartJsonData?.has_data && !wi') badge = n.expression;
});
assert.ok(badge, 'actual availability guard and badge');
const render = new Function('React', 'Badge', 't', 'smartJsonData', 'wi',
  compile('const result = ' + emit(badge, source)) + '\nreturn result;');
const React = {createElement: (tag, props, ...children) => children.join('')};
const text = (locale, data = {has_data: true}, wi = false, messages = catalogs) =>
  render(React, 'badge', translator(locale, messages), data, wi);
assert.equal(text('en'), 'Saved SMART data');
assert.equal(text('missing', undefined, false, {...catalogs, missing: {}}), 'Saved SMART data');
for (const locale of Object.keys(catalogs)) {
  if (catalogs[locale].storage?.savedSmartData === undefined) assert.equal(text(locale), 'Saved SMART data');
}
assert.equal(text('en', {has_data: false}), false);
assert.equal(text('en', {has_data: true}, true), false);
assert.equal(text('en', null), undefined);
assert.equal(text('synthetic', undefined, false, {...catalogs, synthetic: {storage: {savedSmartData: 'SAVED_DATA_TRANSLATED'}}}), 'SAVED_DATA_TRANSLATED');
assert.equal(catalogs.en.storage.realTest, 'Real Test', 'legacy label preserved');
console.log('PASS: saved-data badge guards and actual provider fallback/translation');

// Execute the actual printable-report function with inert browser sinks, not component effects.
const report = source.statements.find(n => ts.isFunctionDeclaration(n) && n.name?.text === 'openSmartReport');
assert.ok(report);
let reportHtml;
const openReport = new Function('window', 'Blob', 'URL', 'setTimeout', 'getDiskTempThresholdsSync', 'getNvmeSmartAttributeKey',
  compile('const APP_VERSION = "fixture";\n' + emit(report, source)) + '\nreturn openSmartReport;')(
  {location: {origin: 'http://fixture.invalid'}, open() {}},
  class { constructor(parts) { reportHtml = parts.join(''); } },
  {createObjectURL() { return 'blob:fixture'; }, revokeObjectURL() {}}, () => {},
  () => ({warning: 55, critical: 65}), () => undefined);
const expectedReport = {
  passedAssessment: 'The supplied SMART status is PASSED. This status alone does not establish that every attribute is within range or that the disk is free of faults. Power-on time shown: {uptime}. Temperature shown: {temperature}. {sectors}',
  noReallocatedSectorsReported: 'The supplied reallocated-sector value is zero or unavailable; this does not establish that there are no bad sectors.',
  passedMeaningTitle: 'What does a PASSED status mean?',
  passedMeaning: 'PASSED is the overall status supplied to this report, not proof of a completed self-test or a guarantee against failure. Review the attributes, error logs and self-test results, and keep current backups.',
  recommendations: {
    passedTitle: 'Review the reported results',
    passedText: 'A PASSED status can coexist with warnings or recorded errors. Review the report details, continue regular monitoring and keep current backups.',
  },
};
function leaves(value, prefix = '') {
  return Object.entries(value).flatMap(([k, v]) => typeof v === 'string' ? [[prefix + k, v]] : leaves(v, prefix + k + '.'));
}
function renderReport(diskOverrides = {}, status = 'passed', locale = 'en', messages = catalogs, smartData = {}) {
  openReport({name: 'sda', model: 'Fixture disk', size: 100, rotation_rate: 7200, temperature: 35, power_on_hours: 24, ...diskOverrides},
    {smart_status: status, smart_data: smartData}, [], [], undefined, undefined, false, undefined, translator(locale, messages));
  return reportHtml;
}
const html = renderReport();
for (const [key, value] of leaves(expectedReport)) {
  const expected = value.replace('{uptime}', '1d (24h)').replace('{temperature}', '35°C').replace('{sectors}', expectedReport.noReallocatedSectorsReported);
  assert.ok(html.includes(expected), `report consumer: ${key}`);
}
assert.ok(html.includes('The supplied SMART status is PASSED.'));
assert.ok(!html.includes('All SMART attributes are within'));
assert.ok(!html.includes('Your disk is healthy!'));
for (const sectors of [undefined, 0]) assert.ok(renderReport({reallocated_sectors: sectors}).includes(expectedReport.noReallocatedSectorsReported));
assert.ok(!renderReport({reallocated_sectors: 3}).includes(expectedReport.noReallocatedSectorsReported));
for (const status of ['failed', 'unknown', 'warning']) assert.ok(!renderReport({}, status).includes(expectedReport.passedMeaning));
for (const locale of ['synthetic', ...Object.keys(catalogs).filter(l => l !== 'en')]) {
  const messages = {...catalogs, synthetic: {}};
  const rendered = renderReport({}, 'passed', locale, messages);
  if (locale === 'synthetic') assert.ok(rendered.includes(expectedReport.passedAssessment.replace('{uptime}', '1d (24h)').replace('{temperature}', '35°C').replace('{sectors}', expectedReport.noReallocatedSectorsReported)));
  for (const [key, value] of leaves(expectedReport)) {
    const localValue = ('storage.smartReport.' + key).split('.').reduce((v, k) => v?.[k], messages[locale]);
    if (localValue === undefined && !value.includes('{')) assert.ok(rendered.includes(value), `${locale}: ${key}`);
  }
}
for (const temperature of [undefined, 0]) assert.ok(renderReport({temperature}).includes('Temperature shown: N/A.'));
assert.ok(renderReport({name: 'nvme0n1'}, 'passed').includes(expectedReport.passedMeaning));
const translated = Object.fromEntries(leaves(expectedReport).filter(([k]) => !k.includes('.')).map(([k]) => [k, `TRANSLATED_${k}`]));
translated.passedAssessment += ' {uptime} {temperature} {sectors}';
translated.recommendations = {passedTitle: 'TRANSLATED_REC_TITLE', passedText: 'TRANSLATED_REC_TEXT'};
const localized = renderReport({}, 'passed', 'synthetic', {...catalogs, synthetic: {storage: {smartReport: translated}}});
for (const [, value] of leaves(translated)) assert.ok(localized.includes(value.split(' {')[0]), value);
assert.ok(renderReport({name: 'nvme0n1'}, 'passed', 'en', catalogs, {nvme_raw: {critical_warning: 0, media_errors: 7}}).includes(expectedReport.passedMeaning));
if (process.env.STORAGE_REPORT_HTML) fs.writeFileSync(process.env.STORAGE_REPORT_HTML, renderReport());
console.log('PASS: actual printable report, passed/failed/unknown/warning, missing/zero/nonzero sectors, NVMe errors and provider fallback');
