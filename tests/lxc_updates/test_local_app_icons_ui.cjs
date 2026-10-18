// Real panel handlers under the same deterministic hook fixture as native discovery.
const assert = require('node:assert/strict')
const {fixture, flatten, text, candidate} = require('./test_native_app_discovery_ui.cjs')
const logo = f => flatten(f.tree()).find(n => n.props?.id === 'app-logo')
const posts = f => f.calls.filter(c => c.method === 'POST' && c.url.endsWith('/apps'))
async function cachedImageContract() {
  const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm')
  const root = path.resolve(__dirname, '../../AppImage')
  const ts = require(path.join(root, 'node_modules/typescript'))
  const source = fs.readFileSync(path.join(root, 'components/lxc-app-panel.tsx'), 'utf8')
  const parsed = ts.createSourceFile('panel.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const fn = parsed.statements.find(n => ts.isFunctionDeclaration(n) && n.name?.text === 'CachedLocalLogo')
  assert.ok(fn)
  const code = ts.transpileModule('export ' + fn.getText(parsed), {compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
  }}).outputText
  let state, deps, cleanup, pendingEffect
  const requests = [], created = [], revoked = [], exported = {}
  vm.runInNewContext(code, {
    exports: exported, AbortController,
    require: () => ({jsx: (type, props) => ({type, props})}),
    useState: () => [state, value => {state = value}],
    useEffect: (fn, next) => {
      if (!deps || deps[0] !== next[0]) pendingEffect = () => {cleanup?.(); deps = next; cleanup = fn()}
    },
    getAuthToken: () => 'fixture-token', getApiUrl: src => '/proxy' + src,
    fetch: (url, opts) => new Promise(resolve => requests.push({url, opts, resolve})),
    URL: {createObjectURL: () => {const url = 'blob:fixture-' + created.length; created.push(url); return url}, revokeObjectURL: url => revoked.push(url)},
  })
  const render = src => {pendingEffect = null; const tree = exported.CachedLocalLogo({src, className: 'icon'}); pendingEffect?.(); return tree}
  const settle = async () => {for (let n = 0; n < 8; n++) await Promise.resolve()}
  // Flask's real SVG response includes a charset parameter.
  const reply = req => req.resolve({ok: true, blob: async () => ({type: 'image/svg+xml; charset=utf-8', size: 100})})
  const a = '/api/vms/101/apps/logo-cache/' + 'a'.repeat(32)
  const b = '/api/vms/102/apps/logo-cache/' + 'b'.repeat(32)
  render(a)
  assert.equal(requests[0].opts.headers.Authorization, 'Bearer fixture-token')
  assert.equal(requests[0].url, '/proxy' + a)
  reply(requests[0]); await settle()
  assert.equal(render(a).props.src, 'blob:fixture-0')
  assert.equal(render(b), null, 'never flash previous guest icon')
  assert.deepEqual(revoked, ['blob:fixture-0'])
  assert.equal(requests[0].opts.signal.aborted, true)
  cleanup(); reply(requests[1]); await settle()
  assert.equal(created.length, 1, 'late unmounted response creates no blob')
  render(a); requests[2].resolve({ok: false}); await settle()
  assert.equal(render(a), null, 'unauthorized/missing cache never falls back to raw authenticated URL')
}
async function editor(ports = [8080]) {
  const f = fixture({nativeCandidate: {...candidate, default_ports: ports}})
  f.render(); await f.settle()
  await f.button('searchApplications').props.onClick(); f.render()
  f.button('registerButton').props.onClick(); f.render(); f.render()
  return f
}
async function main() {
  await cachedImageContract()
  const f = await editor([8080, 8443])
  assert.equal(f.calls.filter(c => c.url.endsWith('/logo-discovery')).length, 0)
  const select = flatten(f.tree()).find(n => n.props?.['aria-label'] === 'vmLxc.appEditor.localLogoPort')
  select.props.onChange({target: {value: 'https:8443'}}); f.render(); f.render()
  await f.button('discoverLocalLogo').props.onClick(); f.render(); f.render()
  const request = f.calls.find(c => c.url.endsWith('/logo-discovery'))
  assert.deepEqual(JSON.parse(request.body), {port: 8443, scheme: 'https'})
  assert.match(logo(f).props.value, /^\/api\/vms\/101\/apps\/logo-cache\//)
  assert.equal(posts(f).length, 0, 'lookup only changes the draft')
  await f.button('saveButton').props.onClick(); f.render()
  assert.match(JSON.parse(posts(f)[0].body).logo_url, /logo-cache/)

  for (const action of ['logo-edit', 'port-edit', 'cancel-reopen', 'guest-roundtrip', 'endpoint-change']) {
    const g = await editor([8080, 8443])
    g.holdIcon()
    const pending = g.button('discoverLocalLogo').props.onClick()
    g.render()
    if (action === 'logo-edit') logo(g).props.onChange({target: {value: 'https://example.test/manual.png'}})
    if (action === 'port-edit') {
      const input = flatten(g.tree()).find(n => n.type === 'Input' && n.props.value === 8080)
      assert.ok(input); input.props.onChange({target: {value: '8090'}})
    }
    if (action === 'cancel-reopen') {
      g.button('cancelButton').props.onClick(); g.render()
      g.button('registerButton').props.onClick()
    }
    if (action === 'guest-roundtrip') {
      g.render({vmid: 102}); g.render({vmid: 101}); await g.settle()
    }
    if (action === 'endpoint-change') {
      flatten(g.tree()).find(n => n.props?.['aria-label'] === 'vmLxc.appEditor.localLogoPort').props.onChange({target: {value: 'https:8443'}})
    }
    g.render(); g.render(); g.resolveIcon(); await pending; g.render()
    assert.ok(!String(logo(g)?.props.value || '').includes('/logo-cache/'), action + ' rejects late success')
    assert.equal(posts(g).length, 0)
    assert.equal(g.calls.find(c => c.url.endsWith('/logo-discovery')).signal.aborted, true)
  }

  for (const code of ['local_logo_unavailable', 'local_logo_stopped']) {
    const g = await editor()
    logo(g).props.onChange({target: {value: 'https://example.test/existing.png'}}); g.render(); g.render()
    g.setIconError({body: {code}})
    await g.button('discoverLocalLogo').props.onClick(); g.render()
    assert.equal(logo(g).props.value, 'https://example.test/existing.png')
    assert.ok(text(g.tree()).includes(code === 'local_logo_stopped' ? 'localLogoStopped' : 'localLogoUnavailable'))
    assert.equal(posts(g).length, 0)
  }
  const wrong = await editor()
  wrong.setIconResult({logo_url: '/api/vms/102/apps/logo-cache/' + 'b'.repeat(32)})
  await wrong.button('discoverLocalLogo').props.onClick(); wrong.render()
  assert.ok(!String(logo(wrong).props.value).includes('/logo-cache/'))
  const immediate = await editor()
  immediate.holdIcon(); immediate.setIconError({body: {code: 'local_logo_unavailable'}})
  const lateError = immediate.button('discoverLocalLogo').props.onClick()
  logo(immediate).props.onChange({target: {value: 'https://example.test/typed.png'}})
  // Deliberately resolve before another render: batched input must invalidate too.
  immediate.resolveIcon(); await lateError; immediate.render()
  assert.equal(logo(immediate).props.value, 'https://example.test/typed.png')
  assert.ok(!text(immediate.tree()).includes('localLogoUnavailable'))
  const noPort = await editor([])
  assert.equal(noPort.button('discoverLocalLogo').props.disabled, true)
  await noPort.button('discoverLocalLogo').props.onClick()
  assert.equal(noPort.calls.filter(c => c.url.endsWith('/logo-discovery')).length, 0)
  console.log('PASS local icons: explicit selected port, draft/save, no-port, errors, cancel/reopen, edit/guest races and forbidden writes')
}
main().catch(error => {console.error(error); process.exitCode = 1})
