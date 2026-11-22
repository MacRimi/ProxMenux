const assert=require('node:assert/strict')
const fs=require('node:fs'),path=require('node:path')
const {loadTypeScript}=require('./ts-fixture.cjs')
async function withApiCatalog(language,values,run){
 const original=fs.readFileSync,target=path.resolve(__dirname,'../AppImage/messages',language,'common.json')
 fs.readFileSync=function(file,...args){
  const content=original.call(this,file,...args)
  if(typeof file==='string'&&path.resolve(file)===target){
   const catalog=JSON.parse(content);catalog.apiErrors=values;return JSON.stringify(catalog)
  }
  return content
 }
 try{return await run()}finally{fs.readFileSync=original}
}
function fixture(language='sk',token='fixture-token'){
 const local=new Map(token?[['proxmenux-auth-token',token]]:[]),session=new Map(),calls=[];let reloads=0,reply=()=>new Response('{}',{headers:{'Content-Type':'application/json'}})
 const storage=map=>({getItem:key=>map.get(key)||null,setItem:(key,v)=>map.set(key,v),removeItem:key=>map.delete(key)})
 const win={localStorage:storage(local),location:{protocol:'https:',hostname:'fixture.invalid',port:'',reload:()=>reloads++}}
 const globals={window:win,document:{documentElement:{lang:language}},localStorage:win.localStorage,sessionStorage:storage(session),console:{error(){}},fetch:async(url,options)=>{calls.push({url,options});return reply()}}
 const {fetchApi}=loadTypeScript('lib/api-config.ts',globals)
 return{fetchApi,calls,reply:value=>reply=value,globals,local,reloads:()=>reloads}
}
async function main(){
 // Future translations must work without another language-specific code branch.
 for(const language of ['de','es','fr','it','pt','sv']){
  await withApiCatalog(language,{http:language+' HTTP {status} {statusText}',unknownContentType:language+' TYPE'},async()=>{
   const f=fixture(language)
   f.reply(()=>new Response('html',{status:502,statusText:'Bad Gateway'}))
   await assert.rejects(f.fetchApi('/api/demo'),e=>e.message===language+' HTTP 502 Bad Gateway')
   // A partial catalog falls back per key, preserving the original endpoint.
   f.reply(()=>new Response('{',{headers:{'Content-Type':'application/json'}}))
   await assert.rejects(f.fetchApi('/api/demo'),e=>e.message==='Invalid JSON response from /api/demo')
   assert.equal(f.calls.length,2,'Localization never retries or makes its own request')
  })
 }
 await withApiCatalog('fr',{http:{invalid:'not a message'},invalidJson:'FR {endpoint}'},async()=>{
  const f=fixture('fr');f.reply(()=>new Response('',{status:503,statusText:'Unavailable'}))
  await assert.rejects(f.fetchApi('/api/demo'),e=>e.message==='API request failed: 503 Unavailable')
  const browser=loadTypeScript('lib/api-errors.ts',{navigator:{language:'fr-FR',languages:['sk']}})
  assert.equal(browser.apiFailure('invalidJson',{endpoint:'/literal?x=<a>&y=1'}),'FR /literal?x=<a>&y=1')
  const document={documentElement:{lang:'sk'}};let storedReads=0
  const current=loadTypeScript('lib/api-errors.ts',{document,window:{localStorage:{getItem:()=>{storedReads++;return 'sk'}}}})
  assert.equal(current.apiFailure('invalidJson',{endpoint:'/api/demo'}),'Odpoveď z /api/demo obsahuje neplatný JSON')
  document.documentElement.lang='fr'
  assert.equal(current.apiFailure('invalidJson',{endpoint:'/api/demo'}),'FR /api/demo','The next error follows a language switch without reloading')
  assert.equal(storedReads,0,'The provider document language takes precedence')
  document.documentElement.lang='unsupported'
  assert.equal(current.apiFailure('unknownContentType'),'neznámy typ obsahu')
  assert.equal(storedReads,1,'An invalid document language uses a supported stored preference')
  const denied=loadTypeScript('lib/api-errors.ts',{window:{get localStorage(){throw new Error('denied')}},navigator:{language:'fr-FR',languages:[]}})
  assert.equal(denied.apiFailure('invalidJson',{endpoint:'/api/demo'}),'FR /api/demo')
 })
 // Translated locales use their catalog; per-key English fallback is covered above.
 for(const lang of ['sk','en']){
  const f=fixture(lang),sk=lang==='sk'
  f.reply(()=>new Response('html',{status:502,statusText:'Bad Gateway',headers:{'Content-Type':'text/html'}}))
  await assert.rejects(f.fetchApi('/api/demo'),e=>e.message===(sk?'Požiadavka na API zlyhala: 502 Bad Gateway':'API request failed: 502 Bad Gateway'))
  f.reply(()=>new Response('<html>',{headers:{'Content-Type':'text/html'}}))
  await assert.rejects(f.fetchApi('/api/demo'),e=>e.message===(sk?'Očakávala sa odpoveď JSON, ale prišiel typ text/html':'Expected JSON response but got text/html'))
  f.reply(()=>new Response('{',{headers:{'Content-Type':'application/json'}}))
  await assert.rejects(f.fetchApi('/api/demo'),e=>e.message===(sk?'Odpoveď z /api/demo obsahuje neplatný JSON':'Invalid JSON response from /api/demo'))
  f.reply(()=>({ok:true,headers:{get:()=>null},text:async()=>''}))
  await assert.rejects(f.fetchApi('/api/demo'),e=>e.message.includes(sk?'neznámy typ obsahu':'unknown content type'))
  const detail={error:'Original technical detail <raw>&',details:{keep:1},suggestion:'Keep diagnostics'}
  f.reply(()=>new Response(JSON.stringify(detail),{status:400,headers:{'Content-Type':'application/json'}}))
  await assert.rejects(f.fetchApi('/api/demo',{method:'POST',body:'fixture'}),e=>{assert.equal(e.message,detail.error);assert.equal(e.status,400);assert.deepEqual(e.body,detail);return true})
  f.reply(()=>new Response('{',{status:400,statusText:'Bad Request',headers:{'Content-Type':'application/json'}}))
  await assert.rejects(f.fetchApi('/api/demo'),e=>e.message.includes('400 Bad Request'))
  const result={ok:true,items:[1,2],empty:null};f.reply(()=>new Response(JSON.stringify(result),{headers:{'Content-Type':'application/json'}}))
  assert.deepEqual(await f.fetchApi('/api/demo',{method:'PUT',body:'unchanged',headers:{'X-Fixture':'keep'}}),result)
  const call=f.calls.at(-1);assert.equal(call.url,'/api/demo');assert.equal(call.options.method,'PUT');assert.equal(call.options.body,'unchanged');assert.equal(call.options.headers.Authorization,'Bearer fixture-token');assert.equal(call.options.headers['X-Fixture'],'keep');assert.equal(call.options.cache,'no-store')
  assert.equal(f.calls.length,7,'Each request calls fetch exactly once, no retries or side calls')
  const network=new Error('Original network diagnostic');f.reply(()=>{throw network});await assert.rejects(f.fetchApi('/api/demo'),e=>e===network)
  assert.equal(f.calls.length,8);assert.equal(f.reloads(),0)
 }
 for(const token of ['', 'fixture-token']){
  const f=fixture('sk',token);f.reply(()=>new Response('',{status:401}))
  await assert.rejects(f.fetchApi('/api/demo'),/Chýba platné prihlásenie/)
  assert.equal(f.local.has('proxmenux-auth-token'),false);assert.equal(f.reloads(),token?1:0)
  await assert.rejects(f.fetchApi('/api/demo'),/Chýba platné prihlásenie/);assert.equal(f.reloads(),token?1:0)
  assert.equal(f.calls.length,2)
 }
 const privateMode=loadTypeScript('lib/api-errors.ts',{document:{documentElement:{lang:'sk'}},window:{get localStorage(){throw new Error('denied')}}})
 assert.equal(privateMode.apiFailure('invalidJson',{endpoint:'/api/demo'}),'Odpoveď z /api/demo obsahuje neplatný JSON')
 const stored=loadTypeScript('lib/api-errors.ts',{window:{localStorage:{getItem:()=> 'sk'}}})
 assert.equal(stored.apiFailure('unknownContentType'),'neznámy typ obsahu')
 // Existing consumer paths, with their actual imports bound to real fetchApi.
 const helper=fixture();Object.assign(helper.globals,{AbortSignal,setTimeout:fn=>{fn();return 1}})
 const control=loadTypeScript('lib/vm-control.ts',helper.globals)
 helper.reply(()=>new Response(JSON.stringify({status:'stopped',exitstatus:'OK',guest_status:'running'}),{headers:{'Content-Type':'application/json'}}))
 await control.waitForVmControlTask(999,'reboot','UPID:fixture');assert.ok(helper.calls.at(-1).url.includes('/control-task/UPID%3Afixture'))
 const archive=loadTypeScript('lib/guest-backup-archives.ts',helper.globals),backup={volid:'store:fixture',storage:'store'}
 helper.reply(()=>new Response(JSON.stringify({results:[{volid:backup.volid,status:'deleted'}]}),{headers:{'Content-Type':'application/json'}}))
 assert.equal((await archive.deleteGuestBackups(999,[backup]))[0].status,'deleted')
 const deletion=helper.calls.at(-1);assert.equal(deletion.options.method,'POST');assert.equal(JSON.parse(deletion.options.body).confirm,true)
 helper.reply(()=>new Response('fixture',{status:500,statusText:'Fixture'}));const count=helper.calls.length
 await assert.rejects(archive.deleteGuestBackups(999,[backup]),/Požiadavka na API zlyhala/);assert.equal(helper.calls.length,count+1,'No retry of delete after a lost response')
 const updates=loadTypeScript('lib/lxc-update-observation.ts',helper.globals)
 helper.reply(()=>new Response(JSON.stringify({count:2,available:true}),{headers:{'Content-Type':'application/json'}}))
 assert.equal((await updates.checkLxcUpdates(999)).count,2);assert.equal(helper.calls.at(-1).url,'/api/vms/999/updates/check')
 helper.reply(()=>new Response(JSON.stringify(helper.calls.at(-1).options.method==='POST'?{job_id:'fixture'}:{state:'complete',update_check:{count:0}}),{headers:{'Content-Type':'application/json'}}))
 assert.equal((await updates.refreshCheckLxcUpdates(999)).count,0)
 const terminal=loadTypeScript('lib/terminal-ws.ts',helper.globals)
 helper.reply(()=>new Response('fixture',{status:500}));assert.equal(await terminal.getTicketedWsUrl('wss://fixture.invalid/ws'),'wss://fixture.invalid/ws')
 assert.equal(helper.calls.at(-1).url,'/api/terminal/ticket')
 console.log('PASS actual fetchApi: EN/SK/fallback, HTTP/type/JSON/401, backend detail/body/status, original requests and success; no extra fetch/retry/mutation')
}
main().catch(error=>{console.error(error);process.exitCode=1})
