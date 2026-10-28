// The retained health snapshot is informational, never permission to reboot.
const assert = require('node:assert/strict')
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm')
const app = path.resolve(__dirname, '../AppImage')
const ts = require(path.join(app, 'node_modules/typescript'))
const source = fs.readFileSync(path.join(app, 'components/host-update-status.tsx'), 'utf8')
const tree = ts.createSourceFile('restart.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
let trigger, contextEffect
function walk(n) {
  if (ts.isJsxElement(n) && n.openingElement.tagName.getText(tree) === 'Button' && n.children.some(c => c.getText(tree).includes('healthStatus.restart.button'))) {
    trigger = n.openingElement.attributes.properties.find(p => p.name?.getText(tree) === 'disabled').initializer.expression.getText(tree)
  }
  if (ts.isCallExpression(n) && n.expression.getText(tree) === 'useEffect' && n.arguments[0].getText(tree).includes('/api/health/reboot-context')) contextEffect = n.arguments[0].getText(tree)
  ts.forEachChild(n, walk)
}
walk(tree)
const evaluate = (code, scope) => vm.runInNewContext(ts.transpileModule('(' + code + ')', {compilerOptions: {target: ts.ScriptTarget.ES2020}}).outputText, scope)
function enabled(overrides = {}) {
  return !evaluate(trigger, {disabled: false, unavailable: false, context: {allowed: true}, pending: false, accepted: false, ...overrides})
}
async function main() {
  assert.equal(enabled({context: null}), false, 'remount after loading/reboot cannot enable a retained button before a fresh context')
  for (const reason of ['current', 'busy', 'unknown']) assert.equal(enabled({context: {allowed: false, reason}}), false)
  for (const key of ['disabled', 'unavailable', 'pending', 'accepted']) assert.equal(enabled({[key]: true}), false, key)
  assert.equal(enabled(), true, 'fresh required context permits an explicit confirmation')
  const calls = [], contexts = [], intervals = new Map(), timers = new Map()
  let seq = 0
  const scope = {open: false, getApiUrl: p => p, headers: () => ({}), AbortController,
    setContext: x => contexts.push(x), setSubmitted() {}, setError() {}, sending: {current: false},
    setTimeout: f => {timers.set(++seq, f); return seq}, clearTimeout: id => timers.delete(id),
    setInterval: (f, delay) => {intervals.set(++seq, {f, delay}); return seq}, clearInterval: id => intervals.delete(id),
    fetch: async (p, opts) => {calls.push({p, opts}); return {ok: true, json: async () => ({hostname: 'fixture', boot_id: 'new-boot', allowed: false, reason: 'current'})}}}
  const cleanup = evaluate(contextEffect, scope)()
  await new Promise(setImmediate)
  assert.equal(calls.length, 1, 'read the real reboot context even while confirmation is closed')
  assert.equal(calls[0].p, '/api/health/reboot-context')
  assert.ok(!calls[0].opts.method || calls[0].opts.method === 'GET')
  assert.equal(contexts.at(-1).allowed, false)
  assert.equal([...intervals.values()][0].delay, 30000, 'closed confirmation uses a bounded cheap probe')
  scope.fetch = async () => {throw Error('offline')}
  await [...intervals.values()][0].f()
  assert.equal(contexts.at(-1), null, 'connection loss revokes old permission')
  cleanup()
  assert.equal(intervals.size, 0); assert.equal(timers.size, 0)
  const modal = fs.readFileSync(path.join(app, 'components/health-status-modal.tsx'), 'utf8')
  assert.ok(modal.includes('unavailable={loading || snapshotUnavailable || !!error}'), 'stale/error/refresh snapshots must disable the action')
  assert.ok(!modal.includes('{healthData && !loading && ('), 'refresh must not unmount and forget an accepted reboot')
  assert.ok(modal.includes('<fieldset disabled={loading}'), 'keeping old results mounted must not enable other actions during refresh')
  console.log('PASS reboot recovery: closed-context probe, remount/current/offline/stale/pending guards, no POST or audit')
}
main().catch(e => {console.error(e); process.exitCode = 1})
