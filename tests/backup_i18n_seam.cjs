// Test-only provider seam shared by independent backup message programs.
// Compile only checked-out provider source; catalog values are never executable code.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const app = path.resolve(__dirname, '../AppImage');
const ts = createRequire(path.join(app, 'package.json'))('typescript');
const read = file => fs.readFileSync(path.join(app, file), 'utf8');
const compile = text => ts.transpileModule(text, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.React },
}).outputText;
const printer = ts.createPrinter();
const provider = ts.createSourceFile('provider.tsx', read('lib/i18n/provider.tsx'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
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
const registered = provider.statements.flatMap(statement => ts.isVariableStatement(statement) ?
  statement.declarationList.declarations.filter(declaration => declaration.name.getText(provider) === 'MESSAGE_CATALOG') : []);
assert.equal(registered.length, 1, 'real provider catalog declaration');
assert.deepEqual(registered[0].initializer.properties.map(property => property.name.getText(provider)).sort(),
  Object.keys(catalogs).sort(), 'test each runtime-registered shipped locale');
assert.ok(catalogs.en, 'English fallback catalog exists');
const translator = (language, messages = catalogs) =>
  new Function('MESSAGE_CATALOG', 'language', compile(lookupCode) + '\nreturn t;')(messages, language);
module.exports = { app, ts, read, compile, printer, catalogs, translator };
