// Node 20+: use the same TypeScript compiler harness as the document tests.
// No browser, React rendering, API or host-management imports.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const app = path.resolve(__dirname, '../AppImage');
const appRequire = createRequire(path.join(app, 'package.json'));
const ts = appRequire('typescript');
const read = rel => fs.readFileSync(path.join(app, rel), 'utf8');
const cache = new Map();
function load(file) {
  file = path.resolve(file);
  if (cache.has(file)) return cache.get(file).exports;
  const mod = { exports: {} };
  cache.set(file, mod);
  const compiled = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  // Evaluate only local repository modules compiled above, never external input.
  new Function('require', 'module', 'exports', compiled)(name => {
    if (!name.startsWith('.')) return appRequire(name);
    return load(path.resolve(path.dirname(file), name + '.ts'));
  }, mod, mod.exports);
  return mod.exports;
}
const messages = JSON.parse(read('messages/en/common.json'));
const used = [];
const t = (key, values = {}) => {
  used.push(key);
  let text = key.split('.').reduce((o, k) => o?.[k], messages);
  assert.equal(typeof text, 'string', key);
  for (const [k, v] of Object.entries(values)) text = text.replaceAll(`{${k}}`, v);
  return text;
};
const contract = 'The assessment inspects host settings and health. It can write reports and logs; boot status checks can temporarily mount EFI system partitions.';
global.window = { location: { origin: 'http://localhost' } };
const { buildAuditDocument } = load(path.join(app, 'lib/audit-document.ts'));
const html = buildAuditDocument({
  t, locale: 'en', profile: 'full', run: null, findings: [],
  inventory: { sections: {}, unavailable: {} },
});
assert.ok(used.includes('audit.presentation.readOnlyScope'), 'document did not look up its scope contract');
assert.ok(html.includes(contract), 'real document omitted the safety contract');

// Check the JSX-to-catalog binding structurally, not quote style, line breaks,
// class names, or paragraph formatting. This is not a React visibility test.
const report = ts.createSourceFile('audit-report.tsx', read('components/audit-report.tsx'),
  ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const noticeKeys = [];
function visit(node) {
  if (ts.isJsxExpression(node) && node.expression && ts.isCallExpression(node.expression)) {
    const call = node.expression;
    const key = call.arguments[0];
    if (ts.isIdentifier(call.expression) && call.expression.text === 't' &&
        key && ts.isStringLiteral(key) && key.text === 'audit.readOnlyNotice') {
      noticeKeys.push(key.text);
    }
  }
  ts.forEachChild(node, visit);
}
visit(report);
assert.ok(noticeKeys.length > 0, 'assessment notice consumer not found');
for (const key of noticeKeys) assert.equal(t(key), contract);
assert.equal(t('audit.document.scopeReadOnly'), contract);
console.log('PASS: real full document safety contract, JSX notice binding, legacy scope agreement');
