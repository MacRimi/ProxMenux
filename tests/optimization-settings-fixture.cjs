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
const source=fs.readFileSync(path.join(app,'components/settings.tsx'),'utf8')
const descriptions={exports:{},require:name=>({default:require(path.resolve(app,'lib',name))})};vm.runInNewContext(compile(fs.readFileSync(path.join(app,'lib/optimization-descriptions.ts'),'utf8')),descriptions)
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
  if(endpoint.endsWith('/installed-tools'))return response({success:true,installed_tools:catalog,updates_available_count:catalog.filter(tool=>tool.has_update).length})
  return response({categories:[],storages:[],interfaces:[],dismissed:[],success:true,candidates:[],configured:false})
 }
 const api={exports:{},fetch,process:{env:{}},console:{error(){}},require:()=>require('./ts-fixture.cjs').loadTypeScript('lib/api-errors.ts')};vm.runInNewContext(compile(fs.readFileSync(path.join(app,'lib/api-config.ts'),'utf8')),api)
 const add=(name,handler)=>{(events[name]??=new Set()).add(handler)},remove=(name,handler)=>events[name]?.delete(handler)
 const win={addEventListener:add,removeEventListener:remove,setTimeout:fn=>{timers.push(fn);return timers.length},isSecureContext:true}
 const doc={addEventListener:add,removeEventListener:remove,body:{appendChild(){},removeChild(){}},createElement:()=>({style:{},focus(){},select(){}}),execCommand:()=>{fallbackCopies++;return true}}
 const clipboard={writeText:async value=>copies.push(value)}
 const context={exports:{},window:win,document:doc,navigator:{clipboard},console:{error(){}},setTimeout:win.setTimeout,
 require:name=>{
  if(name==='react')return react
  if(name==='react/jsx-runtime')return{jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})}
  if(name.includes('optimization-descriptions'))return descriptions.exports
  if(name.includes('api-config'))return api.exports
  if(name.includes('i18n/provider'))return{SUPPORTED_LANGUAGES:[],useI18n:()=>({t,language,setLanguage:value=>language=value})}
  if(name.includes('use-platform'))return{useIsPbs:()=>false}
  if(name.includes('format-network'))return{getNetworkUnit:()=> 'Bytes'}
  return new Proxy({},{get:(_,key)=>key})
 }}
 vm.runInNewContext(compile(source),context)
 const render=()=>{cursor=0;effects=[];tree=context.exports.Settings();for(const effect of effects)effect();return tree}
 const settle=async()=>{for(let i=0;i<24;i++)await Promise.resolve();render()}
 const tool=name=>flatten(tree).find(node=>node.props?.title===t('settings.optimizations.sourceTitle')&&text(node).includes(descriptions.exports.optimizationToolName(name,catalog.find(tool=>tool.key===name)?.name||'Demo '+name,t)))
 const dialog=()=>flatten(tree).find(node=>node.props?.role==='dialog')
 const close=()=>flatten(tree).find(node=>node.props?.['aria-label']===t('actions.close')).props.onClick()
 return{render,settle,tool,dialog,close,calls,copies,timers,tree:()=>tree,setReply:value=>reply=value,t,
  language:value=>{language=value;render()},escape:()=>events.keydown?.forEach(fn=>fn({key:'Escape'})),
  unmount:()=>memo.forEach(effect=>effect?.cleanup?.()),clipboard,win,fallbackCopies:()=>fallbackCopies}
}
module.exports={fixture,flatten,text,translate,catalogs,descriptions}
