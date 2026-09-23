// Offline actual JSX/provider seams; no component/backend imports or effects.
const assert = require('node:assert/strict');
const { ts, read, printer, translator, catalogs } = require('./backup_i18n_seam.cjs');
const source = ts.createSourceFile('host-backup.tsx', read('components/host-backup.tsx'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);

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
assert.equal(catalogs.en.backup.destinations.backupsKeptMessage, keptMessage);
assert.equal(render(kept, 'en', 1), keptMessage);
assert.equal(render(kept, 'en', 3), keptMessage);
assert.equal(render(kept, 'en', 0), false);
// A missing locale key must use English regardless of shipped catalog completeness.
const missing = { ...catalogs, missing: {} };
for (const count of [1, 3]) assert.equal(render(kept, 'missing', count, missing), keptMessage);
console.log('PASS: destination removal JSX guard 0/1/N and missing-key fallback');
// Select the actual help paragraph, keeping its literal paths/JSX whitespace.
const help = find(node => ts.isJsxElement(node) && node.openingElement.tagName.getText(source) === 'p' &&
  /backup\.destinations\.localAttachHelp(?:Before|Message)/.test(node.getText(source)));
const helpMessage = 'Mount USB drives first. Leave blank to use the PVE storage path + /dump (fallback: /var/lib/vz/dump).';
assert.equal(catalogs.en.backup.destinations.localAttachHelpMessage, helpMessage);
assert.equal(render(help, 'en'), helpMessage);
assert.equal(render(help, 'missing', 1, missing), helpMessage);
// Synthetic whole messages prove both JSX consumers use the provider rather than hardcoded English.
const synthetic = { ...catalogs, fixture: { backup: { destinations: {
  backupsKeptMessage: 'Fixture kept.', localAttachHelpMessage: 'Fixture help.',
} } } };
assert.equal(render(kept, 'fixture', 1, synthetic), 'Fixture kept.');
assert.equal(render(kept, 'fixture', 3, synthetic), 'Fixture kept.');
assert.equal(render(help, 'fixture', 1, synthetic), 'Fixture help.');
const locales = Object.keys(catalogs);
assert.ok(locales.length > 1, 'shipped multilingual catalogs discovered');
for (const locale of locales) {
  const destinations = catalogs[locale].backup?.destinations;
  for (const count of [1, 3]) {
    assert.equal(render(kept, locale, count), destinations?.backupsKeptMessage ?? keptMessage,
      `${locale}: actual kept message or English fallback`);
  }
  assert.equal(render(help, locale), destinations?.localAttachHelpMessage ?? helpMessage,
    `${locale}: actual local attach help or English fallback`);
}
for (const [key, english] of [['backupsKeptMessage', keptMessage], ['localAttachHelpMessage', helpMessage]]) {
  assert.ok(locales.some(locale => locale !== 'en' &&
    typeof catalogs[locale].backup?.destinations?.[key] === 'string' &&
    catalogs[locale].backup.destinations[key] !== english),
    `${key}: localized shipped message exercised`);
}
assert.equal(catalogs.en.backup.destinations.kept, 'kept');
assert.equal(catalogs.en.backup.destinations.localAttachHelpMiddle, 'USB drives');
console.log('PASS: destination whole-message JSX, shipped locales, synthetic translation/fallback and literal paths');
