// Run the shipped translation adapter, transport and both dialog components.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const compile = source => ts.transpileModule(source, {compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
}}).outputText;
const translations = Object.fromEntries(['en', 'sk'].map(locale => [locale, JSON.parse(fs.readFileSync(`AppImage/messages/${locale}/common.json`))]));
const translate = locale => (key, params = {}) => {
  const value = key.split('.').reduce((tree, part) => tree?.[part], translations[locale]);
  assert.equal(typeof value, 'string', key);
  return value.replace(/\{(\w+)\}/g, (match, key) => params[key] ?? match);
};
const adapter = {exports: {}};
vm.runInNewContext(compile(fs.readFileSync('AppImage/lib/monitor-link-errors.ts', 'utf8')), adapter);
const {monitorLinkError} = adapter.exports;
const codes = {
  monitor_link_address_required: 'addressRequired', monitor_link_invalid_address: 'invalidAddress',
  monitor_link_address_credentials: 'addressCredentials', monitor_link_invalid_port: 'invalidPort',
  monitor_link_invalid_request: 'invalidRequest', monitor_link_duplicate: 'duplicate',
  monitor_link_not_found: 'notFound', monitor_link_detected_remove: 'detectedRemove',
};
const failure = (code, params) => Object.assign(new Error('RAW ENGLISH SECRET DETAILS'), {body: {error: 'RAW ENGLISH SECRET DETAILS', code, params}});

const flatten = tree => !tree || typeof tree === 'boolean' ? [] : Array.isArray(tree) ? tree.flatMap(flatten)
  : typeof tree === 'object' ? [tree, ...flatten(tree.props?.children)] : [tree];
const text = tree => flatten(tree).filter(n => typeof n === 'string' || typeof n === 'number').join('');
const jsx = (type, props) => ({type, props});
const source = compile(fs.readFileSync('AppImage/components/monitor-switcher.tsx', 'utf8') + '\nexport {ManageLinksDialog};');

function fixture({locale = 'sk', links = [], origin = false, loadError = false, loading = false} = {}) {
  let slots = [], cursor = 0, effects = [], tree, responseError, refreshFailure = false;
  const calls = [], refreshes = [], storage = new Map();
  const candidates = [{u: 'https://other.test', n: 'Other', p: 'pve'}];
  const carried = Buffer.from(JSON.stringify(candidates)).toString('base64url');
  const location = {origin: 'https://current.test', hostname: 'current.test', pathname: '/', hash: '',
    search: origin ? `?pmx_from=https%3A%2F%2Fsource.test&pmx_name=Source&pmx_links=${carried}` : ''};
  const react = {
    useState(initial) {const slot = cursor++; if (!(slot in slots)) slots[slot] = typeof initial === 'function' ? initial() : initial;
      return [slots[slot], value => {slots[slot] = typeof value === 'function' ? value(slots[slot]) : value;}];},
    useEffect(fn, deps) {const slot = cursor++; const old = slots[slot];
      if (!old || deps.some((dep, i) => dep !== old[i])) effects.push(fn);
      slots[slot] = deps;
    },
  };
  const exported = {};
  vm.runInNewContext(source, {exports: exported, URL, URLSearchParams, escape, unescape,
    atob: value => Buffer.from(value, 'base64').toString('binary'), btoa: value => Buffer.from(value, 'binary').toString('base64'),
    window: {location, history: {replaceState() {location.search = ''}}},
    sessionStorage: {getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value)},
    require(name) {
      if (name === 'react') return react;
      if (name === 'react/jsx-runtime') return {jsx, jsxs: jsx, Fragment: 'Fragment'};
      if (name === 'swr') return {default: () => ({data: {self: {name: 'Current', product: 'pve'}, links}, error: loadError, isLoading: loading,
        mutate: async () => refreshes.push('all')}), mutate: async key => {refreshes.push(key); if (refreshFailure) throw new Error('RAW REFRESH ERROR');}};
      if (name.includes('i18n/provider')) return {useT: () => translate(locale)};
      if (name.includes('monitor-link-errors')) return {monitorLinkError};
      if (name.includes('api-config')) return {fetchApi: async (path, options) => {calls.push({path, ...options}); if (responseError) throw responseError; return {success: true};}};
      return new Proxy({}, {get: (_, key) => key});
    },
  });
  return {
    render(component = 'ManageLinksDialog') {cursor = 0; effects = []; tree = exported[component]({open: true, onOpenChange() {}, nodeName: 'Current'}); effects.forEach(fn => fn()); return tree;},
    button(label) {const node = flatten(tree).find(n => n.type === 'Button' && (text(n) === label || n.props['aria-label'] === label)); assert.ok(node, label); return node;},
    input(id) {const node = flatten(tree).find(n => n.type === 'Input' && (n.props.id === id || n.props['aria-label'] === id)); assert.ok(node, id); return node;},
    nodes: () => flatten(tree), text: () => text(tree), fail: error => {responseError = error;}, failRefresh: () => {refreshFailure = true;}, calls, refreshes, storage,
  };
}

