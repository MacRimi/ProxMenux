// Run: node tests/test_borg_ssh_guidance.cjs [account|setup]
// Prerequisites: Node 22.14+, installed AppImage dependencies (React + TypeScript).
// Renders the actual SSH JSX branch and executes the actual provider lookup callback.
// No host-management imports, network, backend, or real SSH key generation.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const app = path.resolve(__dirname, '../AppImage');
const req = createRequire(path.join(app, 'package.json'));
const ts = req('typescript');
const React = req('react');
const { renderToStaticMarkup } = req('react-dom/server');
const read = p => fs.readFileSync(path.join(app, p), 'utf8');
const parse = (s, name = 'fixture.tsx') => ts.createSourceFile(name, s, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
function nodes(tree, predicate) {
  const result = [];
  function visit(n) { if (predicate(n)) result.push(n); ts.forEachChild(n, visit); }
  visit(tree); return result;
}
function evaluate(source, bindings) {
  const js = ts.transpileModule(source, { compilerOptions: {
    jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020,
  }}).outputText;
  const module = { exports: {} };
  // Only trusted checked-out source is compiled; fixture values are bindings, never code.
  new Function('require', 'module', 'exports', ...Object.keys(bindings), js)(req, module, module.exports, ...Object.values(bindings));
  return module.exports;
}
const source = read('components/host-backup.tsx');
const tree = parse(source);
const dialog = nodes(tree, n => ts.isFunctionDeclaration(n) && n.name?.text === 'AddDestinationDialog')[0];
assert.ok(dialog, 'actual destination component exists');
const unwrap = n => ts.isParenthesizedExpression(n) ? unwrap(n.expression) : n;
const branch = nodes(dialog, n => ts.isConditionalExpression(n) && n.condition.getText(tree) === 'borgMode === "local"' && ts.isJsxFragment(unwrap(n.whenFalse)));
assert.equal(branch.length, 1, 'unique actual Borg SSH JSX branch');
const providerSource = read('lib/i18n/provider.tsx');
const providerTree = parse(providerSource);
const helpers = nodes(providerTree, n => ts.isFunctionDeclaration(n) && ['getMessage', 'interpolate'].includes(n.name?.text)).map(n => n.getText(providerTree)).join('\n');
const callback = nodes(providerTree, n => ts.isVariableDeclaration(n) && n.name.getText(providerTree) === 't')[0].initializer.arguments[0].getText(providerTree);
const en = JSON.parse(read('messages/en/common.json'));
function translate(locale) {
  return evaluate(`${helpers}\nmodule.exports = ${callback}`, { MESSAGE_CATALOG: { en, fixture: locale }, language: 'fixture' });
}
const noop = () => {};
const component = tag => ({ children, ...props }) => React.createElement(tag, props, children);
const literalLine = 'command="borg serve --restrict-to-path /backup/repo",restrict ssh-ed25519 AAAA-fixture-only <not-html>\n';
let renderCount = 0;
function render(locale, { user = 'borg', generated = false, loading = false, keyPath = '/root/.ssh/proxmenux_borg' } = {}) {
  renderCount++;
  const bindings = {
    t: translate(locale), borgSshUser: user, borgSshHost: 'backup.example.invalid', borgSshPort: '22',
    borgSshRemotePath: '/backup/repo', borgSshKeyPath: keyPath,
    generatedKey: generated ? { authorized_keys_line: literalLine, public_key: 'ssh-ed25519 AAAA-fixture-only' } : null,
    generatingKey: loading, generateBorgKey: noop,
    setBorgSshUser: noop, setBorgSshHost: noop, setBorgSshPort: noop, setBorgSshRemotePath: noop, setBorgSshKeyPath: noop,
    Label: component('label'), Input: component('input'), Button: ({ size, variant, ...p }) => React.createElement('button', p),
    Loader2: component('svg'), Plus: component('svg'),
  };
  const Fixture = evaluate(`module.exports = function Fixture() { return (${branch[0].whenFalse.getText(tree)}) }`, bindings);
  return renderToStaticMarkup(React.createElement(Fixture));
}
const escape = value => value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#x27;');
const account = 'Remote account used to access the Borg repository, for example borg.';
const keyHelp = "Private key path on this host. Use Prepare key, then review and add the displayed public-key line to the remote user's ~/.ssh/authorized_keys.";
const setupHelp = 'Creates a key at the specified local path if none exists; otherwise reads its public key. No key is installed on the remote host.';
// Accept future shipped translations, while the always-empty synthetic locale
// below continues to assert the independently specified English contract.
const localText = (locale, group, key, fallback) => typeof locale.backup?.[group]?.[key] === 'string' ? locale.backup[group][key] : fallback;
const keys = ['sshUserHelpMessage', 'sshKeyHelpMessage', 'sshKeySetupTitle', 'sshKeySetupHelp', 'sshAuthorizedKeyHelp'];

const locales = fs.readdirSync(path.join(app, 'messages')).filter(l => fs.existsSync(path.join(app, 'messages', l, 'common.json')));
// The empty synthetic locale is unconditional: fallback stays covered after upstream translations arrive.
for (const locale of [{}, ...locales.map(l => JSON.parse(read(`messages/${l}/common.json`)))]) {
  for (const user of ['borg', 'root', 'archive-user', '<img src=x onerror=alert(1)>']) {
    const html = render(locale, { user });
    assert.ok(html.includes(escape(localText(locale, 'destinations', 'sshUserHelpMessage', account))), 'remote-account guidance must not confuse borg serve with an account or prohibit root');
  }
}
const synthetic = { backup: { destinations: { sshUserHelpMessage: 'REMOTE ACCOUNT FIXTURE' } } };
assert.ok(render(synthetic).includes('REMOTE ACCOUNT FIXTURE'), 'actual JSX consumes translated whole account message');
if (process.argv[2] !== 'account') {
  for (const locale of [{}, ...locales.map(l => JSON.parse(read(`messages/${l}/common.json`)))]) {
    for (const user of ['borg', 'root', 'archive-user', '<img src=x onerror=alert(1)>']) {
      for (const generated of [false, true]) for (const loading of [false, true]) {
        const html = render(locale, { user, generated, loading, keyPath: '/custom/long-local-path/'.repeat(8) + 'private_key' });
        const action = localText(locale, 'actions', 'prepareSshKey', 'Prepare key');
        const expectedKeyHelp = localText(locale, 'destinations', 'sshKeyHelpMessage', keyHelp.replace('Prepare key', '{action}')).replaceAll('{action}', action);
        assert.ok(html.includes(escape(expectedKeyHelp)), 'complete local-path and manual-install instruction');
        assert.ok(html.includes(escape(localText(locale, 'destinations', 'sshKeySetupTitle', 'SSH key setup'))));
        assert.ok(html.match(/<button[^>]*>([\s\S]*?)<\/button>/)[1].includes(escape(action)));
        assert.ok(!html.includes('Regenerate') && !html.includes('Generate new SSH key') && !html.includes('when you save'));
        if (generated) {
          const expectedHelp = localText(locale, 'destinations', 'sshAuthorizedKeyHelp', 'Review the line below before adding it to ~/.ssh/authorized_keys for {user} on the remote host.').replaceAll('{user}', user);
          assert.ok(html.includes(escape(expectedHelp)));
          assert.ok(html.includes(escape(literalLine)), 'authorized_keys_line remains exact, escaped text');
        } else assert.ok(html.includes(escape(localText(locale, 'destinations', 'sshKeySetupHelp', setupHelp))));
        if (loading) assert.match(html, /<button[^>]*disabled=""/);
      }
    }
  }
  const translated = { backup: { actions: { prepareSshKey: 'FIXTURE PREPARE' }, destinations: {
    sshUserHelpMessage: 'FIXTURE ACCOUNT', sshKeyHelpMessage: 'At the end use {action}; FIXTURE PATH FIRST.',
    sshKeySetupTitle: 'FIXTURE TITLE', sshKeySetupHelp: 'FIXTURE INITIAL HELP',
    sshAuthorizedKeyHelp: '{user}: FIXTURE REMOTE FIRST. Review the line.',
  } } };
  for (const generated of [false, true]) {
    const html = render(translated, { user: '<custom>', generated });
    for (const text of ['FIXTURE ACCOUNT', 'At the end use FIXTURE PREPARE; FIXTURE PATH FIRST.', 'FIXTURE TITLE', generated ? '&lt;custom&gt;: FIXTURE REMOTE FIRST. Review the line.' : 'FIXTURE INITIAL HELP']) assert.ok(html.includes(text), text);
    assert.match(html, /<button[^>]*>.*FIXTURE PREPARE<\/button>/s);
  }
  // Each new key individually absent, even when all its siblings are translated.
  for (const key of [...keys, 'prepareSshKey']) {
    const missing = structuredClone(translated);
    const group = key === 'prepareSshKey' ? 'actions' : 'destinations';
    delete missing.backup[group][key];
    assert.equal(translate(missing)(`backup.${group}.${key}`), en.backup[group][key]);
  }
  assert.match(render({}, { keyPath: '' }), /<button[^>]*disabled=""/);
}
console.log(`PASS ${process.argv[2] || 'all'}: ${renderCount} actual JSX renders; ${locales.length} shipped catalogs + unconditional missing-key fallback; actual provider callback; translated/reordered messages.`);
