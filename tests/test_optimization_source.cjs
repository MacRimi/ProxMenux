// Actual Settings handlers and real fetchApi; all responses are inert fixtures.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm')
const {execFileSync}=require('node:child_process')
const root=path.resolve(__dirname,'..'),app=path.join(root,'AppImage')
const ts=require(path.join(app,'node_modules/typescript'))
const catalogs=Object.fromEntries(['en','sk','de'].map(locale=>[locale,JSON.parse(fs.readFileSync(path.join(app,`messages/${locale}/common.json`)))]))
const translate=locale=>(key,params={})=>{
 const find=data=>key.split('.').reduce((item,name)=>item?.[name],data)
 return (find(catalogs[locale])??find(catalogs.en)??key).replace(/\{(\w+)\}/g,(all,key)=>params[key]??all)
}
const flatten=node=>!node||typeof node!=='object'?[]:[node,...[node.props?.children].flat(Infinity).flatMap(flatten)]
const text=node=>node==null||node===false?'':typeof node!=='object'?String(node):[node.props?.children].flat(Infinity).map(text).join(' ')
const compile=source=>ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020,jsx:ts.JsxEmit.ReactJSX}}).outputText
const source=process.argv.includes('--baseline')?execFileSync('git',['show','e826680c:AppImage/components/settings.tsx'],{cwd:root,encoding:'utf8'}):fs.readFileSync(path.join(app,'components/settings.tsx'),'utf8')
const formatter={exports:{}};vm.runInNewContext(compile(fs.readFileSync(path.join(app,'lib/optimization-source-errors.ts'),'utf8')),formatter)
const tools=['one','two'].map(key=>({key,name:'Demo '+key,enabled:true,has_source:true,version:'1.0',available_version:'1.1'}))
const sourceBody={success:true,function:'demo',script:'demo.sh',source:'demo() {\n  echo "<tag>& $HOME"\n}\n',deprecated:false}
function fixture(locale='sk',catalog=tools){
 let cursor=0,states=[],refs=[],effects=[],memo=[],tree,language=locale,reply=()=>sourceBody
 const calls=[],events={},timers=[],copies=[];let fallbackCopies=0
 const t=(key,params)=>translate(language)(key,params)
 const react={
  useState(value){const i=cursor++;if(!(i in states))states[i]=typeof value==='function'?value():value;return[states[i],v=>{states[i]=typeof v==='function'?v(states[i]):v}]},
  useRef(value){const i=cursor++;return refs[i]??=( {current:value})},
  useEffect(fn,deps){const i=cursor++,old=memo[i];if(!old||deps?.some((v,n)=>v!==old.deps?.[n]))effects.push(()=>{old?.cleanup?.();memo[i]={deps,cleanup:fn()}})},
 }
 const response=(body,status=200)=>({ok:status<400,status,statusText:'fixture',headers:{get:()=> 'application/json'},json:async()=>body})
 const fetch=async(url,options={})=>{
  const endpoint=String(url).replace(/^https?:\/\/[^/]+/,'');calls.push({endpoint,method:options.method||'GET'})
  assert.equal(options.method||'GET','GET','Source viewer may never mutate')
  if(endpoint.includes('/tool-source/')){const result=await reply(endpoint);if(result instanceof Error)throw result;return result?.http?response(result.body,result.http):response(result)}
  if(endpoint.endsWith('/installed-tools'))return response({success:true,installed_tools:catalog,updates_available_count:0})
  return response({categories:[],storages:[],interfaces:[],dismissed:[],success:true,candidates:[],configured:false})
 }
 const api={exports:{},fetch,process:{env:{}},console:{error(){}}};vm.runInNewContext(compile(fs.readFileSync(path.join(app,'lib/api-config.ts'),'utf8')),api)
 const add=(name,handler)=>{(events[name]??=new Set()).add(handler)},remove=(name,handler)=>events[name]?.delete(handler)
 const win={addEventListener:add,removeEventListener:remove,setTimeout:fn=>{timers.push(fn);return timers.length},isSecureContext:true}
 const doc={addEventListener:add,removeEventListener:remove,body:{appendChild(){},removeChild(){}},createElement:()=>({style:{},focus(){},select(){}}),execCommand:()=>{fallbackCopies++;return true}}
 const clipboard={writeText:async value=>copies.push(value)}
 const context={exports:{},window:win,document:doc,navigator:{clipboard},console:{error(){}},setTimeout:win.setTimeout,
 require:name=>{
  if(name==='react')return react
  if(name==='react/jsx-runtime')return{jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})}
  if(name.includes('optimization-source-errors'))return formatter.exports
  if(name.includes('api-config'))return api.exports
  if(name.includes('i18n/provider'))return{SUPPORTED_LANGUAGES:[],useI18n:()=>({t,language,setLanguage:value=>language=value})}
  if(name.includes('use-platform'))return{useIsPbs:()=>false}
  if(name.includes('format-network'))return{getNetworkUnit:()=> 'Bytes'}
  return new Proxy({},{get:(_,key)=>key})
 }}
 vm.runInNewContext(compile(source),context)
 const render=()=>{cursor=0;effects=[];tree=context.exports.Settings();for(const effect of effects)effect();return tree}
 const settle=async()=>{for(let i=0;i<24;i++)await Promise.resolve();render()}
 const tool=name=>flatten(tree).find(node=>node.props?.title===t('settings.optimizations.sourceTitle')&&text(node).includes(catalog.find(tool=>tool.key===name)?.name||'Demo '+name))
 const dialog=()=>flatten(tree).find(node=>node.props?.role==='dialog')
 const close=()=>flatten(tree).find(node=>node.props?.['aria-label']===t('actions.close')).props.onClick()
 return{render,settle,tool,dialog,close,calls,copies,timers,tree:()=>tree,setReply:value=>reply=value,t,
  language:value=>{language=value;render()},escape:()=>events.keydown?.forEach(fn=>fn({key:'Escape'})),
  unmount:()=>memo.forEach(effect=>effect?.cleanup?.()),clipboard,win,fallbackCopies:()=>fallbackCopies}
}
async function main(){
 if(process.argv.includes('--baseline')){
  const f=fixture();f.render();await f.settle();f.setReply(()=>({http:404,body:{success:false,error:'Function not found in available scripts'}}));await f.tool('one').props.onClick();f.render();
  assert.ok(text(f.tree()).includes('Failed to load source code'));assert.ok(!text(f.tree()).includes(f.t('settings.optimizations.sourceFunctionMissing')))
  console.log('REPRODUCED baseline: real Settings + fetchApi 404 displays English Failed to load source code');return
 }
 for(const locale of ['en','sk','de']){
  const f=fixture(locale);f.render();await f.settle()
  for(const [reply,key,param]of [
   [{success:false},'sourceUnavailable'],[null,'sourceUnavailable'],[{success:'yes',source:'invalid'},'sourceUnavailable'],[{success:true,source:''},'sourceUnavailable'],[{success:true,source:'   '},'sourceUnavailable'],[{success:true,source:17},'sourceUnavailable'],
   [{http:404,body:{success:false,error:'Function not found in available scripts'}},'sourceFunctionMissing'],
   [{http:404,body:{success:false,error:'Unknown tool: demo'}},'sourceUnknownTool',{tool:'demo'}],
   [{http:404,body:{success:false,error:'No function mapping for demo'}},'sourceNoMapping',{tool:'demo'}],
   [{success:false,error:'Source code not available'},'sourceUnavailable'],[new Error('network unreachable'),'sourceLoadFailed']]){
   f.setReply(()=>reply);await f.tool('one').props.onClick();f.render();assert.ok(text(f.dialog()).includes(f.t('settings.optimizations.'+key,param)),key)
  }
  f.setReply(()=>({http:500,body:{success:false,error:'PermissionError /opt/demo <unsafe>&'}}));await f.tool('one').props.onClick();f.render();assert.ok(text(f.dialog()).includes('PermissionError /opt/demo <unsafe>&'))
  f.language('sk');assert.ok(text(f.dialog()).includes(translate('sk')('settings.optimizations.sourceLoadFailed')))
  f.setReply(()=>sourceBody);await f.tool('one').props.onClick();f.render();
  const backdrop=flatten(f.tree()).find(node=>node.props?.className?.startsWith('fixed inset-0')&&flatten(node).some(child=>child.props?.role==='dialog'))
  assert.equal(backdrop.props.style.margin,0,'parent space-y must not offset the fixed backdrop')
  const pre=flatten(f.dialog()).find(node=>node.type==='pre');assert.ok(pre.props.dangerouslySetInnerHTML.__html.includes('&lt;'));assert.ok(!pre.props.dangerouslySetInnerHTML.__html.includes('<tag>'))
  const copy=flatten(f.dialog()).find(node=>node.props?.title===f.t('actions.copyToClipboard'));await copy.props.onClick();f.render();assert.equal(f.copies.at(-1),sourceBody.source)
  f.win.isSecureContext=false;await copy.props.onClick();assert.equal(f.fallbackCopies(),1)
  const before=f.calls.length;f.close();f.render();assert.equal(f.dialog(),undefined);assert.equal(f.calls.length,before)
 }
 const names=catalogs.en.settings.optimizations.sourceToolNames
 for(const [key,name]of Object.entries(names)){
  assert.equal(formatter.exports.optimizationSourceName(key,name,translate('en')),name)
  assert.equal(formatter.exports.optimizationSourceName(key,name,translate('sk')),catalogs.sk.settings.optimizations.sourceToolNames[key])
  assert.equal(formatter.exports.optimizationSourceName(key,name,translate('de')),name)
 }
 assert.equal(Object.keys(names).length,27)
 assert.equal(formatter.exports.optimizationSourceName('future','Future tool',translate('sk')),'Future tool')
 const known=fixture('sk',[{...tools[0],key:'time_sync',name:'Time Synchronization'}]);known.render();await known.settle();await known.tool('time_sync').props.onClick();known.render();assert.ok(text(known.dialog()).includes('Synchronizácia času'));known.language('en');assert.ok(text(known.dialog()).includes('Time Synchronization'))
 const f=fixture();f.render();await f.settle();let resolveOld;f.setReply(()=>new Promise(resolve=>resolveOld=resolve));const old=f.tool('one').props.onClick();f.render();assert.ok(flatten(f.dialog()).some(node=>node.props?.role==='status'))
 f.close();f.render();resolveOld(sourceBody);await old;f.render();assert.equal(f.dialog(),undefined,'late success never reopens closed viewer')
 let resolveStale;f.setReply(()=>new Promise(resolve=>resolveStale=resolve));const stale=f.tool('one').props.onClick();f.setReply(()=>({...sourceBody,source:'two() { :; }'}));await f.tool('two').props.onClick();f.render();resolveStale({http:404,body:{error:'Function not found in available scripts'}});await stale;f.render();assert.ok(text(f.dialog()).includes('Demo two'));assert.equal(flatten(f.dialog()).some(node=>node.props?.role==='alert'),false)
 const before=f.calls.length;f.escape();f.render();assert.equal(f.dialog(),undefined);assert.equal(f.calls.length,before)
 f.setReply(()=>sourceBody);await f.tool('one').props.onClick();f.render();let copyResolve;f.clipboard.writeText=()=>new Promise(resolve=>copyResolve=resolve);const copying=flatten(f.dialog()).find(node=>node.props?.title===f.t('actions.copyToClipboard')).props.onClick();f.close();f.render();copyResolve();await copying;f.render();assert.equal(f.dialog(),undefined)
 let unmountedResolve;f.setReply(()=>new Promise(resolve=>unmountedResolve=resolve));const unmounted=f.tool('one').props.onClick();f.render();const snapshot=text(f.tree());f.unmount();unmountedResolve(sourceBody);await unmounted;f.render();assert.equal(text(f.tree()),snapshot,'response after unmount cannot update modal state')
 assert.equal(f.calls.filter(call=>call.method!=='GET').length,0);assert.equal(f.calls.filter(call=>/scan|update|script-runner/.test(call.endpoint)).length,0)
 console.log('PASS source viewer: actual Settings/fetchApi, EN/SK/fallback, 404/500/network/malformed/empty, exact copy, late requests and close/Esc; mutations/scan/update 0')
}
main().catch(error=>{console.error(error);process.exitCode=1})
