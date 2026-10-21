// Actual Settings callbacks; terminal is a JSX stub, never a real updater.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path')
const {fixture,flatten,text,translate,catalogs,descriptions}=require('./optimization-settings-fixture.cjs')
async function main(){
 const known={key:'time_sync',name:'Time Synchronization',has_source:true,has_update:true,version:'1.0',available_version:'1.1',function:'configure_time_sync',function_auto:'configure_time_sync',source:'auto',description:catalogs.en.settings.optimizations.toolDescriptions.timeSync}
 const unknown={...known,key:'future',name:'Future Tool',function:'future_fn',function_auto:'future_fn',description:'New server wording <raw>&'}
 for(const locale of ['sk','en','de']){
  const f=fixture(locale,[known,unknown]);f.render();await f.settle()
  const expected=translate(locale)('settings.optimizations.toolNames.time_sync')
  assert.ok(text(f.tree()).includes(expected));assert.ok(text(f.tree()).includes('Future Tool'))
  const open=flatten(f.tree()).find(n=>n.props?.title===f.t('settings.optimizations.viewUpdates'));assert.ok(open)
  open.props.onClick();f.render()
  assert.ok(text(f.tree()).includes(descriptions.exports.optimizationDescription(known.description,translate(locale))))
  assert.ok(text(f.tree()).includes(unknown.description))
  const count=f.calls.length
  flatten(f.tree()).find(n=>n.type==='button'&&text(n)===f.t('actions.cancel')).props.onClick();f.render()
  assert.equal(f.calls.length,count,'Cancel has no scan/update effects')
  open.props.onClick();f.render()
  flatten(f.tree()).find(n=>n.type==='button'&&text(n).trim()===f.t('settings.optimizations.updateSelected')).props.onClick();f.render()
  const terminal=flatten(f.tree()).find(n=>n.props?.scriptName==='update_post_install_function')
  assert.equal(terminal.props.params.FUNCTIONS_BATCH,'auto:configure_time_sync:time_sync\nauto:future_fn:future')
  assert.equal(terminal.props.params.EXECUTION_MODE,'web');assert.equal(f.calls.length,count,'Only an inert terminal node was created')
  const single=fixture(locale,[known]);single.render();await single.settle()
  const button=flatten(single.tree()).find(n=>n.props?.title===single.t('settings.optimizations.updateToolTitle',{name:expected,version:'1.1'}));assert.ok(button)
  button.props.onClick({stopPropagation(){}});single.render()
  const one=flatten(single.tree()).find(n=>n.props?.scriptName==='update_post_install_function')
  assert.equal(one.props.title,single.t('settings.optimizations.updateOneTitle',{name:expected}))
  assert.equal(one.props.params.FUNCTIONS_BATCH,'auto:configure_time_sync:time_sync')
  assert.equal([...f.calls,...single.calls].filter(c=>c.method!=='GET'||/scan|script-runner/.test(c.endpoint)).length,0)
 }
 for(const locale of ['sk','en','de']){
  const t=translate(locale)
  for(const [key,name] of Object.entries(catalogs.en.settings.optimizations.toolNames)){
   assert.equal(descriptions.exports.optimizationToolName(key,name,t),locale==='sk'?catalogs.sk.settings.optimizations.toolNames[key]:name)
  }
  assert.equal(descriptions.exports.optimizationToolName('future','Future <raw>&',t),'Future <raw>&')
 }
 const source=path.join(__dirname,'../scripts/post_install')
 const actual=new Set(['auto_post_install.sh','customizable_post_install.sh'].flatMap(file=>[...fs.readFileSync(path.join(source,file),'utf8').matchAll(/^\s*# description: (.+)$/gm)].map(m=>m[1].trim())))
 const english=catalogs.en.settings.optimizations.toolDescriptions
 assert.deepEqual(new Set(Object.values(english)),actual)
 for(const [key,description]of Object.entries(english))assert.equal(descriptions.exports.optimizationDescription(description,translate('sk')),catalogs.sk.settings.optimizations.toolDescriptions[key])
 assert.equal(descriptions.exports.optimizationDescription('Changed version description',translate('sk')),'Changed version description')
 console.log('PASS optimization names/descriptions: actual Settings cards/single/batch/cancel, unchanged payload, EN/SK/fallback, exact live-description matching; host calls 0')
}
main().catch(error=>{console.error(error);process.exitCode=1})
