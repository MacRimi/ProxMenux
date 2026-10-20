// Real transport templates and actual fetchApi, with no network/guest access.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const {execFileSync} = require('node:child_process')
const root = path.resolve(__dirname, '../..')
const app = path.join(root, 'AppImage')
const ts = require(path.join(app, 'node_modules/typescript'))
function load(relative, extra = {}) {
  const compiled = ts.transpileModule(fs.readFileSync(path.join(app, relative), 'utf8'), {
    compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}, reportDiagnostics: true,
  })
  assert.deepEqual(compiled.diagnostics, [])
  const context = {exports: {}, process: {env: {}}, console: {error() {}}, ...extra}
  vm.runInNewContext(compiled.outputText, context)
  return context.exports
}
const {localizeAppEditorError: localize} = load('lib/lxc-app-editor-errors.ts')
const catalogs = Object.fromEntries(['en', 'sk', 'de'].map(locale => [locale,
  JSON.parse(fs.readFileSync(path.join(app, `messages/${locale}/common.json`)))]))
const translate = locale => (key, params = {}) => {
  const lookup = data => key.split('.').reduce((item, segment) => item?.[segment], data)
  const template = lookup(catalogs[locale]) ?? lookup(catalogs.en)
  assert.equal(typeof template, 'string', 'Missing translation ' + key)
  return template.replace(/\{(\w+)\}/g, (all, key) => params[key] ?? all)
}
const en = translate('en'), sk = translate('sk')
// Enumerate only pure validator ASTs; importing lxc_apps would access host state.
const contract = JSON.parse(execFileSync('python3', ['-c', String.raw`
import ast,json,re,typing,sys
tree=ast.parse(open(sys.argv[1]).read())
names={'_err','_validate_command_argv','_validate_binary_args','_validate_ports','validate_config'}
ns={'re':re,'Any':typing.Any,'Optional':typing.Optional}
for node in tree.body:
    if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id.startswith('_'):
        try: value=ast.literal_eval(node.value)
        except (ValueError,TypeError):
            if not (isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Attribute) and isinstance(node.value.func.value,ast.Name) and node.value.func.value.id=='re' and node.value.func.attr=='compile'): continue
            args=[getattr(re,a.attr) if isinstance(a,ast.Attribute) and isinstance(a.value,ast.Name) and a.value.id=='re' else ast.literal_eval(a) for a in node.value.args]
            value=re.compile(*args)
        ns[node.targets[0].id]=value
functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
exec(compile(ast.Module(body=functions,type_ignores=[]),'<pure validators>','exec'),ns)
messages=set()
context={**ns,'i':3,'p':8080,'field':'repo','e':'missing ], position 4\npattern: v?(test'}
for function in functions:
    for n in ast.walk(function):
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='_err' and n.args and isinstance(n.args[0],(ast.Constant,ast.JoinedStr)):
            messages.add(eval(compile(ast.Expression(n.args[0]),'<contract>','eval'),context))
cases=[[],{}, {'name':'Test','installed_via':'file','file_path':'relative'},
 {'name':'Test','installed_via':'file','file_path':'/fiction/version','file_regex':'['},
 {'name':'Test','installed_via':'command','command_argv':['test','bad\narg']},
 {'name':'Test','ports':[{'port':8080},{'port':8080}]},
 {'name':'Test','installed_via':'manual'}]
errors=[]
for case in cases:
    ok,error=ns['validate_config'](case)
    assert not ok
    errors.append(error)
print(json.dumps({'templates':sorted(messages),'actual':errors}))
`, path.join(app, 'scripts/lxc_apps.py')], {encoding: 'utf8'}))
assert.equal(contract.templates.length, 69, 'Update the contract inventory when validation changes')
for (const message of [...contract.templates, ...contract.actual]) {
  assert.equal(localize(message, en), message, 'EN must preserve the exact backend message')
  assert.notEqual(localize(message, sk), message, 'Untranslated backend validation: ' + message)
  assert.equal(localize(message, translate('de')), message, 'Missing locale falls back to EN')
}
// Every supported message, including detector errors, preserves interpolated data.
const enErrors = catalogs.en.vmLxc.appEditor.errors, skErrors = catalogs.sk.vmLxc.appEditor.errors
assert.deepEqual(Object.keys(enErrors).sort(), Object.keys(skErrors).sort())
for (const [key, template] of Object.entries(enErrors)) {
  const params = Object.fromEntries([...template.matchAll(/\{(\w+)\}/g)].map(([, name]) => [name,
    ['index','port','max','code'].includes(name) ? '17' : "detail /opt/app --version {literal} <tag>\nnext line"]))
  const message = en(`vmLxc.appEditor.errors.${key}`, params)
  assert.equal(localize(message, en), message)
  assert.equal(localize(message, sk), sk(`vmLxc.appEditor.errors.${key}`, params), key)
}
assert.equal(localize('binary_args[4] exceeds 256 chars', sk), 'Argument binary_args[4] môže mať najviac 256 znakov.')
assert.equal(localize('tag_regex is not a valid regex: [bad]\nposition 4', sk), 'Regulárny výraz pre tagy (tag_regex) je neplatný: [bad]\nposition 4')
for (const message of ['unknown /opt/app --version', '<script>alert(1)</script>', 'file_regex is required extra', 'prefix file_regex is required', 'binary_args[-1] exceeds 4 chars']) {
  assert.equal(localize(message, sk), message, 'Unknown detail must remain intact')
}
for (const empty of [null, undefined, '']) assert.equal(localize(empty, sk), '')
assert.equal(catalogs.sk.vmLxc.appEditor.commandPlaceholder, catalogs.en.vmLxc.appEditor.commandPlaceholder)
assert.equal(catalogs.sk.vmLxc.appEditor.regexPlaceholderVersion, catalogs.en.vmLxc.appEditor.regexPlaceholderVersion)
async function main() {
  let requests = 0
  const backend = 'file_path is required and must be an absolute path'
  const {fetchApi} = load('lib/api-config.ts', {fetch: async () => {
    requests++
    return {ok: false, status: 400, statusText: 'BAD REQUEST', headers: {get: () => 'application/json'}, json: async () => ({error: backend})}
  }})
  for (const [method, route] of [['POST','/api/vms/999999/apps'], ['PUT','/api/vms/999999/apps/fake'], ['POST','/api/vms/999999/apps/test']]) {
    try {await fetchApi(route, {method, body: '{}'}); assert.fail('Expected validation failure')}
    catch (error) {
      assert.equal(error.message, backend)
      assert.equal(localize(error.message, sk), 'Zadaj úplnú cestu k súboru (file_path), začínajúcu lomkou /.')
    }
  }
  assert.equal(requests, 3)
  console.log(`PASS app editor: ${contract.templates.length} backend validation templates, ${Object.keys(enErrors).length} EN/SK rules, real fetchApi POST/PUT/test fixtures; external calls 0`)
}
main().catch(error => {console.error(error); process.exitCode = 1})
