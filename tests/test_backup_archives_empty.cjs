// Offline JSX seam, following the TypeScript compiler harness in adjacent tests.
// No component imports, React effects, API calls or host-management execution.
// Run from the repository root: node tests/test_backup_archives_empty.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const app = path.resolve(__dirname, '../AppImage');
const ts = createRequire(path.join(app, 'package.json'))('typescript');
const read = file => fs.readFileSync(path.join(app, file), 'utf8');
const parse = file => ts.createSourceFile(file, read(file), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const compile = text => ts.transpileModule(text, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.React },
}).outputText;
const printer = ts.createPrinter();
const provider = parse('lib/i18n/provider.tsx');
const pure = provider.statements.filter(node => ts.isFunctionDeclaration(node) &&
  ['getMessage', 'interpolate'].includes(node.name?.text));
assert.equal(pure.length, 2);
let lookup;
function visitLookup(node) {
  if (ts.isVariableDeclaration(node) && node.name.getText(provider) === 't' &&
      node.initializer && ts.isCallExpression(node.initializer) &&
      node.initializer.expression.getText(provider) === 'useCallback') lookup = node.initializer.arguments[0];
  ts.forEachChild(node, visitLookup);
}
visitLookup(provider);
assert.ok(lookup, 'real provider lookup callback');
const lookupCode = pure.map(node => printer.printNode(ts.EmitHint.Unspecified, node, provider)).join('\n') +
  '\nconst t = ' + printer.printNode(ts.EmitHint.Expression, lookup, provider) + ';';
const catalogs = Object.fromEntries(fs.readdirSync(path.join(app, 'messages')).filter(locale =>
  fs.existsSync(path.join(app, 'messages', locale, 'common.json'))).map(locale =>
  [locale, JSON.parse(read(`messages/${locale}/common.json`))]));
// Compile only trusted, checked-out source; no catalog/input strings enter code.
const translator = (language, messages = catalogs) =>
  new Function('MESSAGE_CATALOG', 'language', compile(lookupCode) + '\nreturn t;')(messages, language);

const source = parse('components/host-backup.tsx');
let branch;
function visitBranch(node) {
  if (ts.isConditionalExpression(node) && node.condition.getText(source) === 'archivesErr && remoteArchivesErr') branch = node;
  ts.forEachChild(node, visitBranch);
}
visitBranch(source);
assert.ok(branch, 'real archives loading/error/empty decision');
// Keep the actual guards and JSX messages. Only replace the nonempty archive
// list with a sentinel: rendering its controls is outside this message test.
const transformed = ts.transform(branch, [context => root => {
  const visit = node => {
    if (ts.isConditionalExpression(node) && node.condition.getText(source) === 'unifiedArchives.length === 0') {
      return ts.factory.updateConditionalExpression(node, node.condition, node.questionToken,
        node.whenTrue, node.colonToken, ts.factory.createStringLiteral('NONEMPTY_ARCHIVES'));
    }
    return ts.visitEachChild(node, visit, context);
  };
  return ts.visitNode(root, visit);
}]);
const expression = printer.printNode(ts.EmitHint.Expression, transformed.transformed[0], source);
transformed.dispose();
const render = new Function('React', 'Loader2', 't', 'archivesErr', 'remoteArchivesErr',
  'archivesResp', 'remoteArchivesResp', 'unifiedArchives', compile(`const result = ${expression};`) + '\nreturn result;');
// Text-only JSX sink: TypeScript performs the real JSX whitespace conversion.
const React = { createElement: (tag, props, ...children) => children.flat(Infinity).filter(x => x != null && x !== false).join('') };
const text = (locale = 'en', overrides = {}, messages = catalogs) => {
  const state = { archivesErr: null, remoteArchivesErr: null, archivesResp: { archives: [] },
    remoteArchivesResp: { snapshots: [] }, unifiedArchives: [], ...overrides };
  return render(React, 'spinner', translator(locale, messages), state.archivesErr, state.remoteArchivesErr,
    state.archivesResp, state.remoteArchivesResp, state.unifiedArchives);
};

assert.equal(text(), 'No backup archives found.');
assert.equal(text('it'), 'No backup archives found.', 'Italian catalog uses English fallback');
// Keep fallback coverage even after all shipped locales gain the new key.
assert.equal(text('missing', {}, { ...catalogs, missing: {} }), 'No backup archives found.');
for (const locale of Object.keys(catalogs)) {
  // Existing catalogs intentionally have no new key; actual provider falls back.
  if (catalogs[locale].backup?.archives?.emptyMessage === undefined) {
    assert.equal(text(locale), 'No backup archives found.', `${locale}: missing-key fallback`);
  }
}
for (const count of [1, 3]) assert.equal(text('en', { unifiedArchives: Array(count).fill({}) }), 'NONEMPTY_ARCHIVES');
assert.equal(text('en', { archivesResp: undefined, remoteArchivesResp: undefined }), translator('en')('backup.common.loading'));
assert.equal(text('en', { archivesErr: true, remoteArchivesErr: true }), translator('en')('backup.archives.loadFailed'));
// Preserve existing partial-source semantics; no claim that every source was queried.
assert.equal(text('en', { archivesErr: true, archivesResp: undefined }), 'No backup archives found.');
assert.equal(text('en', { remoteArchivesErr: true, remoteArchivesResp: undefined }), 'No backup archives found.');
assert.equal(translator('en')('backup.manual.run'), 'Run');
assert.ok(read('components/host-backup.tsx').includes('{t("backup.manual.run")}'), 'manual action remains');
console.log('PASS: actual archives JSX seam, zero/one/multiple, loading/errors, locale fallback, Run unchanged');
// Export only test seams for separate, unapplied linguistic proposal checks.
module.exports = { text, translator, catalogs };
