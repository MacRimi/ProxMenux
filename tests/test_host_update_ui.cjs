// Execute actual transport initializers, reconnect handlers and routing.
const assert = require('node:assert/strict')
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm')
const app = path.resolve(__dirname, '../AppImage')
const ts = require(path.join(app, 'node_modules/typescript'))
const text = fs.readFileSync(path.join(app, 'components/script-terminal-modal.tsx'), 'utf8')
const tree = ts.createSourceFile('modal.tsx', text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
const opens = [], messages = [], closes = []
let route, cleanup
function walk(n) {
  if (ts.isBinaryExpression(n) && n.left.getText(tree) === 'ws.onopen') opens.push(n.right.getText(tree))
  if (ts.isBinaryExpression(n) && n.left.getText(tree) === 'ws.onmessage') messages.push(n.right.getText(tree))
  if (ts.isBinaryExpression(n) && n.left.getText(tree) === 'ws.onclose') closes.push(n.right.getText(tree))
  if (ts.isVariableDeclaration(n) && n.name.getText(tree) === 'getScriptWebSocketUrl') route = n.initializer.getText(tree)
  if (ts.isCallExpression(n) && n.expression.getText(tree) === 'useEffect'
    && n.arguments[0]?.getText(tree).includes('Transport mode is fixed')) cleanup = n.arguments[0].getText(tree)
  ts.forEachChild(n, walk)
}
walk(tree)
const compile = (code, scope) => vm.runInNewContext(ts.transpileModule('('+code+')', {
  compilerOptions:{target:ts.ScriptTarget.ES2020,module:ts.ModuleKind.CommonJS},
}).outputText, scope)
assert.equal(opens.length, 2)
for (const [index, open] of opens.entries()) {
  for (const resume of [false, true]) {
    const sent = [], scope = {backgroundUpdate:{runId:'same-id',kind:'host',resume},
      scriptPath:'/forbidden-client-path', paramsRef:{current:{FORBIDDEN:'client-env'}},
      outputOffsetRef:{current:42}, setConnectionStatus(){}, reconnectAttemptsRef:{current:0},
      keepAliveIntervalRef:{current:null}, clearInterval(){}, setInterval(){return 1}, setTimeout(){},
      WebSocket:{OPEN:1}, ws:{readyState:1,send:s=>sent.push(JSON.parse(s))}}
    compile(open, scope)()
    assert.equal(sent.length,1)
    assert.deepEqual(sent[0],{resume:index===0 ? true : resume, offset:42},
      'reconnect must attach; explicit initial start is the sole resume=false message')
  }
}
for (const backgroundUpdate of [{runId:'same-id',kind:'host'}, {runId:'lxc-id',vmid:101}, undefined]) {
  const actual = compile(route,{backgroundUpdate,API_PORT:'8008'})('legacy-id')
  assert.equal(actual,'ws://localhost:8008/ws/'+(backgroundUpdate?.kind==='host'?'host-update/same-id':backgroundUpdate?'lxc-update/lxc-id':'script/legacy-id'))
}
for (const close of closes) {
  const sent=[], results=[], scope={backgroundUpdate:{runId:'same-id',kind:'host'},
    ws:{send:s=>sent.push(s)}, isOpenRef:{current:true}, isComplete:false,
    completionReceivedRef:{current:false}, keepAliveIntervalRef:{current:null},
    reconnectAttemptsRef:{current:0},reconnectTimeoutRef:{current:null},setTimeout(fn){fn();return 1},clearTimeout(){},
    setConnectionStatus(){}, clearInterval(){}, termRef:{current:{writeln(){}}},term:{writeln(){}},
    attemptReconnect(){results.push('attach')}, onCompleteRef:{current:()=>results.push('complete')},t:s=>s}
  compile(close,scope)({})
  assert.deepEqual(results,['attach'])
  assert.deepEqual(sent,[])
}
const sent=[], scope={backgroundUpdate:{runId:'same-id',kind:'host'},
  openGenerationRef:{current:0}, isOpenRef:{current:true}, wsRef:{current:{close(){},send:x=>sent.push(x)}},
  termRef:{current:{dispose(){}}}, clearTimeout(){},clearInterval(){},
  waitingTimeoutRef:{current:null}, reconnectTimeoutRef:{current:null}, keepAliveIntervalRef:{current:null},checkConnectionInterval:{current:null}}
compile(cleanup,scope)()()
assert.deepEqual(sent,[],'unmount cannot send cancellation or restart')
const health=fs.readFileSync(path.join(app,'components/health-status-modal.tsx'),'utf8')
const en=JSON.parse(fs.readFileSync(path.join(app,'messages/en/common.json'),'utf8'))
const sk=JSON.parse(fs.readFileSync(path.join(app,'messages/sk/common.json'),'utf8'))
assert.deepEqual(Object.keys(en.healthStatus.hostUpdate).sort(),Object.keys(sk.healthStatus.hostUpdate).sort())
assert.ok(health.includes('Number(categoryData?.count ?? 0) > 0'),'reboot-only state has no Update Now action')
console.log('PASS host initial/resume transport, legacy/LXC routes, disconnect/unmount and EN/SK keys')
