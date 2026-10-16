// Execute the real scheduled-run detail JSX: a known backend reason code is
// localized, while an unknown/missing code keeps its raw diagnostic text.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const root = path.resolve(__dirname, '../../AppImage')
const ts = require(path.join(root, 'node_modules/typescript'))
const source = fs.readFileSync(path.join(root, 'components/virtual-machines.tsx'), 'utf8')
const tree = ts.createSourceFile('vm.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
let declaration
let legacyReasons
let reasonCodeHelper
function walk(node) {
  if (ts.isVariableDeclaration(node) && node.name.getText(tree) === 'renderScheduleRunDetails') declaration = node.getText(tree)
  if (ts.isVariableDeclaration(node) && node.name.getText(tree) === 'LEGACY_STOPPED_SCHEDULE_REASONS') legacyReasons = node.getText(tree)
  if (ts.isVariableDeclaration(node) && node.name.getText(tree) === 'scheduleReasonCodeFromPersisted') reasonCodeHelper = node.getText(tree)
  ts.forEachChild(node, walk)
}
walk(tree)
assert(declaration, 'scheduled run detail renderer must exist')
assert(legacyReasons, 'legacy stopped-reason list must exist')
assert(reasonCodeHelper, 'persisted schedule reason-code helper must exist')

function compile(context) {
  const result = ts.transpileModule(`const ${declaration}; exports.render = renderScheduleRunDetails;`, {
    compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    reportDiagnostics: true,
  })
  assert.equal(result.diagnostics.length, 0)
  vm.runInNewContext(result.outputText, context)
  return context.exports.render
}

function compileReasonCodeHelper() {
  const result = ts.transpileModule(`const ${legacyReasons}; const ${reasonCodeHelper}; exports.reasonCode = scheduleReasonCodeFromPersisted;`, {
    compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS },
    reportDiagnostics: true,
  })
  assert.equal(result.diagnostics.length, 0)
  const context = { exports: {}, Set }
  vm.runInNewContext(result.outputText, context)
  return context.exports.reasonCode
}

function flattenText(node) {
  if (Array.isArray(node)) return node.map(flattenText).join(' ')
  if (!node || typeof node !== 'object') return typeof node === 'string' ? node : ''
  return flattenText(node.props?.children)
}

const persistedReasonCode = compileReasonCodeHelper()
assert.equal(persistedReasonCode('stopped_container', 'anything'), 'stopped_container')
assert.equal(persistedReasonCode(null, 'Container is stopped; scheduled update was skipped'), 'stopped_container')
assert.equal(persistedReasonCode(null, 'container was stopped before scheduled update could begin'), 'stopped_container')
assert.equal(persistedReasonCode('future_reason', 'raw diagnostic'), 'future_reason')
assert.equal(persistedReasonCode(null, 'raw diagnostic'), null)

for (const locale of ['en', 'sk']) {
  const messages = JSON.parse(fs.readFileSync(path.join(root, `messages/${locale}/common.json`), 'utf8'))
  const t = (key, variables = {}) => {
    const message = key.split('.').reduce((value, part) => value?.[part], messages)
    return String(message ?? key).replace(/\{([^}]+)\}/g, (_, name) => String(variables[name] ?? `{${name}}`))
  }
  const context = {
    exports: {}, t, selectedVM: { vmid: 100 }, scheduleLastRunAt: '2026-10-16T05:10:02Z',
    scheduleLastRunStatus: 'skipped', scheduleLastRunReasonCode: 'stopped_container',
    scheduleLastRunReason: 'container is stopped; scheduled update was skipped',
    scheduleLastRunRebootRequired: false, scheduleLastRunRebootPackages: [], scheduleLastRunLog: null,
    openScheduleLog() {}, AlertTriangle: 'AlertTriangle', FileText: 'FileText',
    require: () => ({ jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }), Fragment: 'Fragment' }),
  }
  const render = compile(context)
  const translated = flattenText(render(true))
  const expected = t('vmLxc.scheduled.reasonStoppedContainer')
  assert(translated.includes(expected), `${locale}: known reason code must use the locale catalog`)
  assert(!translated.includes(context.scheduleLastRunReason), `${locale}: raw stopped reason must not leak into UI`)

  context.scheduleLastRunReasonCode = 'unknown_reason'
  const fallback = flattenText(render(true))
  assert(fallback.includes(context.scheduleLastRunReason), `${locale}: unknown code must retain the raw diagnostic`)
}
console.log('PASS scheduled reason i18n: EN/SK structured stopped reason and raw fallback')
