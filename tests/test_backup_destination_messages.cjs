// Offline actual JSX/provider seams; no component/backend imports or effects.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const { translator, catalogs } = require('./test_backup_archives_empty.cjs');
const app = path.resolve(__dirname, '../AppImage');
const ts = createRequire(path.join(app, 'package.json'))('typescript');
const source = ts.createSourceFile('host-backup.tsx', fs.readFileSync(path.join(app, 'components/host-backup.tsx'), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const printer = ts.createPrinter();
const React = { createElement: (tag, props, ...children) => children.flat(Infinity).filter(x => x != null && x !== false).join('') };
function find(predicate) {
  const found = [];
  function visit(node) { if (predicate(node)) found.push(node); ts.forEachChild(node, visit); }
  visit(source);
  assert.equal(found.length, 1, 'unique actual message seam');
  return found[0];
}
function render(node, locale, backups = 1, messages = catalogs) {
  const code = ts.transpileModule(`const result = ${printer.printNode(ts.EmitHint.Expression, node, source)};`, {
    compilerOptions: { target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.React },
  }).outputText;
  // Only trusted checked-out AST enters executable code, never catalog values.
  return new Function('React', 't', 'backups', code + '\nreturn result;')(React, translator(locale, messages), backups);
}
const kept = find(node => ts.isBinaryExpression(node) && node.left.getText(source) === 'backups > 0');
const keptMessage = 'Existing backup archives are not deleted.';
for (const count of [1, 3]) assert.equal(render(kept, 'it', count), keptMessage, 'Italian catalog uses English fallback');
assert.equal(render(kept, 'en', 0), false);
for (const locale of Object.keys(catalogs)) {
  if (catalogs[locale].backup?.destinations?.backupsKeptMessage !== undefined && locale !== 'en') continue;
  for (const count of [1, 3]) assert.equal(render(kept, locale, count), keptMessage, `${locale}: kept whole-message fallback`);
}
console.log('PASS: destination removal JSX guard 0/1/N and whole-message locale fallback');
// Select the actual help paragraph, keeping its literal paths/JSX whitespace.
const help = find(node => ts.isJsxElement(node) && node.openingElement.tagName.getText(source) === 'p' &&
  /backup\.destinations\.localAttachHelp(?:Before|Message)/.test(node.getText(source)));
const helpMessage = 'Mount USB drives first. Leave blank to use the PVE storage path + /dump (fallback: /var/lib/vz/dump).';
assert.equal(render(help, 'it'), helpMessage, 'Italian catalog uses English fallback');
for (const locale of Object.keys(catalogs)) {
  if (catalogs[locale].backup?.destinations?.localAttachHelpMessage !== undefined && locale !== 'en') continue;
  assert.equal(render(help, locale), helpMessage, `${locale}: local attach help fallback`);
}
// Missing-key fallback must remain covered after shipped catalogs are complete.
const missing = { ...catalogs, missing: {} };
assert.equal(render(kept, 'missing', 1, missing), keptMessage);
assert.equal(render(help, 'missing', 1, missing), helpMessage);
// Synthetic locale proves complete messages are translatable, not hardcoded.
const synthetic = { ...catalogs, fixture: { backup: { destinations: {
  backupsKeptMessage: 'Fixture kept.', localAttachHelpMessage: 'Fixture help.',
} } } };
assert.equal(render(kept, 'fixture', 1, synthetic), 'Fixture kept.');
assert.equal(render(help, 'fixture', 1, synthetic), 'Fixture help.');
assert.equal(catalogs.en.backup.destinations.kept, 'kept');
assert.equal(catalogs.en.backup.destinations.localAttachHelpMiddle, 'USB drives');
console.log('PASS: local attach JSX whole-message fallback and literal paths');
