// Execute the actual modal handlers and Updates recovery wiring.
const assert = require('node:assert/strict')
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm')
const {loadTypeScript} = require('./ts-fixture.cjs')
const root = path.resolve(__dirname, '../AppImage')
const ts = require(path.join(root, 'node_modules/typescript'))
const source = fs.readFileSync(path.join(root, 'components/script-terminal-modal.tsx'), 'utf8')
const tree = ts.createSourceFile('modal.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
const handlers = {onmessage: [], onclose: []}
let unmount
function walk(node) {
  if (ts.isBinaryExpression(node) && /^ws\.(onmessage|onclose)$/.test(node.left.getText(tree)))
    handlers[node.left.name.text].push(node.right.getText(tree))
  if (ts.isCallExpression(node) && node.expression.getText(tree) === 'useEffect'
    && node.arguments[0]?.getText(tree).includes('Transport mode is fixed'))
    unmount = node.arguments[0].getText(tree)
  ts.forEachChild(node, walk)
}
walk(tree)
assert.equal(handlers.onmessage.length, 2)
assert.equal(handlers.onclose.length, 2)
const completion = loadTypeScript('lib/script-completion.ts')
function fixture(backgroundUpdate) {
  const output = [], finished = [], reconnects = []
  const term = {write: s => output.push(s), writeln: s => output.push(s)}
  const ws = {readyState: 1, close() { this.readyState = 3 }}
  const context = {
    ...completion, backgroundUpdate, term, termRef: {current: term}, ws, WebSocket: {OPEN: 1},
    completionReceivedRef: {current: false}, outputOffsetRef: {current: 0},
    isOpenRef: {current: true}, isComplete: false, cancelledExitCode: 130,
    waitingTimeoutRef: {current: null}, keepAliveIntervalRef: {current: null},
    reconnectAttemptsRef: {current: 0}, reconnectTimeoutRef: {current: null},
    onCompleteRef: {current: code => finished.push(code)},
    setIsComplete: value => context.isComplete = value, setConnectionStatus() {},
    setIsWaitingNextInteraction: value => context.waiting = value,
    setCurrentInteraction: value => context.interaction = value, setInteractionInput() {},
    clearTimeout() {}, clearInterval() {}, setTimeout: fn => { fn(); return 1 },
    attemptReconnect: () => reconnects.push(true), t: key => key,
    getCompletionMessage: code => 'Result ' + code,
  }
  return {context, output, finished, reconnects, ws}
}
function compile(code, context) {
  return vm.runInNewContext(ts.transpileModule('(' + code + ')', {compilerOptions: {
    target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS,
  }}).outputText, context)
}
for (const handler of handlers.onmessage) {
  const f = fixture({runId: 'existing', vmid: 100, resume: true})
  const message = compile(handler, f.context)
  message({data: JSON.stringify({type: 'job_output', text: '[Script exited with code 0]', offset: 27})})
  assert.equal(f.finished.length, 0, 'text inside a job is never its authoritative result')
  assert.equal(f.context.outputOffsetRef.current, 27)
  message({data: JSON.stringify({type: 'web_interaction', interaction: {id:'pending', type:'yesno'}})})
  assert.equal(f.context.interaction.id, 'pending', 'replayed interaction remains answerable')
  f.context.waiting = true
  message({data: JSON.stringify({type: 'web_interaction', interaction: null})})
  assert.equal(f.context.interaction, null, 'answer in another viewer dismisses the stale question')
  assert.equal(f.context.waiting, false)
  f.context.waiting = true
  message({data: JSON.stringify({type: 'job_output', text: 'working', offset: 34})})
  assert.equal(f.context.waiting, false, 'ordinary progress clears the post-answer spinner')
  f.context.interaction = {id: 'stale'}; f.context.waiting = true
  message({data: JSON.stringify({type: 'script_complete', exit_code: 3})})
  assert.deepEqual(f.finished, [3])
  assert.equal(f.context.interaction, null, 'a completed job cannot retain an active question')
  assert.equal(f.context.waiting, false, 'a completed job cannot retain a processing overlay')
  message({data: JSON.stringify({type: 'script_complete', exit_code: 0})})
  assert.deepEqual(f.finished, [3], 'replayed completion cannot finalize twice')
  const missing = fixture({runId: 'missing'})
  compile(handler, missing.context)({data: JSON.stringify({type:'job_unavailable', message:'Unavailable; not restarted'})})
  assert.equal(missing.finished.length, 0, 'missing job is not success or a synthetic failure callback')
  const legacy = fixture(undefined)
  compile(handler, legacy.context)({data:'[Script exited with code 0]'})
  assert.deepEqual(legacy.finished, [0], 'legacy terminal exit fallback still works')
}
for (const handler of handlers.onclose) {
  const f = fixture({runId: 'existing'})
  compile(handler, f.context)({})
  assert.equal(f.finished.length, 0, 'losing a viewer never reports update failure')
  assert.equal(f.context.isComplete, false)
  assert.equal(f.reconnects.length, 1)
  const closed = fixture({runId:'existing'}); closed.context.isOpenRef.current = false
  compile(handler, closed.context)({})
  assert.equal(closed.reconnects.length, 0, 'closing the view cannot reopen a socket')
}
assert.ok(unmount)
for (const backgroundUpdate of [undefined, {runId:'existing'}]) {
  const f=fixture(backgroundUpdate), closes=[], sends=[], disposals=[]
  const ref={current:{close:()=>closes.push(true),send:()=>sends.push(true)}}
  Object.assign(f.context,{wsRef:ref,openGenerationRef:{current:1},
    checkConnectionInterval:{current:null},reconnectTimeoutRef:{current:null}})
  f.context.termRef.current.dispose=()=>disposals.push(true)
  compile(unmount,f.context)()()
  assert.equal(closes.length,backgroundUpdate?1:0)
  assert.equal(sends.length,0,'unmount cannot send cancellation or another start')
  assert.equal(f.finished.length,0)
  assert.equal(disposals.length,backgroundUpdate?1:0)
}
const vms=fs.readFileSync(path.join(root,'components/virtual-machines.tsx'),'utf8')
const vmTree=ts.createSourceFile('vms.tsx',vms,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX)
let complete
function visit(n){if(ts.isVariableDeclaration(n)&&n.name.getText(vmTree)==='handleApplyComplete')complete=n.initializer.getText(vmTree);ts.forEachChild(n,visit)}
visit(vmTree)
async function checkCompletion(){
 for(const selected of [100,200]){
  const posts=[],states=[],refresh=[]
  const context={applyVmid:100,applyStartedAt:Date.now(),selectedVM:{vmid:selected},selectedVMRef:{current:{vmid:selected}},
    applyRunId:'existing',applyTarget:'app',applyTargetIds:['app:test'],applyTargetLabels:['Test'],applyDockerRefresh:false,
    vmModalCacheRef:{current:{details:new Map(),schedule:new Map()}},fetchApi:async(...args)=>posts.push(args),
    fetchLxcApps:id=>refresh.push(id),mutate:()=>{},setUpdatesBaselineCount:v=>states.push(v),setUpdatesResult:v=>states.push(v),setUpdatesRefreshing:v=>states.push(v)}
  await compile(complete,context)(0,false)
  assert.equal(posts.length,0,'background completion never sends a second finalization POST')
  assert.deepEqual(refresh,[100])
  assert.equal(states.length,selected===100?3:0,'another guest result UI is preserved')
 }
}
const local = new Map(), events = []
const storage = {getItem:k=>local.get(k), setItem:(k,v)=>local.set(k,v)}
const jobs = loadTypeScript('lib/lxc-update-jobs.ts', {localStorage:storage,
  window:{dispatchEvent:e=>events.push(e)}, Event:class {constructor(type){this.type=type}}})
local.set('proxmenux-viewed-update-jobs', '{')
assert.equal(jobs.viewedUpdateJobs().length, 0)
jobs.markUpdateJobViewed('opaque-run'); jobs.markUpdateJobViewed('opaque-run')
assert.equal(jobs.viewedUpdateJobs().length, 1)
assert.equal(events.length, 2)
assert.equal([...local.values()].join(''), '["opaque-run"]', 'storage has IDs, no commands or credentials')
console.log('PASS actual initial/reconnect handlers, auth-independent recovery metadata and legacy completion')
checkCompletion().catch(e=>{console.error(e);process.exitCode=1})
