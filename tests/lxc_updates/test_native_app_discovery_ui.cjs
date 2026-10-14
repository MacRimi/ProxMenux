// Execute the real panel, handlers and editor with inert hook/UI/API fixtures.
// This is component interaction evidence, not browser or Proxmox acceptance.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const root = path.resolve(__dirname, '../../AppImage')
const ts = require(path.join(root, 'node_modules/typescript'))
const source = fs.readFileSync(path.join(root, 'components/lxc-app-panel.tsx'), 'utf8')
const compiled = ts.transpileModule(source, {compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
}, reportDiagnostics: true})
assert.equal(compiled.diagnostics.length, 0)

const flatten = node => !node || typeof node !== 'object' ? [] : [node, ...(
  [node.props?.children].flat(Infinity).flatMap(flatten)
)]
const text = node => node == null || node === false ? '' : typeof node !== 'object'
  ? String(node) : [node.props?.children].flat(Infinity).map(text).join(' ')
const candidate = {
  slug: 'native-' + 'a'.repeat(24), discovery_id: 'native-' + 'a'.repeat(24),
  name: 'handmade', source: 'native_metadata', installed_version: null,
  evidence: [{kind: 'installation_file', value: '/opt/handmade/server'}], default_ports: [],
}

function fixture() {
  let cursor = 0, tree, props, effects = [], states = [], refs = [], effectStates = []
  const calls = [], cachedWrites = []
  let native = {vmid: 101, status: 'not_scanned', candidates: [], stale: false}
  let holdScan, scanGate, holdSave, saveGate, scanStatus = 'complete'
  const seed = {sidecar: {vmid: 101, apps: []}, suggestions: {extras: [], port_suggestions: []}}
  const react = {
    useState(initial) {
      const index = cursor++
      if (!(index in states)) states[index] = typeof initial === 'function' ? initial() : initial
      return [states[index], value => {states[index] = typeof value === 'function' ? value(states[index]) : value}]
    },
    useRef(value) {const index = cursor++; return refs[index] ||= {current: value}},
    useMemo(fn) {cursor++; return fn()}, useCallback(fn) {cursor++; return fn},
    useEffect(fn, deps) {
      const index = cursor++, prior = effectStates[index]
      if (!prior || !deps || deps.some((value, i) => value !== prior.deps?.[i])) {
        effects.push(() => {prior?.cleanup?.(); effectStates[index] = {deps, cleanup: fn()}})
      }
    },
  }
  const api = async (url, options = {}) => {
    calls.push({url, ...options})
    if (url.endsWith('/native-discovery')) {
      if (options.method === 'POST') {
        if (scanGate) await scanGate
        native = {...native, status: scanStatus, candidates: [candidate]}
      }
      return structuredClone(native)
    }
    if (url.endsWith('/apps/suggestions')) return seed.suggestions
    if (url.endsWith('/apps') && options.method === 'POST') {
      if (saveGate) await saveGate
      return {vmid: Number(url.split('/')[3]), apps: [{id: 'saved', ...JSON.parse(options.body), state: {}}]}
    }
    if (url.endsWith('/adguard-setup')) return {available: false}
    return []
  }
  const cache = {
    getLxcAppsCached: () => null, fetchLxcApps: async () => seed,
    subscribeLxcApps: () => () => {}, setLxcAppsCached: (...args) => cachedWrites.push(args),
  }
  const exports = {}
  vm.runInNewContext(compiled.outputText, {exports, console, setTimeout, clearTimeout,
    require: name => {
      if (name === 'react') return react
      if (name === 'react/jsx-runtime') return {jsx: (type, props) => ({type, props}), jsxs: (type, props) => ({type, props})}
      if (name.includes('api-config')) return {fetchApi: api}
      if (name.includes('lxc-apps-cache')) return cache
      if (name.includes('i18n/provider')) return {useT: () => (key, values) => key + (values ? JSON.stringify(values) : '')}
      if (name.includes('category-color')) return {useIsLightTheme: () => false, categoryChipStyle: () => ({})}
      if (name.includes('category-label')) return {getCategoryLabel: value => value}
      return new Proxy({}, {get: (_, key) => key})
    },
  })
  function render(next = props || {vmid: 101, initialData: seed}) {
    props = next; cursor = 0; effects = []
    tree = exports.LxcAppPanel(props)
    for (const effect of effects) effect()
    return tree
  }
  const settle = async () => {for (let i = 0; i < 6; i++) await Promise.resolve(); render()}
  const button = key => {
    const match = flatten(tree).find(n => n.type === 'Button' && text(n).includes('vmLxc.appEditor.' + key))
    assert.ok(match, 'Missing button ' + key)
    return match
  }
  return {render, settle, calls, cachedWrites, button, tree: () => tree,
    setNative: value => {native = value},
    setScanStatus: value => {scanStatus = value},
    holdScan: () => {scanGate = new Promise(resolve => {holdScan = resolve})}, resolveScan: () => holdScan(),
    holdSave: () => {saveGate = new Promise(resolve => {holdSave = resolve})}, resolveSave: () => holdSave(),
  }
}

