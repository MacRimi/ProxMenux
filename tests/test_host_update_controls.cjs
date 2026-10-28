// Execute the actual destructive-action callback using an inert transport.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm')
const app=path.resolve(__dirname,'../AppImage'),ts=require(path.join(app,'node_modules/typescript'))
const tree=ts.createSourceFile('controls.tsx',fs.readFileSync(path.join(app,'components/host-update-status.tsx'),'utf8'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX)
let callback
function walk(n){if(ts.isVariableDeclaration(n)&&n.name.getText(tree)==='confirm')callback=n.initializer.getText(tree);ts.forEachChild(n,walk)}
walk(tree);assert.ok(callback)
function fixture(){
 const calls=[],events=[]
 const scope={AbortController,JSON,Error,disabled:false,context:{allowed:true,hostname:'fixture-host',boot_id:'fixture-boot'},submitted:false,
  sending:{current:false},alive:{current:true},postRequest:{current:null},getApiUrl:p=>p,headers:()=>({}),
  setSubmitted:v=>events.push(['submitted',v]),setPending:v=>events.push(['pending',v]),setError:v=>events.push(['error',v]),
  setAccepted:v=>events.push(['accepted',v]),setOpen:v=>events.push(['open',v]),
  setTimeout:()=>1,clearTimeout(){},fetch:async(p,options)=>{calls.push({p,options});return {status:202,json:async()=>({accepted:true})}}}
 const run=vm.runInNewContext(ts.transpileModule('('+callback+')',{compilerOptions:{target:ts.ScriptTarget.ES2020}}).outputText,scope)
 return {scope,calls,events,run}
}
async function main(){
 for(const block of ['disabled','submitted','sending','missing-context','not-allowed']){
  const x=fixture()
  if(block==='sending')x.scope.sending.current=true
  else if(block==='missing-context')x.scope.context=null
  else if(block==='not-allowed')x.scope.context.allowed=false
  else x.scope[block]=true
  await x.run();assert.equal(x.calls.length,0);assert.equal(x.events.length,0)
 }
 const x=fixture();await x.run();await x.run()
 assert.equal(x.calls.length,1,'duplicate confirm never sends a second request')
 assert.equal(x.calls[0].p,'/api/health/reboot-after-update')
 assert.equal(x.calls[0].options.method,'POST')
 assert.deepEqual(JSON.parse(x.calls[0].options.body),{confirm:true,hostname:'fixture-host',boot_id:'fixture-boot'})
 assert.ok(x.events.some(e=>e[0]==='accepted'&&e[1]===true))
 assert.equal(x.scope.postRequest.current,null)
 for(const response of [{status:409},{status:202,json:async()=>({accepted:false})}]){
  const e=fixture();e.scope.fetch=async()=>response;await e.run()
  assert.ok(e.events.some(v=>v[0]==='error'&&v[1]===true))
  assert.ok(!e.events.some(v=>v[0]==='accepted'))
 }
 const e=fixture();e.scope.fetch=async()=>{throw Error('unknown outcome')};await e.run()
 assert.ok(!e.events.some(v=>v[0]==='accepted'))
 assert.ok(e.scope.sending.current,'unknown outcome is not automatically retried')
 console.log('PASS actual confirmation guards, exact payload, duplicate suppression and unknown outcomes')
}
main().catch(e=>{console.error(e);process.exitCode=1})
