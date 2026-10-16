const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')
const source = fs.readFileSync(path.join(__dirname, '../components/proxmox-dashboard.tsx'), 'utf8')
const tree = ts.createSourceFile('dashboard.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
const wrapper = tree.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'ProxmoxDashboard')
assert.ok(wrapper, 'platform gate must remain separate from PVE hooks/prewarmers')
const code = ts.transpileModule(ts.createPrinter().printNode(ts.EmitHint.Unspecified, wrapper, tree), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
}).outputText
const PBS = () => {}, PVE = () => {}
for (const [data, error, expected] of [
  [{ product: 'pbs' }, null, PBS], [{ product: 'pve' }, null, PVE],
  [undefined, new Error('older API'), PVE], [undefined, null, 'p'],
]) {
  const sandbox = {
    exports: {}, PBSDashboard: PBS, PVEDashboard: PVE,
    useT: () => key => key, useSWR: () => ({ data, error }),
    require: () => ({ jsx: (type, props) => ({ type, props }) }),
  }
  vm.runInNewContext(code, sandbox)
  assert.equal(sandbox.exports.ProxmoxDashboard().type, expected)
}
console.log('PASS: PBS dashboard routing and loading gate do not mount PVE prewarmers')