async function main() {
  const f = fixture()
  f.render(); await f.settle()
  assert.equal(f.calls.filter(c => c.method === 'POST').length, 0, 'mount and cache reads never scan')
  await f.button('searchApplications').props.onClick(); f.render()
  assert.equal(f.calls.filter(c => c.url.endsWith('/native-discovery') && c.method === 'POST').length, 1)
  assert.ok(text(f.tree()).includes('nativeVersionUnknown'), 'unknown version remains visible')
  assert.ok(text(f.tree()).includes('/opt/handmade/server'))
  await f.button('registerButton').props.onClick(); f.render()
  assert.ok(text(f.tree()).includes('saveButton'), 'candidate opens actual editor')
  f.button('cancelButton').props.onClick(); f.render()
  assert.equal(f.calls.filter(c => /\/apps$/.test(c.url) && c.method === 'POST').length, 0, 'cancel never registers')
  await f.button('registerButton').props.onClick(); f.render()
  await f.button('saveButton').props.onClick(); f.render()
  const saved = f.calls.find(c => /\/apps$/.test(c.url) && c.method === 'POST')
  const payload = JSON.parse(saved.body)
  assert.equal(saved.url, '/api/vms/101/apps')
  assert.equal(payload.discovery_id, candidate.discovery_id)
  assert.ok(!payload.helper_slug, 'native identity never becomes a helper')
  assert.equal(payload.installed_via, '')
  assert.equal(payload.update_method, 'none')
  assert.equal(payload.update_command, '')
  assert.equal(payload.repo, '')
  assert.equal(payload.upstream_type, '')

  const partial = fixture()
  partial.render(); await partial.settle(); partial.setScanStatus('partial')
  await partial.button('searchApplications').props.onClick(); partial.render()
  assert.ok(text(partial.tree()).includes('nativeScanPartial'))
  assert.ok(text(partial.tree()).includes('nativeEvidenceStale'))
  const failed = fixture()
  failed.render(); await failed.settle(); failed.setScanStatus('error')
  await failed.button('searchApplications').props.onClick(); failed.render()
  assert.ok(text(failed.tree()).includes('nativeScanFailed'))
  assert.equal(failed.calls.filter(c => c.url.endsWith('/apps/suggestions') && c.method === 'POST').length, 0)

  const late = fixture()
  late.render(); await late.settle(); late.holdScan()
  const scan = late.button('searchApplications').props.onClick()
  late.render({vmid: 102}); await late.settle()
  late.resolveScan(); await scan; late.render()
  assert.ok(!text(late.tree()).includes('/opt/handmade/server'), 'late A scan cannot appear in B')
  assert.equal(late.cachedWrites.length, 0)
  assert.equal(late.calls.filter(c => c.url.endsWith('/apps/suggestions') && c.method === 'POST').length, 0)

  const saveLate = fixture()
  saveLate.render(); await saveLate.settle()
  await saveLate.button('searchApplications').props.onClick(); saveLate.render()
  await saveLate.button('registerButton').props.onClick(); saveLate.render()
  saveLate.holdSave(); const saving = saveLate.button('saveButton').props.onClick()
  const priorWrites = saveLate.cachedWrites.length
  saveLate.render({vmid: 102}); await saveLate.settle()
  saveLate.resolveSave(); await saving; saveLate.render()
  assert.equal(saveLate.cachedWrites.length, priorWrites, 'late save response does not update new target')
  assert.equal(saveLate.calls.filter(c => /\/vms\/102\/apps$/.test(c.url) && c.method === 'POST').length, 0)

  const oci = fixture()
  oci.render({vmid: 101, oci: {instance: true}, initialData: {sidecar: {apps: []}, suggestions: {oci_instance: {template_id: 'image-app'}, extras: []}}})
  await oci.settle()
  await oci.button('refreshData').props.onClick()
  assert.equal(oci.calls.filter(c => c.url.endsWith('/native-discovery') && c.method === 'POST').length, 0, 'OCI refresh never native-scans')
  console.log('PASS native discovery: real panel Find → editor → Cancel/Save, no automatic scan, safe payload, CT switching and OCI refresh (fixtures)')
}
main().catch(error => {console.error(error); process.exitCode = 1})
