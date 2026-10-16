const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')

const source = fs.readFileSync(path.join(__dirname, '../lib/oidc-login.ts'), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText

async function run(hash, response, blockedStorage = false) {
  const saved = new Map(), session = new Map(), requests = [], history = []
  const sandbox = {
    exports: {}, URLSearchParams,
    require: name => { assert.equal(name, './api-config'); return { getApiUrl: x => x } },
    window: { location: { hash, pathname: '/', search: '' }, history: { replaceState: (...args) => history.push(args) } },
    localStorage: { setItem: (k, v) => saved.set(k, v) },
    sessionStorage: {
      setItem: (k, v) => { if (blockedStorage) throw Error('blocked'); session.set(k, v) },
      removeItem: k => { if (blockedStorage) throw Error('blocked'); session.delete(k) },
    },
    fetch: async (...args) => { requests.push(args); return response },
  }
  vm.runInNewContext(compiled, sandbox)
  await sandbox.exports.completeOIDCLogin()
  return { saved, session, requests, history }
}

;(async () => {
  let state = await run('#overview')
  assert.equal(state.requests.length, 0)
  assert.equal(state.history.length, 0)
  state = await run('#oidc_code=one-use-code', { ok: true, json: async () => ({ token: 'monitor-jwt' }) })
  assert.equal(state.saved.get('proxmenux-auth-token'), 'monitor-jwt')
  assert.equal(state.requests[0][0], '/api/auth/oidc/exchange')
  assert.equal(state.requests[0][1].credentials, 'include')
  assert.deepEqual(JSON.parse(state.requests[0][1].body), { code: 'one-use-code' })
  assert.equal(state.history[0][2], '/')
  for (const response of [
    { ok: false, json: async () => ({ error: 'expired' }) },
    { ok: true, json: async () => ({}) },
    { ok: false, json: async () => { throw SyntaxError('HTML') } },
  ]) {
    state = await run('#oidc_code=expired-code', response)
    assert.equal(state.saved.size, 0)
    assert.equal(state.session.get('proxmenux-oidc-error'), '1')
  }
  state = await run('#oidc_error=login_failed')
  assert.equal(state.requests.length, 0)
  assert.equal(state.session.get('proxmenux-oidc-error'), '1')
  await run('#oidc_error=login_failed', undefined, true)
  console.log('PASS: OIDC browser exchange, fragment cleanup and failed-login recovery')
})().catch(error => { console.error(error); process.exitCode = 1 })