async function main() {
  for (const locale of ['en', 'sk']) {
    const t = translate(locale);
    for (const [code, key] of Object.entries(codes)) assert.equal(monitorLinkError(failure(code), t), t(`monitorLinks.errors.${key}`));
    assert.equal(monitorLinkError(failure('monitor_link_limit', {count: 64}), t), t('monitorLinks.errors.limit', {count: 64}));
    for (const error of [null, undefined, 'raw', new Error('raw'), {body: null}, {body: {}},
      ...['constructor', '__proto__', 'toString', 'unknown', 'monitor_links_save_failed'].map(code => failure(code)),
      ...[undefined, null, '64', 0, -1, 1.5, NaN, Infinity, 2 ** 54].map(count => failure('monitor_link_limit', {count}))]) {
      assert.equal(monitorLinkError(error, t), t('monitorLinks.saveFailed'));
    }
    const f = fixture({locale, links: [{key: 'manual:saved', name: 'Saved', url: 'https://saved.test', manual: true}]});
    f.render(); f.button(t('monitorLinks.changeAddress')).props.onClick(); f.render();
    f.input(t('monitorLinks.address')).props.onChange({target: {value: 'https://unsaved.test'}}); f.render();
    f.button(t('monitorLinks.cancel')).props.onClick(); f.render();
    assert.equal(f.calls.length, 0, 'Cancel must not write');
    f.button(t('monitorLinks.changeAddress')).props.onClick(); f.render();
    assert.equal(f.input(t('monitorLinks.address')).props.value, 'https://saved.test', 'Cancel discards address draft');
    f.input(t('monitorLinks.address')).props.onChange({target: {value: 'https://changed.test'}}); f.render();
    await f.button(t('monitorLinks.save')).props.onClick(); f.render();
    assert.equal(f.calls[0].method, 'PATCH'); assert.deepEqual(JSON.parse(f.calls[0].body), {url: 'https://changed.test'});
    assert.equal(f.button(t('monitorLinks.add')).props.disabled, true, 'Blank address cannot be submitted');
    f.input('monitor-link-url').props.onChange({target: {value: 'ftp://bad.test'}}); f.render();
    f.fail(failure('monitor_link_invalid_address')); await f.button(t('monitorLinks.add')).props.onClick(); f.render();
    assert.ok(f.text().includes(t('monitorLinks.errors.invalidAddress')));
    assert.equal(f.input('monitor-link-url').props.value, 'ftp://bad.test', 'Failure retains draft');
    assert.ok(!f.text().includes('RAW ENGLISH'));
    f.fail(new Error('raw network details')); await f.button(t('monitorLinks.remove')).props.onClick(); f.render();
    assert.ok(f.text().includes(t('monitorLinks.saveFailed')));
    const failedRead = fixture({locale, loadError: new Error('raw')}); failedRead.render();
    assert.ok(failedRead.text().includes(t('monitorLinks.loadFailed')));
    const pendingRead = fixture({locale, loading: true}); pendingRead.render();
    assert.ok(pendingRead.text().includes(t('monitorLinks.checking')));

    const declined = fixture({locale, origin: true});
    for (let n = 0; n < 3; n++) declined.render('MonitorSwitcher');
    declined.button(t('monitorLinks.notNow')).props.onClick(); declined.render('MonitorSwitcher');
    assert.equal(declined.calls.length, 0, 'Not now must not write');
    const carried = fixture({locale, origin: true});
    for (let n = 0; n < 3; n++) carried.render('MonitorSwitcher');
    const boxes = carried.nodes().filter(n => n.type === 'Checkbox'); assert.equal(boxes.length, 2);
    boxes[1].props.onCheckedChange(false); carried.render('MonitorSwitcher');
    carried.fail(failure('monitor_link_duplicate'));
    carried.failRefresh();
    await carried.button(t('monitorLinks.addSelected')).props.onClick(); carried.render('MonitorSwitcher');
    assert.equal(carried.calls.length, 1, 'Only selected origin is attempted');
    assert.equal(JSON.parse(carried.calls[0].body).url, 'https://source.test');
    assert.ok(carried.text().includes(t('monitorLinks.errors.duplicate')));
    assert.equal(carried.refreshes.length, 1, 'Failed/partially successful batch refreshes the visible list');
  }
  // Real authenticated transport preserves additive fields for the adapter.
  const api = {exports: {}, process: {env: {}}, fetch: async () => new Response(JSON.stringify({error: 'Original English error', code: 'monitor_link_duplicate'}), {status: 400, headers: {'Content-Type': 'application/json'}})};
  vm.runInNewContext(compile(fs.readFileSync('AppImage/lib/api-config.ts', 'utf8')), api);
  try {await api.exports.fetchApi('/api/monitor-links', {method: 'POST'}); assert.fail('expected rejection');}
  catch (error) {assert.equal(error.status, 400); assert.equal(error.message, 'Original English error'); assert.equal(monitorLinkError(error, translate('sk')), translations.sk.monitorLinks.errors.duplicate);}
  const en = translations.en.monitorLinks, sk = translations.sk.monitorLinks;
  assert.deepEqual(Object.keys(en.errors).sort(), Object.keys(sk.errors).sort());
  for (const key of Object.keys(en.errors)) {
    assert.ok(sk.errors[key]);
    assert.deepEqual(en.errors[key].match(/\{\w+\}/g), sk.errors[key].match(/\{\w+\}/g), key);
  }
  console.log('PASS: EN/SK known/unknown errors, real transport, both dialogs, Cancel/Not now zero writes, draft persistence, selected-only batch, localized loading/failure');
}
main().catch(error => {console.error(error); process.exitCode = 1;});
