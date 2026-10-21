// Exercise the shipped error adapter and actual HostBackup handlers with a fake transport.
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const { ts, read, compile, translator } = require('./backup_i18n_seam.cjs');
const library = { exports: {} };
vm.runInNewContext(compile(read('lib/host-backup-messages.ts')), library);
const { hostBackupErrorText } = library.exports;
// Independently read the real API's literal/f-string contracts without importing
// Flask or running any route, host probe, script or persistence operation.
const contracts = JSON.parse(require('node:child_process').execFileSync('python3', ['-I', '-B', '-c', `
import ast,json,sys
tree=ast.parse(open(sys.argv[1]).read())
def messages(node):
    if isinstance(node,ast.Constant) and isinstance(node.value,str): return [node.value]
    if isinstance(node,ast.JoinedStr): return [''.join(part.value if isinstance(part,ast.Constant) else 'PARAMETER' for part in node.values)]
    if isinstance(node,ast.BoolOp): return [text for child in node.values for text in messages(child)]
    return []
result=set()
for function in tree.body:
    if isinstance(function,ast.FunctionDef) and function.name.startswith(('api_host_backups_','api_host_restore')):
        for node in ast.walk(function):
            if isinstance(node,ast.Dict):
                for key,value in zip(node.keys,node.values):
                    if isinstance(key,ast.Constant) and key.value=='error': result.update(messages(value))
print(json.dumps(sorted(result)))
`, 'AppImage/scripts/flask_server.py'], { encoding: 'utf8' }));
const flatten = n => !n || typeof n === 'boolean' ? [] : Array.isArray(n) ? n.flatMap(flatten)
  : typeof n === 'object' ? [n, ...flatten(n.props?.children)] : [n];
const text = n => flatten(n).filter(n => typeof n === 'string' || typeof n === 'number').join('');

function fixture(locale) {
  let cursor = 0, slots = [], tree, failure = 'path must be absolute', mutations = 0;
  const calls = [], t = translator(locale);
  const jsx = (type, props) => typeof type === 'function' ? type(props) : { type, props };
  const hooks = { useState(initial) { const i = cursor++; if (!(i in slots)) slots[i] = initial; return [slots[i], value => { slots[i] = value; }]; } };
  const requireModule = name => {
    if (name === 'react') return hooks;
    if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx };
    if (name === 'swr') return { default: () => ({ data: { paths: [{ path: '/kept' }] }, mutate: () => { mutations++; } }) };
    if (name.includes('i18n/provider')) return { useT: () => t };
    if (name.endsWith('host-backup-messages')) return library.exports;
    if (name.endsWith('api-config')) return { fetchApi: async (url, options) => { calls.push({ url, ...options }); if (failure) throw new Error(failure); return { status: 'ok' }; } };
    return new Proxy({}, { get: (_, key) => key });
  };
  const source = read('components/host-backup.tsx') + '\nexports.ExtraPathsSection = ExtraPathsSection;';
  const module = { exports: {} };
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX } }).outputText,
    { exports: module.exports, require: requireModule, Error, console });
  return { calls, t, render() { cursor = 0; tree = module.exports.ExtraPathsSection(); return tree; }, text: () => text(tree),
    input: () => flatten(tree).find(n => n.type === 'Input'),
    add: () => flatten(tree).find(n => n.type === 'Button' && text(n).includes(t('backup.actions.addPath'))),
    fail: message => { failure = message; }, mutations: () => mutations };
}

