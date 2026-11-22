// The remove UI must only submit its accepted task once and must never turn a
// refresh/recovery into a second delete request.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')

const root = path.resolve(__dirname, '../../AppImage')
const deps = process.env.PROXMENUX_NODE_DEPS || root
const ts = require(path.join(deps, 'node_modules/typescript'))
const dialog = fs.readFileSync(path.join(root, 'components/lxc-remove-dialog.tsx'), 'utf8')
const vmPage = fs.readFileSync(path.join(root, 'components/virtual-machines.tsx'), 'utf8')

assert.match(vmPage, /capabilities\.admin && selectedVM\?\.type === "lxc"/, 'only administrators see the LXC action')
assert.match(vmPage, /disabled=\{selectedVM\?\.status !== "stopped" \|\| controlLoading\}\s+onSelect=\{\(\) => setRemoveLxcOpen\(true\)\}/,
  'the menu opens a review dialog; it does not submit a remove request')
assert.match(dialog, /typedVmid === String\(preview\.target\.vmid\)/, 'the exact VMID gates the submit button')
assert.match(dialog, /const \[purge, setPurge\] = useState\(false\)/, 'purging job configuration defaults to off')
assert.match(dialog, /const \[destroyUnreferenced, setDestroyUnreferenced\] = useState\(false\)/,
  'unreferenced disk removal defaults to off')
assert.doesNotMatch(dialog, /confirm_no_backup|createBackup/, 'backup inventory is outside the removal flow')
assert.match(dialog, /submitRef\.current\) return/, 'a duplicate click cannot submit again')
assert.match(dialog, /saveLxcRemovalReceipt\(receipt\)[\s\S]*method: "POST"/,
  'the recovery receipt is saved before the destructive request')
assert.doesNotMatch(dialog, /method:\s*["']DELETE["']/, 'the browser never issues PVE delete directly')

const source = fs.readFileSync(path.join(root, 'lib/lxc-removal.ts'), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText
const reads = []
const store = new Map()
const context = {
  exports: {},
  window: {},
  sessionStorage: {
    get length() { return store.size },
    key(index) { return [...store.keys()][index] || null },
    getItem(key) { return store.get(key) || null },
    setItem(key, value) { store.set(key, value) },
    removeItem(key) { store.delete(key) },
  },
  AbortSignal: { timeout: value => ({ value }) },
  require: () => ({ fetchApi: async (url, options) => {
    reads.push([url, options])
    return { state: 'running', task: 'UPID:fixture' }
  }}),
}
vm.runInNewContext(compiled, context)
const helper = context.exports

store.set(helper.lxcRemovalReceiptKey(90), 'malformed')
assert.equal(helper.saveLxcRemovalReceipt({ vmid: 100, check: 'operation-a' }), true)
assert.equal(helper.saveLxcRemovalReceipt({ vmid: 200, check: 'operation-b' }), true)
const recovered = helper.loadLxcRemovalReceipt()
assert.equal(recovered?.vmid, 100, 'reload restores the accepted VMID')
assert.equal(recovered?.check, 'operation-a', 'reload restores a receipt even without a native task')
assert.equal(helper.loadLxcRemovalReceipt(200)?.check, 'operation-b', 'reopening a target selects only its receipt')
helper.clearLxcRemovalReceipt(100)
assert.equal(helper.loadLxcRemovalReceipt(100), null, 'terminal state removes only its own receipt')
assert.equal(helper.loadLxcRemovalReceipt(200)?.check, 'operation-b')
context.sessionStorage.setItem = () => { throw Error('storage unavailable') }
assert.equal(helper.saveLxcRemovalReceipt({ vmid: 100, check: 'check' }), false)

;(async () => {
  const result = await helper.readLxcRemovalTask(recovered)
  assert.equal(result.state, 'running')
  assert.equal(reads.length, 1)
  assert.equal(reads[0][0], '/api/vms/100/remove-operation')
  assert.equal(reads[0][1].headers['X-LXC-Removal-Check'], 'operation-a')
  assert.equal(reads[0][1].method, undefined, 'task tracking is read-only')
  console.log('PASS LXC remove UI: gated action, exact confirmation, receipt recovery and read-only task polling')
})().catch(error => { console.error(error); process.exitCode = 1 })
