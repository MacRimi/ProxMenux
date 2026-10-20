// Execute the real WebSocket handlers and the OCI caller's actual close callback.
const assert = require('node:assert/strict'), vm = require('node:vm');
const {ts,read,compile,translator,catalogs} = require('./backup_i18n_seam.cjs');
const moduleScope = {exports:{}};
vm.runInNewContext(compile(read('lib/script-completion.ts')), moduleScope);
const completion = moduleScope.exports;
const source = ts.createSourceFile('modal.tsx', read('components/script-terminal-modal.tsx'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const handlers = []; let messageCallback,reconnectCallback;
function walk(node) {
  if (ts.isBinaryExpression(node) && node.left.getText(source) === 'ws.onmessage') handlers.push(node.right);
  if (ts.isVariableDeclaration(node) && node.name.getText(source) === 'getCompletionMessage') messageCallback = node.initializer.arguments[0];
  if (ts.isVariableDeclaration(node) && node.name.getText(source) === 'attemptReconnect') reconnectCallback = node.initializer.arguments[0];
  ts.forEachChild(node, walk);
}
walk(source);
assert.equal(handlers.length,2,'initial and reconnect handlers');
assert.ok(messageCallback);
function executable(node, file, scope) {
  const local = {...scope,exports:{}};
  vm.runInNewContext(compile('exports.fn = '+node.getText(file)+';'),local);
  return local.exports.fn;
}
function fixture(handler, locale, optedIn=true) {
  const writes=[], callbacks=[], state={closed:0};
  const t=translator(locale), terminal={write:s=>writes.push(s),writeln:s=>writes.push(s)};
  const shared={...completion, cancelledExitCode:optedIn?6:undefined,t,
    completedSuccessfullyMessage:undefined,completedWithErrorMessage:undefined};
  const getCompletionMessage=executable(messageCallback,source,shared);
  const scope={...shared,getCompletionMessage,term:terminal,termRef:{current:terminal},
    completionReceivedRef:{current:false},onCompleteRef:{current:code=>callbacks.push(code)},
    setIsComplete:v=>state.complete=v,ws:{readyState:1,close:()=>state.closed++},WebSocket:{OPEN:1},
    setIsWaitingNextInteraction:()=>{},waitingTimeoutRef:{current:null},clearTimeout:()=>{},
    setCurrentInteraction:()=>{}};
  return {receive:executable(handler,source,scope),writes,callbacks,state,t,scope};
}
let scenarios=0;
for (const handler of handlers) for (const locale of ['en','sk']) for (const frame of ['raw','json']) {
  for (const [code,optedIn,kind] of [[6,true,'cancelled'],[6,false,'error'],[1,true,'error'],[0,true,'success'],[-1,true,'error']]) {
    const f=fixture(handler,locale,optedIn);
    const data=frame==='raw'?`\r\n[Script exited with code ${code}]\r\n`:JSON.stringify({type:'script_complete',exit_code:code});
    f.receive({data});
    assert.deepEqual(f.callbacks,[code]); assert.equal(f.state.closed,1);
    const rendered=f.writes.join('');
    if(kind==='cancelled') {
      assert.ok(rendered.includes(f.t('scriptTerminal.cancelled')));
      assert.ok(rendered.includes('\x1b[36m'));
      assert.ok(rendered.startsWith('\x1bc'),'cancel resets the obsolete dialog in the queued output');
      assert.ok(!rendered.includes('Script exited with code'));
      assert.ok(!rendered.includes('\x1b[31m'));
      assert.ok(!rendered.includes(f.t('scriptTerminal.completedSuccessfully')));
    } else {
      assert.ok(!rendered.includes('\x1bc'),'success/errors and non-opted-in scripts keep their logs');
      assert.ok(rendered.includes(kind==='success'?f.t('scriptTerminal.completedSuccessfully'):f.t('scriptTerminal.completedWithError',{code})));
    }
    // Worker sends both forms; neither a second frame nor a heartbeat may complete twice.
    f.receive({data:JSON.stringify({type:'script_complete',exit_code:code})});
    f.receive({data:'{"type":"pong"}'});
    assert.deepEqual(f.callbacks,[code]);assert.equal(f.state.closed,1);scenarios++;
  }
  for(const payload of [{type:'script_complete'},{type:'script_complete',exit_code:'invalid'}]) {
    const f=fixture(handler,locale);f.receive({data:JSON.stringify(payload)});
    assert.ok(f.writes.join('').includes('\x1b[31m'));
    assert.ok(!f.writes.join('').includes(f.t('scriptTerminal.cancelled')));scenarios++;
  }
}
for(const locale of Object.keys(catalogs)) assert.ok(translator(locale)('scriptTerminal.cancelled')!=='scriptTerminal.cancelled');
// The native CLI and the explicitly opted-in caller share the documented code6 contract.
const fs=require('node:fs');
assert.match(fs.readFileSync('oci/src/proxmenux_oci/management.py','utf8'),/^EXIT_CANCELLED = 6 /m);
assert.equal(completion.OCI_CANCELLED_EXIT_CODE,6);
const parent=ts.createSourceFile('vms.tsx',read('components/virtual-machines.tsx'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
let ociElement,reset,pendingRecoveryClick;
function find(node) {
  if(ts.isJsxSelfClosingElement(node) && node.tagName.getText(parent)==='ScriptTerminalModal' &&
      node.attributes.properties.some(p=>p.name?.getText(parent)==='scriptPath' && p.initializer?.text?.endsWith('/oci/manage_instance.sh'))) ociElement=node;
  if(ts.isCallExpression(node) && node.expression.getText(parent)==='useEffect' && node.arguments[0]?.getText(parent).includes('ociCompletionCodeRef.current = undefined')) reset=node.arguments[0];
  if(ts.isJsxElement(node) && node.openingElement.tagName.getText(parent)==='Button') {
    const click=node.openingElement.attributes.properties.find(p=>p.name?.getText(parent)==='onClick')?.initializer?.expression;
    if(click?.getText(parent).includes('setOciAction(') && click.getText(parent).includes('action: "update"')) pendingRecoveryClick=click;
  }
  ts.forEachChild(node,find);
}
find(parent);assert.ok(ociElement);assert.ok(reset);assert.ok(pendingRecoveryClick);
const attribute=name=>ociElement.attributes.properties.find(p=>p.name?.getText(parent)===name)?.initializer?.expression;
assert.equal(attribute('cancelledExitCode').getText(parent),'OCI_CANCELLED_EXIT_CODE');
(async()=>{
 for(const locale of ['en','sk']) for(const pending of [false,true]) {
  const scope={t:translator(locale), selectedVM:{vmid:110}, ociInstance:{pending},
    applyBackup:false,applyBackupStorage:'',selectedBackupStorage:''};
  scope.setOciAction=value=>scope.ociAction=value;
  executable(pendingRecoveryClick,parent,scope)();
  assert.equal(scope.ociAction.vmid,110);
  assert.equal(scope.ociAction.action,'update','pending recovery retains the existing manage contract');
  // Background refresh or another selected guest must not rename this open operation.
  scope.ociInstance={pending:!pending};scope.selectedVM={vmid:999};
  const title=executable(attribute('title'),parent,scope);
  assert.equal(title,scope.t(pending?'vmLxc.ociUpdates.terminalTitleRecoverPrevious':'vmLxc.ociUpdates.terminalTitleUpdate'));
  assert.equal(title,pending?(locale==='sk'?'Obnoviť predchádzajúcu OCI inštaláciu':'Recover the previous OCI installation'):
    (locale==='sk'?'Aktualizovať OCI aplikáciu':'Update OCI application'));
  const params=executable(attribute('params'),parent,scope);
  assert.equal(params.ACTION,'update');assert.equal(params.VMID,'110');
  assert.equal(params.KEEP_BACKUP,'');
 }
 for(const action of ['modify','recover']) {
  const scope={t:translator('sk'),ociAction:{vmid:110,action,recoverPrevious:true}};
  assert.equal(executable(attribute('title'),parent,scope),scope.t(action==='recover'?
    'vmLxc.ociUpdates.terminalTitleRecover':'vmLxc.ociUpdates.terminalTitleModify'),
    'registration and editing retain their own titles');
 }
 for(const frame of ['raw','json']) {
  const f=fixture(handlers[0],'sk'),timers=[];
  const old={readyState:3,onclose:()=>f.callbacks.push(-1),onerror:()=>{},onmessage:()=>{},close(){this.onclose?.({})}};
  const ref={current:old};
  class Socket{static OPEN=1;constructor(){this.readyState=1}close(){this.onclose?.({})}}
  const scope={...f.scope,isOpen:true,isComplete:false,reconnectAttemptsRef:{current:0},reconnectTimeoutRef:{current:null},
    wsRef:ref,WebSocket:Socket,sessionIdRef:{current:'fixture'},paramsRef:{current:{}},keepAliveIntervalRef:{current:null},
    scriptPath:'/fixture/oci',setConnectionStatus:()=>{},getScriptWebSocketUrl:()=> 'ws://fixture',getTicketedWsUrl:async url=>url,
    setTimeout:fn=>{timers.push(fn);return 1},clearTimeout:()=>{}};
  executable(reconnectCallback,source,scope)();await timers[0]();
  assert.equal(old.onclose,null,'replaced connection cannot emit an unknown result');
  assert.equal(old.onmessage,null,'late result from replaced connection cannot win');
  ref.current.onmessage({data:frame==='raw'?'\r\n[Script exited with code 6]\r\n':JSON.stringify({type:'script_complete',exit_code:6})});
  assert.deepEqual(f.callbacks,[6]);
 }
 for(const action of ['update','modify']) for(const code of [6,0,1,undefined]) {
  const calls=[],row={vmid:110,action},saved=JSON.stringify(row),ref={current:undefined};
  const scope={...completion,ociAction:row,ociCompletionCodeRef:ref,
    setOciAction:value=>calls.push(['close',value]),fetchApi:(url,options)=>{calls.push(['fetch',url,options]);return Promise.resolve({});},
    invalidateLxcApps:vmid=>calls.push(['invalidate',vmid]),vmModalCacheRef:{current:{mountPoints:new Map()}},
    fetchOciInstance:vmid=>calls.push(['instance',vmid]),fetchMountPoints:vmid=>calls.push(['mounts',vmid]),mutate:()=>calls.push(['mutate'])};
  executable(attribute('onComplete'),parent,scope)(code);
  executable(attribute('onClose'),parent,scope)();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(JSON.stringify(row),saved);
  if(code===6) assert.deepEqual(calls,[['close',null]],'cancel has zero registry/API/cache calls');
  else assert.equal(calls.filter(c=>c[0]==='fetch'&&c[2].method==='POST').length,1,'preserve refresh after non-cancel');
  executable(reset,parent,scope)();assert.equal(ref.current,undefined,'next modal cannot inherit cancellation');
 }
 console.log(`PASS: ${scenarios} real terminal frame scenarios; actual OCI close callbacks, code6 scoping, reset and zero cancel probes`);
})().catch(error=>{console.error(error);process.exitCode=1});
