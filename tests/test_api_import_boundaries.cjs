const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm')
const root=path.resolve(__dirname,'..'),ts=require(root+'/AppImage/node_modules/typescript')
const code=ts.transpileModule(fs.readFileSync(root+'/AppImage/lib/api-config.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText
async function main(){
 let calls=0,reply=()=>new Response(JSON.stringify({ok:true}),{headers:{'Content-Type':'application/json'}})
 // Existing consumers compile the actual transport in VM contexts without imports.
 const context={exports:{},process:{env:{}},console:{error(){}},fetch:async()=>{calls++;return reply()}}
 vm.runInNewContext(code,context)
 assert.deepEqual(await context.exports.fetchApi('/api/fixture'),{ok:true})
 const body={error:'Original backend detail',code:'fixture',details:{keep:true}}
 reply=()=>new Response(JSON.stringify(body),{status:400,headers:{'Content-Type':'application/json'}})
 await assert.rejects(context.exports.fetchApi('/api/fixture',{method:'POST',body:'unchanged'}),error=>{assert.equal(error.message,body.error);assert.equal(error.status,400);assert.deepEqual(error.body,body);return true})
 const network=new Error('Original network detail');reply=()=>{throw network}
 await assert.rejects(context.exports.fetchApi('/api/fixture'),error=>error===network)
 assert.equal(calls,3,'No locale import, retry or extra request on these paths')
 console.log('PASS legacy transport imports: success, backend payload/status and network identity without a locale loader; exactly three calls')
}
main().catch(error=>{console.error(error);process.exitCode=1})
