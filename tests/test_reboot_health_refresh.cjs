// Execute actual TS callbacks/effects with controlled transport and clocks.
const assert = require('node:assert/strict')
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm')
const app = path.resolve(__dirname, '../AppImage')
const ts = require(path.join(app, 'node_modules/typescript'))
function source(file, name, effectText) {
  const tree = ts.createSourceFile(file, fs.readFileSync(path.join(app, 'components', file), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  let callback, effect
  function walk(n) {
    if (ts.isVariableDeclaration(n) && n.name.getText(tree) === name) callback = n.initializer.arguments[0].getText(tree)
    if (ts.isCallExpression(n) && n.expression.getText(tree) === 'useEffect' && n.arguments[0].getText(tree).includes(effectText)) effect = n.arguments[0].getText(tree)
    ts.forEachChild(n, walk)
  }
  walk(tree)
  assert.ok(callback && effect)
  return {callback, effect}
}
const modal = source('health-status-modal.tsx', 'fetchHealthDetails', 'Recheck reboot evidence')
const header = source('proxmox-dashboard.tsx', 'fetchHealthInfoCount', 'Header reboot information')
const compile = (code, scope) => vm.runInNewContext(ts.transpileModule('('+code+')', {compilerOptions:{target:ts.ScriptTarget.ES2020}}).outputText, scope)
function environment() {
  const calls = [], data = [], errors = [], counts = [], events = [], availability = [], timers = new Map(), listeners = new Map()
  let timerId = 0
  const categories = [{key:'updates', category:'updates'}]
  const scope = {AbortController, CustomEvent:class {constructor(type, values){this.type=type;this.detail=values.detail}},
    healthRequest:{current:null}, getAuthToken:()=>null, getApiUrl:p=>p, t:s=>s,
    CATEGORIES:categories, HEALTH_CATEGORY_KEYS:categories,
    setHealthData:v=>data.push(v), setDismissedItems(){}, setCustomSuppressions(){},
    setLoading(){}, setError:v=>errors.push(v), setInfoCount:v=>counts.push(v),
    setSnapshotUnavailable:v=>availability.push(v),
    setTimeout(fn, delay){timers.set(++timerId,{fn,delay});return timerId}, clearTimeout:id=>timers.delete(id),
    window:{dispatchEvent:e=>events.push(e)},
    fetch:async(p, opts)=>{calls.push({p,opts});return {ok:true,json:async()=>payload('INFO')}},
    fetchApi:async(p, opts)=>{calls.push({p,opts});return payload('INFO')}}
  return {scope,calls,data,errors,counts,events,availability,timers,listeners}
}
function payload(status='OK') {return {health:{overall:'OK',timestamp:'original',details:{updates:{status,count:0}}},dismissed:[],custom_suppressions:[]}}
async function callbacks() {
  for (const [item, args] of [[modal,[false,true]],[header,[true]]]) {
    const env=environment(), run=compile(item.callback,env.scope)
    await run(...args)
    assert.equal(env.calls[0].p,'/api/health/full?cached=1')
    assert.equal(env.scope.healthRequest.current,null)
    assert.equal(env.timers.size,0)
    assert.deepEqual(item===modal ? env.events[0].detail.infoCount : env.counts[0],1)
  }
  const env=environment(), run=compile(modal.callback,env.scope)
  const pending=environment(), poll=compile(modal.callback,pending.scope)
  pending.scope.fetch=async(p)=>{pending.calls.push({p});return {ok:false,status:503}}
  await poll(false,true)
  assert.deepEqual(pending.availability,[true],'expected cache gap is explicitly unavailable, not a red failure or healthy result')
  assert.equal(pending.errors.filter(Boolean).length,0)
  assert.equal(pending.data.length,0,'cache gap cannot erase or replace the last known data')
  assert.deepEqual(pending.calls.map(x=>x.p),['/api/health/full?cached=1'],'no full/legacy fallback on cache miss')
  pending.scope.fetch=async()=>({ok:true,json:async()=>payload('INFO')})
  await poll(false,true)
  assert.deepEqual(pending.availability,[true,false],'a real successful response clears the unavailable notice')
  assert.equal(pending.data.length,1)
  for(const status of [401,500]){
    const failed=environment()
    failed.scope.fetch=async()=>({ok:false,status})
    await compile(modal.callback,failed.scope)(false,true)
    assert.ok(failed.errors.filter(Boolean).length,'auth and server failures remain errors')
    assert.equal(failed.data.length,0)
    assert.ok(!failed.availability.includes(true),'real failures are not relabelled as a cache gap')
  }
  env.scope.fetch=async(p)=>{env.calls.push({p});return {ok:false}}
  await run(false,true)
  assert.deepEqual(env.calls.map(x=>x.p),['/api/health/full?cached=1'])
  assert.equal(env.data.length,0)
  assert.ok(env.errors.includes('healthStatus.errors.fetchFailed'))
  const malformed=environment()
  malformed.scope.fetch=async()=>({ok:true,json:async()=>({})})
  await compile(modal.callback,malformed.scope)(false,true)
  assert.equal(malformed.data.length,0)
  assert.ok(malformed.errors.includes('healthStatus.errors.fetchFailed'))
  const h=environment()
  h.scope.fetchApi=async()=>({})
  await compile(header.callback,h.scope)(true)
  assert.equal(h.counts.length,0,'malformed data must not replace the previous count with zero')
}
async function races() {
  for (const [item, args, forceArgs] of [[modal,[false,true],[true]],[header,[true],[]]]) {
    const e=environment(), pending=[]
    if(item===modal) e.scope.fetch=(p,opts)=>{e.calls.push({p,opts});return new Promise(resolve=>pending.push(resolve))}
    else e.scope.fetchApi=(p,opts)=>{e.calls.push({p,opts});return new Promise(resolve=>pending.push(resolve))}
    const run=compile(item.callback,e.scope), first=run(...args)
    await run(...args)
    assert.equal(e.calls.length,1,'overlapping polls are coalesced')
    const second=run(...forceArgs)
    assert.ok(e.calls[0].opts.signal.aborted,'explicit refresh supersedes old poll')
    pending[1](item===modal ? {ok:true,json:async()=>payload('INFO')} : payload('INFO'))
    await second
    pending[0](item===modal ? {ok:true,json:async()=>payload('OK')} : payload('OK'))
    await first
    assert.equal(item===modal ? e.data.length : e.counts.length,1,'late response cannot overwrite new data')
    assert.equal(item===modal ? e.events[0].detail.infoCount : e.counts[0],1)
    assert.equal(e.timers.size,0)
  }
}
function effects(item, activeTab='overview') {
  const e=environment(), intervals=new Map(), listeners=new Map(), polls=[]
  let timerId=0
  e.scope.open=true; e.scope.activeTab=activeTab
  e.scope.fetchHealthDetails=(...args)=>polls.push(args)
  e.scope.fetchHealthInfoCount=(...args)=>polls.push(args)
  e.scope.fetchSystemData=()=>{}; e.scope.fetchUpdateStatus=()=>{}
  e.scope.setInterval=(fn,delay)=>{intervals.set(++timerId,{fn,delay});return timerId}
  e.scope.clearInterval=id=>intervals.delete(id)
  const target = name=>({addEventListener:(type,fn)=>listeners.set(name+type,fn),removeEventListener:(type,fn)=>{assert.equal(listeners.get(name+type),fn);listeners.delete(name+type)}})
  Object.assign(e.scope.window,target('window'))
  e.scope.document={visibilityState:'visible',...target('document')}
  const cleanup=compile(item.effect,e.scope)()
  const interval=[...intervals.values()].find(x=>x.delay===30000 && x.fn.toString().includes('fetchHealth'))
  assert.ok(interval,'every tab polls health at 30 seconds')
  assert.equal(polls.length,1,'initial full request retained')
  interval.fn(); listeners.get('windowfocus')(); listeners.get('documentvisibilitychange')()
  assert.equal(polls.length,4)
  for(const args of polls.slice(1))assert.deepEqual(args,item===modal?[false,true]:[true])
  e.scope.document.visibilityState='hidden'
  interval.fn();listeners.get('documentvisibilitychange')()
  assert.equal(polls.length,4,'hidden document does not poll')
  const controller=new AbortController();e.scope.healthRequest.current=controller
  cleanup()
  assert.ok(controller.signal.aborted)
  assert.equal(e.scope.healthRequest.current,null)
  assert.equal(intervals.size,0)
  assert.equal(listeners.size,0)
}
function expansion() {
  const text=fs.readFileSync(path.join(app,'components/health-status-modal.tsx'),'utf8')
  const tree=ts.createSourceFile('modal.tsx',text,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX)
  let code
  function walk(n) {
    if(ts.isCallExpression(n)&&n.expression.getText(tree)==='useEffect'&&n.arguments[0].getText(tree).includes('newlyDegraded'))code=n.arguments[0].getText(tree)
    ts.forEachChild(n,walk)
  }
  walk(tree);assert.ok(code)
  let expanded=new Set(['updates'])
  const scope={Set,CATEGORIES:[{key:'updates'},{key:'cpu'}],previousAutoExpanded:{current:new Set()},
    healthData:{details:{updates:{status:'INFO'},cpu:{status:'OK'}}},setExpandedCategories:fn=>{expanded=fn(expanded)}}
  const effect=compile(code,scope)
  effect();assert.ok(expanded.has('updates'),'poll must preserve manually opened updates')
  scope.healthData.details.cpu.status='WARNING';effect()
  assert.ok(expanded.has('cpu'),'new warnings may expand')
  expanded.delete('cpu');effect()
  assert.ok(!expanded.has('cpu'),'poll must preserve user collapsing a known warning')
}
async function main() {await callbacks();await races();effects(modal);effects(header);effects(header,'settings');expansion();console.log('PASS actual health callbacks: polling, focus, errors, no fallback, races, expansion and cleanup')}
main().catch(e=>{console.error(e);process.exitCode=1})
