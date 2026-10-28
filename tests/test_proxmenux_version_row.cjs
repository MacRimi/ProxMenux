// Render the shipped component with an inert snapshot; no network or power.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm')
const app=path.resolve(__dirname,'../AppImage'),ts=require(path.join(app,'node_modules/typescript'))
const react=require(path.join(app,'node_modules/react'))
const {renderToStaticMarkup}=require(path.join(app,'node_modules/react-dom/server'))
const code=ts.transpileModule(fs.readFileSync(path.join(app,'components/host-update-status.tsx'),'utf8'),{
 compilerOptions:{target:ts.ScriptTarget.ES2020,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText
for(const locale of ['en','sk']){
 const catalog=JSON.parse(fs.readFileSync(path.join(app,'messages',locale,'common.json'),'utf8'))
 const t=(key,params={})=>{const text=key.split('.').reduce((x,k)=>x?.[k],catalog);assert.equal(typeof text,'string',key);return text.replace(/\{(\w+)\}/g,(_,k)=>params[k]??'{'+k+'}')}
 const versions=catalog.healthStatus.versions
 let value, effects=0
 const exports={}
 vm.runInNewContext(code,{exports,require:name=>{
  if(name==='react')return {...react,useState:()=>[value,()=>{}],useEffect:()=>{},useRef:()=>({current:null})}
  if(name==='react/jsx-runtime')return require(path.join(app,'node_modules/react/jsx-runtime'))
  if(name==='@radix-ui/react-alert-dialog'||name==='./ui/button')return {}
  if(name==='@/lib/i18n/provider')return {useT:()=>t}
  if(name==='@/lib/api-config')return {getAuthToken:()=>null}
  if(name==='lucide-react')return require(path.join(app,'node_modules/lucide-react'))
  throw Error('Unexpected boundary '+name)
 },fetch:()=>{effects++;throw Error('Forbidden request')},console})
 const snapshot={installed:'1.2.7',available:'1.2.7',state:'current',channel:'stable',checked_at:'2026-10-28T08:00:00Z'}
 const render=data=>{value=data;return renderToStaticMarkup(react.createElement(exports.ProxMenuxVersionCard,{getApiUrl:p=>p}))}
 const current=render(snapshot)
 assert.ok(current.includes('<details')&&current.includes('<summary'),'current version is a compact native disclosure')
 assert.ok(!current.includes('<section')&&!current.includes('<dl>'),'up-to-date version has no expanded update card')
 assert.ok(current.includes('1.2.7')&&current.includes('text-green-500'))
 assert.ok(current.includes(versions.stable)&&current.includes(versions.checked.split('{')[0]))
 const available=render({...snapshot,state:'available',available:'1.2.8'})
 assert.ok(available.includes('<section')&&available.includes('<dl'))
 assert.ok(available.includes('1.2.7')&&available.includes('1.2.8')&&available.includes(versions.available))
 assert.ok(available.includes('text-blue-500'))
 for(const data of [null,{...snapshot,state:'unknown'},{...snapshot,state:'unknown',available:null,checked_at:null,channel:'beta'}]){
  const unknown=render(data)
  assert.ok(unknown.includes('<details')&&unknown.includes('text-amber-500'))
  assert.ok(unknown.includes(versions.unknown)&&!unknown.includes('text-green-500'))
  if(data?.available)assert.ok(unknown.includes(versions.lastKnown),'old version remains explicitly last known')
  else assert.ok(unknown.includes(versions.unverified),'missing data is never a current version')
 }
 assert.equal(effects,0,'rendering/disclosure never triggers update, installation or power')
}
console.log('PASS actual ProxMenux version rendering: compact current, expanded update, unknown/last-known; EN/SK and zero effects')
