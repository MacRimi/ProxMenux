// Offline JSX seam, following the TypeScript compiler harness in adjacent tests.
// No component imports, React effects, API calls or host-management execution.
// Run from the repository root: node tests/test_backup_archives_empty.cjs
const assert = require('node:assert/strict');
const { ts, read, compile, printer, catalogs, translator } = require('./backup_i18n_seam.cjs');
const parse = file => ts.createSourceFile(file, read(file), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);

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

const emptyMessage = 'No backup archives found.';
assert.equal(catalogs.en.backup.archives.emptyMessage, emptyMessage);
assert.equal(text(), emptyMessage);
// Missing-key fallback is unconditional: it must survive later catalog generation.
assert.equal(text('missing', {}, { ...catalogs, missing: {} }), emptyMessage);
const synthetic = { ...catalogs, fixture: { backup: { archives: { emptyMessage: 'Fixture: no archives.' } } } };
assert.equal(text('fixture', {}, synthetic), 'Fixture: no archives.');
const locales = Object.keys(catalogs);
assert.ok(locales.length > 1, 'shipped multilingual catalogs discovered');
for (const locale of locales) {
  const shipped = catalogs[locale].backup?.archives?.emptyMessage;
  assert.equal(text(locale), shipped ?? emptyMessage, `${locale}: actual shipped locale or English fallback`);
}
assert.ok(locales.some(locale => locale !== 'en' &&
  typeof catalogs[locale].backup?.archives?.emptyMessage === 'string' &&
  catalogs[locale].backup.archives.emptyMessage !== emptyMessage), 'localized shipped archive message exercised');
for (const count of [1, 3]) assert.equal(text('en', { unifiedArchives: Array(count).fill({}) }), 'NONEMPTY_ARCHIVES');
assert.equal(text('en', { archivesResp: undefined, remoteArchivesResp: undefined }), translator('en')('backup.common.loading'));
assert.equal(text('en', { archivesErr: true, remoteArchivesErr: true }), translator('en')('backup.archives.loadFailed'));
// Preserve existing partial-source semantics; no claim that every source was queried.
assert.equal(text('en', { archivesErr: true, archivesResp: undefined }), 'No backup archives found.');
assert.equal(text('en', { remoteArchivesErr: true, remoteArchivesResp: undefined }), 'No backup archives found.');
assert.equal(translator('en')('backup.manual.run'), 'Run');
assert.ok(read('components/host-backup.tsx').includes('{t("backup.manual.run")}'), 'manual action remains');
console.log('PASS: actual archives JSX seam, zero/one/multiple, loading/errors, shipped locales and synthetic fallback/translation, Run unchanged');
