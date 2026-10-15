// Execute the real Updates JSX and handlers with independent state fixtures.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const root = path.resolve(__dirname, '../../AppImage')
const ts = require(path.join(root, 'node_modules/typescript'))
const source = fs.readFileSync(path.join(root, 'components/virtual-machines.tsx'), 'utf8')
const tree = ts.createSourceFile('vm.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
let appRender, bulkRender, checkButton, checkHandler
const declarations = []
function walk(node) {
  if (ts.isCallExpression(node) && node.expression.getText(tree) === 'appSections.map') appRender = node.arguments[0].getText(tree)
  if (ts.isConditionalExpression(node) && node.condition.getText(tree) === 'bulkConfigured'
    && node.whenTrue.getText(tree).includes('applyBulkUpdate(')) bulkRender = node.whenTrue.getText(tree)
  if (ts.isVariableDeclaration(node)) {
    if (node.name.getText(tree) === 'checkOsUpdates') checkHandler = node.getText(tree)
    if (['selectedBulkUpdateStates', 'bulkHasPendingUpdates', 'bulkAllTargetsUpToDate', 'bulkHasUnknownTargets'].includes(node.name.getText(tree)))
      declarations.push('const ' + node.getText(tree) + ';')
  }
  if (ts.isJsxElement(node) && node.openingElement.tagName.getText(tree) === 'Button'
    && node.openingElement.attributes.getText(tree).includes('checkOsUpdates(selectedVM.vmid)')) checkButton = node.getText(tree)
  ts.forEachChild(node, walk)
}
walk(tree)
assert(appRender && bulkRender && checkButton && checkHandler)
function compile(code, context) {
  const result = ts.transpileModule(code, {compilerOptions: {target: ts.ScriptTarget.ES2020,
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX}, reportDiagnostics: true})
  assert.equal(result.diagnostics.length, 0)
  vm.runInNewContext(result.outputText, context)
  return context.exports
}
function flatten(node) {
  if (Array.isArray(node)) return node.flatMap(flatten)
  return node && typeof node === 'object' ? [node, ...flatten(node.props?.children)] : []
}
function text(node) {
  if (Array.isArray(node)) return node.map(text).join(' ')
  return node && typeof node === 'object' ? text(node.props?.children) : typeof node === 'string' ? node : ''
}
for (const locale of ['en', 'sk']) {
  const messages = JSON.parse(fs.readFileSync(path.join(root, `messages/${locale}/common.json`)))
  const t = key => key.split('.').reduce((o, part) => o?.[part], messages) ?? key
  const calls = []
  const context = {exports: {}, t, customCmdEditingApp: null, uc: null, helperExists: false,
    helperUsesWebUpdater: false, selectedVM: {vmid: 210, status: 'stopped'}, openCustomCmdEditor() {},
    openApplyTerminal: (...args) => calls.push(args), getUpdateActionButtonClass: () => 'original-style',
    bulkApplying: false, osCheckingVmid: null, updatesRefreshing: false, controlLoading: false,
    applyOpen: false, osUpdateStatusKnown: true, hasOsUpdates: false,
    dockerEngineHasUpdate: false, dockerEngineUpToDate: true, dockerInventoryRefreshing: false,
    dockerInventoryAvailable: true, dockerUpdateUnits: [], selectedBulkLabels: ['OS', 'Custom app'],
    bulkTargets: ['os', 'app:custom'], applyBulkUpdate: () => calls.push('bulk'), checkOsUpdates() {},
    require: () => ({jsx: (type, props) => ({type, props}), jsxs: (type, props) => ({type, props})})}
  for (const name of ['Button', 'Package', 'Settings2', 'ArrowUpCircle', 'CheckCircle2', 'RefreshCw', 'Pin', 'Loader2']) context[name] = name
  const ui = compile('exports.app = (' + appRender + '); exports.check = () => (' + checkButton + ');', context)
  const original = {id: 'custom', name: 'Custom app', installed_via: 'manual', installed_version: null,
    latest_version: '2.0', update_available: null, update_command: 'approved-command', checked_at: '2026-10-14T10:43:19Z'}
  const before = JSON.stringify(original)
  const rendered = ui.app(original)
  assert.equal(ui.check().props.disabled, true, 'a stopped CT must not start an index refresh from the check button')
  assert.match(text(rendered), locale === 'sk' ? /Nainštalovaná verzia nie je overená/ : /Installed version is unverified/)
  assert.doesNotMatch(text(rendered), /Čaká sa|pending|upstreamAvailable/)
  const action = flatten(rendered).find(n => n.type === 'Button')
  assert.equal(text(action).trim(), locale === 'sk' ? 'Spustiť vlastný príkaz' : 'Run custom command')
  assert.equal(calls.length, 0, 'render/check timestamp must not execute an updater')
  action.props.onClick()
  assert.equal(calls.length, 1)
  assert.equal(calls[0][0], 210)
  assert.equal(calls[0][1], 'app')
  assert.equal(calls[0][2].updateCommand, 'approved-command')
  assert.deepEqual(Array.from(calls[0][2].targetIds), ['app:custom'])
  assert.equal(JSON.stringify(original), before, 'UI must not confirm or edit the stored version')
  calls.length = 0
  const knownVersion = ui.app({...original, installed_version: '1.0'})
  assert(text(knownVersion).includes('1.0'), 'keep the known installed version when comparison is unavailable')
  assert.doesNotMatch(text(knownVersion), /Čaká sa|Version tracking pending/)
  const noDetector = ui.app({...original, installed_via: undefined})
  assert(text(noDetector).includes(t('vmLxc.updates.versionTrackingNotConfigured')))
  assert.equal(text(flatten(noDetector).find(n => n.type === 'Button')).trim(), t('vmLxc.updates.runCustomCommand'))
  assert.equal(text(ui.check()).trim(), locale === 'sk' ? 'Skontrolovať balíky systému' : 'Check system packages')
  for (const installed_via of ['binary', 'file', 'dpkg', 'apk']) {
    const unavailable = ui.app({...original, installed_via, error: 'probe failed'})
    assert.match(text(unavailable), locale === 'sk' ? /Dostupnosť aktualizácie nie je overená/ : /Update availability is unverified/)
    assert.doesNotMatch(text(unavailable), /Čaká sa|next scheduled|upToDateAtLabel/)
  }
  const current = {...original, installed_version: '2.0', update_available: false}
  const pending = {...original, installed_version: '1.0', update_available: true}
  assert(text(ui.app(current)).includes(t('vmLxc.updates.upToDateAtLabel')))
  assert(text(ui.app(pending)).includes(t('vmLxc.updates.installedLabel')))
  assert.equal(text(flatten(ui.app(pending)).find(n => n.type === 'Button')).trim(), t('vmLxc.updates.applyUpdate'))
  assert(!flatten(ui.app({...original, update_command: ''})).some(n => n.type === 'Button'), 'no command means no execution')
  function bulk(app, osKnown = true, extra = {}) {
    return compile(declarations.join('\n') + '\nexports.rendered=(' + bulkRender + ');',
      {...context, exports: {}, registeredApps: [app], osUpdateStatusKnown: osKnown, ...extra}).rendered
  }
  const unknownBulk = bulk(original)
  assert.match(text(unknownBulk), locale === 'sk' ? /nie je overená/ : /is unverified/)
  assert.equal(flatten(unknownBulk).find(n => n.type === 'Button').props.disabled, false, 'preserve explicit manual execution')
  assert.equal(flatten(bulk(current)).find(n => n.type === 'Button').props.disabled, true)
  assert.equal(flatten(bulk(original, false)).find(n => n.type === 'Button').props.disabled, true, 'unknown OS blocks bulk')
  assert.equal(flatten(bulk(original, true, {bulkApplying: true})).find(n => n.type === 'Button').props.disabled, true)
  const mixed = bulk(pending, true, {registeredApps: [pending, {...original, id: 'unknown'}],
    bulkTargets: ['os', 'app:custom', 'app:unknown']})
  assert.match(text(mixed), locale === 'sk' ? /nie je overená/ : /is unverified/)
  assert.equal(flatten(mixed).find(n => n.type === 'Button').props.disabled, false)
  const imageUnavailable = bulk(original, true, {bulkTargets: ['os', 'docker-unit:one'], dockerInventoryAvailable: false})
  assert.equal(flatten(imageUnavailable).find(n => n.type === 'Button').props.disabled, true, 'unavailable image cannot be run')
  assert.doesNotMatch(text(bulk(pending)), locale === 'sk' ? /nie je overená/ : /is unverified/)
  assert.equal(calls.length, 0, 'all status fixtures are side-effect free')
}
assert.match(source, /t\("vmLxc\.updates\.startBeforeCheck"\)/,
  'the Updates tab must explain why checking a stopped CT is disabled')
;(async () => {
  const context = {exports: {}, osCheckRequestRef: {current: null}, applyOpen: false, controlLoading: false,
    selectedVMRef: {current: {vmid: 210}}, vmModalCacheRef: {current: {details: new Map()}},
    setOsCheckingVmid() {}, setOsCheckError() {}, setSelectedVM() {}, setVMDetails() {}, mutate: async () => {},
    t: key => key, requests: []}
  context.refreshCheckLxcUpdates = async vmid => {context.requests.push(['check', vmid]); return {count: 0}}
  context.fetchApi = async (url, options) => {context.requests.push([url, options]); return {}}
  const handler = compile('const ' + checkHandler + '; exports.check = checkOsUpdates;', context)
  await handler.check(210)
  assert.deepEqual(context.requests, [['check', 210], ['/api/vms/210', undefined]])
  context.requests.length = 0
  for (const guard of ['applyOpen', 'controlLoading']) {
    context[guard] = true
    await handler.check(210)
    context[guard] = false
  }
  assert.equal(context.requests.length, 0, 'blocked checks make no API/probe requests')
  console.log('PASS common update status: EN/SK unknown/current/pending/error/custom/no-command/bulk/OS check guards; actual JSX and handlers')
})().catch(error => {console.error(error); process.exitCode = 1})
