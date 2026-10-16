// Execute the actual handler and footer: acceptance is not task completion.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const root = path.resolve(__dirname, '../../AppImage')
const ts = require(path.join(root, 'node_modules/typescript'))
const source = fs.readFileSync(path.join(root, 'components/virtual-machines.tsx'), 'utf8')
const tree = ts.createSourceFile('vm.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
let handler, footer
function walk(node) {
  if (ts.isVariableDeclaration(node) && node.name.getText(tree) === 'handleVMControl') handler = node.getText(tree)
  if (ts.isJsxElement(node) && node.openingElement.tagName.getText(tree) === 'div'
    && node.openingElement.attributes.getText(tree).includes('border-t border-border bg-background px-6 py-4 mt-auto'))
    footer = node.getText(tree)
  ts.forEachChild(node, walk)
}
walk(tree)
function compile(code, context) {
  vm.runInNewContext(ts.transpileModule(code, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
  }}).outputText, context)
  return context.exports
}
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
function buttons(node) {
  if (!node || typeof node !== 'object') return []
  if (Array.isArray(node)) return node.flatMap(buttons)
  return [...(node.type === 'Button' ? [node] : []), ...buttons(node.props?.children)]
}
;(async () => {
  for (const action of ['start', 'shutdown', 'reboot', 'stop']) {
    const completion = deferred(), accepted = deferred()
    const context = {
      exports: {}, console: { error() {} }, selectedVM: { vmid: 100, status: action === 'start' ? 'stopped' : 'running', type: 'lxc' },
      selectedVMRef: { current: { vmid: 100 } }, controlRequestRef: { current: false },
      controlLoading: false, controlAction: null, posts: 0, alerts: [],
      setControlLoading(value) { context.controlLoading = value },
      setControlAction(value) { context.controlAction = value },
      setSelectedVM(value) { context.selectedVM = typeof value === 'function' ? value(context.selectedVM) : value },
      rows: [{ vmid: 100, status: 'running' }, { vmid: 200, status: 'stopped' }], publications: 0,
      setVMDetails() {}, mutate: async (update, options) => {
        if (!update) return
        assert.equal(options.revalidate, false, 'publish the confirmation before another GET')
        context.rows = update(context.rows)
        assert.equal(context.rows[1].status, 'stopped', 'only the operated guest changes')
        context.publications++
      }, invalidateLxcApps() {},
      vmModalCacheRef: { current: Object.fromEntries(['details','backups','mountPoints','schedule','firewall'].map(n => [n, new Map()])) },
      fetchApi: async (url, options) => {
        if (options?.method === 'POST') { context.posts++; return accepted.promise }
        return { config: {} }
      },
      waitForVmControlTask: () => completion.promise,
      t: key => key, alert: text => context.alerts.push(text),
      require: () => ({ jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) }),
    }
    for (const name of ['Button','Terminal','Play','Power','RotateCcw','StopCircle','Loader2']) context[name] = name
    const ui = compile(`const ${handler}; exports.control = handleVMControl; exports.footer = () => (${footer});`, context)
    const run = ui.control(100, action)
    assert.equal(context.controlLoading, true, 'busy starts before the POST')
    accepted.resolve({ success: true, task: 'task-id' })
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(context.controlLoading, true, 'accepted control must stay busy until the Proxmox task completes')
    assert.equal(context.publications, 0, 'acceptance never publishes an assumed final status')
    assert(buttons(ui.footer()).filter(b => b.props.title).every(b => b.props.disabled), 'all power buttons stay disabled')
    await ui.control(100, action)
    assert.equal(context.posts, 1, 'a double click never submits a second operation')
    completion.resolve({ guest_status: action === 'shutdown' || action === 'stop' ? 'stopped' : 'running' })
    await run
    assert.equal(context.controlLoading, false)
    assert.equal(context.controlRequestRef.current, false)
    assert.equal(context.selectedVM.status, action === 'shutdown' || action === 'stop' ? 'stopped' : 'running')
    assert.equal(context.alerts.length, 0)
    assert.equal(context.controlAction, null)
    assert.equal(context.publications, 1)
    assert.equal(context.rows[0].status, action === 'shutdown' || action === 'stop' ? 'stopped' : 'running')
    const failed = deferred()
    context.fetchApi = async () => ({ task: 'task-id' })
    context.waitForVmControlTask = () => failed.promise
    const failureRun = ui.control(100, action)
    failed.reject(new Error('task failed'))
    await failureRun
    assert.equal(context.controlLoading, false)
    assert.equal(context.alerts.length, 1, 'a task error cannot look like completion')
    const switched = deferred()
    context.waitForVmControlTask = () => switched.promise
    const switchRun = ui.control(100, action)
    context.selectedVMRef.current = { vmid: 200 }
    context.selectedVM = { vmid: 200, status: 'stopped' }
    switched.resolve({ guest_status: 'running' })
    await switchRun
    assert.equal(context.selectedVM.vmid, 200)
    assert.equal(context.selectedVM.status, 'stopped', 'completion cannot overwrite another guest')
    assert.equal(buttons(ui.footer()).filter(b => b.props.title).some(b => /Pending/.test(b.props.title)), false)
  }
  const polls = [], sequence = []
  let clock = 0, readError = null
  const helper = compile(fs.readFileSync(path.join(root, 'lib/vm-control.ts'), 'utf8'), {
    exports: {}, Date: { now: () => clock }, AbortSignal: { timeout: () => ({}) },
    setTimeout: callback => { clock += 1000; callback() },
    require: () => ({ fetchApi: async (url, options) => {
      polls.push([url, options]); if (readError) throw readError
      return sequence.shift() || { status: 'running' }
    }}),
  })
  // A reboot with "running" status is still pending until its task reports OK.
  for (const action of ['start','shutdown','reboot','stop']) {
    clock = 0; polls.length = 0
    const expected = ['shutdown','stop'].includes(action) ? 'stopped' : 'running'
    sequence.push({ status: 'running', guest_status: expected },
      { status: 'stopped', exitstatus: 'OK', guest_status: expected === 'running' ? 'stopped' : 'running' },
      { status: 'stopped', exitstatus: 'OK', guest_status: expected })
    assert.equal((await helper.waitForVmControlTask(100, action, 'UPID:test')).guest_status, expected)
    assert.equal(polls.length, 3, 'wait for both the task and actual target state')
    assert(polls.every(([url, options]) => url === '/api/vms/100/control-task/UPID%3Atest' && !options.method),
      'polling only reads the accepted task; no second POST or package check')
  }
  for (const response of [null, {}, { status:'stopped' }, { status:'stopped', exitstatus:'failed' }]) {
    sequence.push(response)
    // null must reach the helper, rather than the fake's default running state.
    if (response === null) sequence[sequence.length - 1] = { status: null }
    await assert.rejects(helper.waitForVmControlTask(100, 'reboot', 'task'), /controlNotConfirmed|failed/)
  }
  clock = 0; polls.length = 0
  await assert.rejects(helper.waitForVmControlTask(100, 'reboot', 'task'), /controlNotConfirmed/)
  assert.equal(clock, 180000, 'bounded wait includes the exact deadline')
  polls.length = 0
  await assert.rejects(helper.waitForVmControlTask(100, 'start', ''), /controlNotConfirmed/)
  assert.equal(polls.length, 0, 'a missing task never starts speculative probes')
  clock = 0; readError = new Error('unavailable')
  await assert.rejects(helper.waitForVmControlTask(100, 'start', 'task'), /controlNotConfirmed/)
  assert.equal(polls.length, 3, 'repeated read failures do not report success')
  console.log('PASS VM control UI: accepted/pending/completed, all actions, duplicate guard and task failure')
})().catch(error => { console.error(error); process.exitCode = 1 })
