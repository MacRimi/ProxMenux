// Render the real summary JSX with fixture state, without API calls or effects.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const app = path.resolve(__dirname, '../AppImage');
const appRequire = createRequire(path.join(app, 'package.json'));
const React = appRequire('react');
const { renderToStaticMarkup } = appRequire('react-dom/server');
const ts = appRequire('typescript');
const {load} = require('./test_audit_presentation.cjs');
const source = fs.readFileSync(path.join(app, 'components/audit-report.tsx'), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2020,
}}).outputText;
function render(locale, findings, status = 'partial') {
  const messages = JSON.parse(fs.readFileSync(path.join(app, 'messages', locale, 'common.json')));
  const t = (key, values = {}) => {
    let text = key.split('.').reduce((o, k) => o?.[k], messages) ?? key;
    for (const [key, value] of Object.entries(values)) text = text.replaceAll(`{${key}}`, value);
    return text;
  };
  const summary = findings.reduce((o, f) => ({...o, [f.classification]: (o[f.classification] || 0) + 1}), {});
  // Positional: one entry per useState in audit-report.tsx, in order.
  const states = ['assessment', false, {status, finished_at: Date.now()/1000}, findings, summary,
    'all', new Set(findings.map(f=>f.check_id)), null, false, null, '', '', false,
    {completed: 0, total: 36},'full',[],false];
  let index = 0;
  const ui = tag => ({children, ...props}) => React.createElement(tag, props, children);
  const imports = {
    react: {...React, useState: () => [states[index++], () => {}], useEffect: () => {},
      useMemo: cb => cb(), useCallback: cb => cb},
    './ui/card': {Card: ui('section'), CardContent: ui('div'), CardHeader: ui('header'), CardTitle: ui('h2')},
    './ui/button': {Button: ui('button')}, './ui/badge': {Badge: ui('span')},
    './ui/dialog': {Dialog: () => null},
    '../lib/api-config': {fetchApi: () => {throw Error('unexpected API call')}},
    '../lib/i18n/provider': {useT: () => t, useI18n:()=>({language:locale})},
    './audit-inventory': {AuditInventory:()=>null},
    './audit-policy': {AuditPolicy:()=>null},
    './audit-changes': {AuditChanges:()=>null},
    './audit-comparison': {AuditComparison:()=>null},
    './ui/label': {Label: ui('label')},
    './ui/select': {Select: ui('div'), SelectContent: ui('div'), SelectItem: ui('option'),
                    SelectTrigger: ui('div'), SelectValue: ui('span')},
    '../lib/audit-document': {},
    './audit-evidence': load(path.join(app,'components/audit-evidence.tsx')),
    './audit-finding-data': load(path.join(app,'components/audit-finding-data.tsx')),
    '../lib/audit-presentation': load(path.join(app,'lib/audit-presentation.ts')),
  };
  const module = {exports: {}};
  new Function('require', 'module', 'exports', compiled)(name => imports[name] || appRequire(name), module, module.exports);
  return {html: renderToStaticMarkup(React.createElement(module.exports.AuditReport)), t};
}
// renderToStaticMarkup escapes text, so a translation containing an
// apostrophe never matches its raw form. Compare against what React
// actually writes.
const esc = (text) => text.replace(/&/g, '&amp;').replace(/</g, '&lt;')
  .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#x27;');
const finding = (check_id, state, severity, incomplete = false) => ({
  check_id, state, severity, classification: {fail:'critical',warn:'warning',unknown:'unverified'}[state] || state,
  incomplete, area: check_id.split('.')[0], affected: [], evidence:null, summary_key: null,
});
for (const locale of ['en', 'es', 'de', 'fr', 'it', 'pt', 'sk', 'sv']) {
  const fixtures = [finding('backup.guest_coverage', 'fail', 'CRITICAL'),
    finding('system.pending_reboot', 'warn', 'WARNING'),
    finding('hardware.disk_service_life', 'unknown', 'INFO'),
    finding('security.lynis_warnings', 'unknown', 'WARNING')];
  const {html, t} = render(locale, fixtures);
  assert(html.includes(`aria-label="${t('audit.results')}"`));
  assert(html.includes(esc(t('audit.unverifiedChecks', {checks: [
    t('audit.checks.hardware.disk_service_life.title'), t('audit.checks.security.lynis_warnings.title'),
  ].join(' · ')}))));
  assert.equal((html.match(/h-6 gap-1.5 whitespace-nowrap px-2.5 py-0 text-xs/g) || []).length, 3);
  assert(html.includes('flex max-w-full flex-wrap items-center gap-2'));
  assert(!render(locale, [], 'complete').html.includes('role="alert"'));
  assert(!render(locale, []).html.includes(`aria-label="${t('audit.severityGroup')}"`));
  const partial = render(locale, [finding('backup.guest_coverage', 'warn', 'CRITICAL', true)]);
  assert(partial.html.includes(esc(t('audit.unverifiedChecks',
    {checks: t('audit.checks.backup.guest_coverage.title')}))));
}
console.log('Audit summary: eight locales, uniform counters, labelled groups and partial/complete states passed.');