(async () => {
  assert.ok(contracts.length > 100, 'real HostBackup error contracts discovered');
  for (const message of contracts) {
    const translated = hostBackupErrorText(message, translator('sk'));
    assert.notEqual(translated, message, 'application-owned message must be localized: ' + message);
    assert.ok(!translated.includes('backup.apiErrors.'), 'every mapped key has a real Slovak value');
    assert.equal(hostBackupErrorText(message, translator('missing')), hostBackupErrorText(message, translator('en')), 'missing locale uses English');
  }
  for (const locale of ['en', 'sk', 'missing']) {
    const t = translator(locale);
    assert.equal(hostBackupErrorText(new Error('path must be absolute'), t), t('backup.apiErrors.absolutePath'));
    assert.equal(hostBackupErrorText({ message: 'this path is already configured' }, t), t('backup.apiErrors.pathConfigured'));
    assert.equal(hostBackupErrorText('job already exists: test_1', t), t('backup.apiErrors.jobExists', { value: 'test_1' }));
    const raw = 'tool failed: <img src=x onerror=unsafe()> path must be absolute';
    assert.equal(hostBackupErrorText(raw, t), raw, 'external diagnostics must not be partially matched or discarded');
    const long = 'path does not exist on this host: ' + 'x'.repeat(20000);
    assert.equal(hostBackupErrorText(long, t), long, 'large diagnostics preserved without pattern matching');
    for (const unknown of ['constructor', '__proto__', 'toString', 'future backend message']) assert.equal(hostBackupErrorText(unknown, t), unknown);
    for (const invalid of [null, undefined, {}, 23]) assert.equal(hostBackupErrorText(invalid, t), t('backup.apiErrors.requestFailed'));
    const unsafe = '<img src=x onerror=unsafe()>{backup.actions.run}';
    assert.equal(hostBackupErrorText('path does not exist on this host: ' + unsafe, t), t('backup.apiErrors.pathMissing', { value: unsafe }), 'captured paths remain literal data');
    const f = fixture(locale); f.render();
    assert.equal(f.add().props.disabled, true);
    await f.add().props.onClick(); assert.equal(f.calls.length, 0, 'blank path causes no request');
    f.input().props.onChange({ target: { value: 'relative-path' } }); f.render(); await f.add().props.onClick(); f.render();
    assert.equal(f.calls.length, 1); assert.equal(f.calls[0].url, '/api/host-backups/extra-paths');
    assert.equal(f.calls[0].method, 'POST'); assert.deepEqual(JSON.parse(f.calls[0].body), { path: 'relative-path' });
    assert.equal(f.input().props.value, 'relative-path'); assert.equal(f.mutations(), 0, 'rejected input preserves state and does not refresh as success');
    assert.ok(f.text().includes(t('backup.apiErrors.absolutePath'))); assert.ok(f.text().includes('/kept'));
    f.fail('future backend message'); await f.add().props.onClick(); f.render(); assert.ok(f.text().includes('future backend message'));
    f.fail(null); await f.add().props.onClick(); f.render(); assert.equal(f.input().props.value, ''); assert.equal(f.mutations(), 1);
  }
  // Adapter has no effect on the server's CLI/API/persistence contracts.
  const host = read('components/host-backup.tsx');
  const ast = ts.createSourceFile('host-backup.tsx', host, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX), encryptionCatches = [];
  function visit(node) { if (ts.isCatchClause(node) && node.block.getText(ast).includes('err.body?.tool_output')) encryptionCatches.push(node.block); ts.forEachChild(node, visit); }
  visit(ast); assert.equal(encryptionCatches.length, 2, 'scheduled and manual backup encryption paths both checked');
  for (const locale of ['en', 'sk', 'missing']) for (const block of encryptionCatches) {
    let displayed, effects = 0;
    const code = ts.transpileModule('function run(e) '+block.getText(ast)+'; run(error);', { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText;
    const t = translator(locale), error = Object.assign(new Error('failed to create PBS encryption keyfile'), { body: { tool_output: 'EXTERNAL TOOL DIAGNOSTIC' } });
    vm.runInNewContext(code, { error, t, hostBackupErrorText, setError: value => { displayed = value; }, setPbsImportBusy: () => {}, setSubmitting: () => {}, onCreated: () => effects++ });
    assert.ok(displayed.includes(hostBackupErrorText(error, t)) && displayed.includes('EXTERNAL TOOL DIAGNOSTIC'));
    assert.ok(!displayed.includes('{error}') && !displayed.includes('{detail}'), 'error interpolation must not leave an unresolved placeholder');
    assert.equal(effects, 0);
  }
  assert.ok(!host.includes('e instanceof Error ? e.message : String(e)'), 'all HostBackup catch consumers use the adapter');
  assert.ok(!host.includes('{e.error}') && !host.includes('{calendarPreview.error}'), 'structured error consumers use the adapter too');
  console.log('PASS: '+contracts.length+' real API contracts, HostBackup actual extra-path handlers, EN/SK/fallback, 0 calls for blank, rejected input/state, success, literal parameters and unknown diagnostics');
})().catch(error => { console.error(error); process.exitCode = 1; });
