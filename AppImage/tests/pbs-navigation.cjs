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

// The PVE Backup tab keeps native guest retention alongside jobs when adding
// its PBS connection view. Exercise the shipped JSX for all three selections.
const backupSource = fs.readFileSync(path.join(__dirname, '../components/backup-tab.tsx'), 'utf8')
const backupTree = ts.createSourceFile('backup-tab.tsx', backupSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
const backupTab = backupTree.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'BackupTab')
assert.ok(backupTab, 'Backup tab must keep a platform-specific view switch')
const backupCode = ts.transpileModule(ts.createPrinter().printNode(ts.EmitHint.Unspecified, backupTab, backupTree), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
}).outputText
const HostBackup = () => {}, VmBackupJobs = () => {}, BackupStorageRetention = () => {}, PBSPanel = () => {}
for (const [view, expected] of [
  ['host', [HostBackup]], ['guests', [VmBackupJobs, BackupStorageRetention]], ['pbs', [PBSPanel]],
]) {
  const selected = []
  const sandbox = {
    exports: {}, HostBackup, VmBackupJobs, BackupStorageRetention, PBSPanel, DatabaseBackup: () => {},
    useT: () => key => key, useState: () => [view, value => selected.push(value)],
    require: () => ({ jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }), Fragment: Symbol('Fragment') }),
  }
  vm.runInNewContext(backupCode, sandbox)
  const visible = [], mountedHosts = [], buttons = []
  const components = new Set([HostBackup, VmBackupJobs, BackupStorageRetention, PBSPanel])
  function walk(node, hidden = false) {
    if (Array.isArray(node)) { node.forEach(item => walk(item, hidden)); return }
    if (!node || typeof node !== 'object') return
    hidden ||= node.props?.className === 'hidden'
    if (node.type === HostBackup) mountedHosts.push(node)
    if (components.has(node.type) && !hidden) visible.push(node.type)
    if (node.type === 'button') buttons.push(node)
    walk(node.props?.children, hidden)
  }
  walk(sandbox.exports.BackupTab())
  assert.deepEqual(visible, expected, `visible backup panels for ${view}`)
  assert.equal(mountedHosts.length, 1, 'host backup progress must stay mounted across view changes')
  assert.equal(buttons.length, 3)
  assert.equal(buttons.filter(button => button.props['aria-pressed']).length, 1)
  const pbsButton = buttons.find(button => button.props.children === 'pbs.title')
  assert.ok(pbsButton, 'PBS navigation button must exist')
  pbsButton.props.onClick()
  assert.deepEqual(selected, ['pbs'])
}
console.log('PASS: host progress stays mounted, guest jobs and retention stay together, and PBS navigation remains separate')
