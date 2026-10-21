// Load real TS modules with injected host boundaries; no bundler or network.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm')
const app=path.resolve(__dirname,'../AppImage'),ts=require(path.join(app,'node_modules/typescript'))
function loadTypeScript(file,globals={}){
 const resolved=path.isAbsolute(file)?file:path.join(app,file)
 if(resolved.endsWith('.json'))return JSON.parse(fs.readFileSync(resolved,'utf8'))
 const exports={}
 const context={process:{env:{}},console,Error,SyntaxError,...globals,exports,module:{exports},require:name=>{
  if(name.startsWith('@/'))return loadTypeScript(path.join(app,name.slice(2))+'.ts',globals)
  if(!name.startsWith('.'))return require(name)
  let target=path.resolve(path.dirname(resolved),name)
  if(!fs.existsSync(target))target+='.ts'
  return loadTypeScript(target,globals)
 }}
 const compiled=ts.transpileModule(fs.readFileSync(resolved,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020,esModuleInterop:true}}).outputText
 vm.runInNewContext(compiled,context,{filename:resolved})
 return context.module.exports
}
module.exports={loadTypeScript}
