// Execute actual UI helpers, button handler and badge render with fake I/O.
const assert = require("node:assert/strict")
const fs = require("node:fs")
const path = require("node:path")
const vm = require("node:vm")
const root = path.resolve(__dirname, "../../AppImage")
const ts = require(path.join(root, "node_modules/typescript"))

function compile(source, context) {
  const result = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
  }, reportDiagnostics: true })
  assert.equal(result.diagnostics.length, 0)
  vm.runInNewContext(result.outputText, context)
  return context.exports
}

const requests = []
const helpers = compile(fs.readFileSync(path.join(root, "lib/lxc-update-observation.ts"), "utf8"), {
  exports: {}, require: () => ({ fetchApi: async (...args) => { requests.push(args); return {} } }),
})
assert.equal(requests.length, 0, "loading helpers never schedules a package check")
const now = Date.parse("2026-10-13T12:00:00Z")
const recent = { last_check: "2026-10-13T11:59:00Z" }
assert.equal(helpers.isLxcUpdateStale(recent, now), false)
for (const value of [undefined, {}, { last_check: "bad" }, { last_check: "2026-10-14T00:00:00Z" },
  { last_check: "2026-10-11T12:00:00Z" }, { ...recent, stale: true }]) {
  assert.equal(helpers.isLxcUpdateStale(value, now), true)
}
for (const age of [86400, 86400 + 600, 172799]) {
  assert.equal(helpers.isLxcUpdateStale({ last_check: new Date(now - age * 1000).toISOString() }, now), false,
    'daily checks have a full extra day of freshness margin')
}
assert.equal(helpers.isLxcUpdateStale({ ...recent, stale_after_seconds: 60 }, now), true,
  'the backend-provided threshold still takes precedence')
for (const lang of ['en', 'sk']) {
  const catalog = JSON.parse(fs.readFileSync(path.join(root, `messages/${lang}/common.json`), 'utf8'))
  assert.match(catalog.vmLxc.updates.checkStaleHelp, /48/)
}

const source = fs.readFileSync(path.join(root, "components/virtual-machines.tsx"), "utf8")
const tree = ts.createSourceFile("vm.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
assert.equal(tree.parseDiagnostics.length, 0)
const wanted = new Set(["checkOsUpdates", "getAggregateUpdateCheck", "renderLxcUpdateBadge"])
const definitions = []
const status = []
let detailEffect
function walk(node) {
  if (ts.isCallExpression(node) && node.expression.getText(tree) === "useEffect"
      && node.arguments[1]?.getText(tree) === "[selectedVM?.vmid]") {
    detailEffect = node.arguments[0].getText(tree)
  }
  if (ts.isVariableDeclaration(node)) {
    const name = node.name.getText(tree)
    if (wanted.has(name)) definitions.push(`const ${node.getText(tree)};`)
    if (["osUpdateStale", "osUpdateStatusKnown", "hasOsUpdates"].includes(name))
      status.push(`const ${node.getText(tree)};`)
  }
  ts.forEachChild(node, walk)
}
walk(tree)
assert.equal(definitions.length, 3)
assert.equal(status.length, 3)
assert.ok(detailEffect)
let checking = null
let displayedError = null
let details = null
let errorToThrow = null
let polls = 0
const context = {
  exports: {},
  require: () => ({ jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) }),
  Badge: "Badge", Clock: "Clock", ArrowUpCircle: "Arrow", ChevronRight: "Chevron",
  t: (key, args) => key + (args ? JSON.stringify(args) : ""),
  isLxcUpdateStale: o => helpers.isLxcUpdateStale(o, now),
  checkLxcUpdates: async id => {
    if (errorToThrow) throw errorToThrow
    return helpers.checkLxcUpdates(id)
  },
  fetchApi: async endpoint => { requests.push([endpoint]); return { config: { onboot: 1 }, os_info: { id: "debian" } } },
  mutate: async () => { polls++ },
  selectedVMRef: { current: { vmid: 100 } },
  selectedVM: { vmid: 100 },
  setInterval: (callback, delay) => { context.detailTimer = { callback, delay }; return 1 },
  clearInterval: id => { context.clearedTimer = id },
  vmModalCacheRef: { current: { details: new Map() } },
  setVMDetails: value => { details = value },
  setOsCheckingVmid: value => { checking = value },
  setOsCheckError: value => { displayedError = value },
}
const ui = compile(definitions.join("\n") + `
exports.check = checkOsUpdates;
exports.aggregate = getAggregateUpdateCheck;
exports.badge = renderLxcUpdateBadge;
exports.osStatus = (uc) => { ${status.join("\n")} return { osUpdateStatusKnown, hasOsUpdates }; };
exports.revalidateDetails = ${detailEffect};
`, context)
const legacy = { last_check: "2026-10-12T00:00:00Z", available: true, count: 51, stale: true }
assert.equal(ui.osStatus(legacy).osUpdateStatusKnown, false, "old count must not claim live OS status")
assert.equal(ui.osStatus({ ...recent, available: false, count: 0 }).osUpdateStatusKnown, true)
assert.equal(ui.osStatus({ ...recent, error: "probe failed" }).osUpdateStatusKnown, false)
assert.equal(ui.aggregate({ app_watches: [{ update_available: true, name: "App" }] }).last_check, null,
  "an app badge cannot invent an OS check timestamp")
assert.equal(ui.badge(legacy).props.children[0].type, "Clock")
assert.equal(ui.badge(legacy).props.children[1], "vmLxc.updates.checkStale")
assert.equal(ui.badge({ ...recent, available: true, count: 2 }).props.children[1], 2)
assert.equal(ui.badge({ ...recent, available: false, count: 0 }), null)
assert.equal(requests.length, 0)

;(async () => {
  await ui.check(100)
  assert.equal(requests[0][0], "/api/vms/100/updates/check")
  assert.equal(requests[0][1].method, "POST")
  assert.equal(requests[1][0], "/api/vms/100")
  assert.equal(polls, 1)
  assert.equal(details.os_info.id, "debian")
  assert.equal(checking, null)
  const before = requests.length
  errorToThrow = { status: 429, body: { retry_after: 60 } }
  await ui.check(100)
  assert.match(displayedError, /checkCooldown.*60/)
  assert.equal(checking, null)
  assert.equal(requests.length, before)
  assert.equal(polls, 1)
  // Switching guests while a request runs must not replace another modal.
  errorToThrow = null
  context.selectedVMRef.current = { vmid: 200 }
  details = null
  await ui.check(100)
  assert.equal(details, null)
  errorToThrow = { status: 429, body: { retry_after: 60 } }
  displayedError = null
  await ui.check(100)
  assert.equal(displayedError, null, "errors from the previous guest cannot leak into another modal")
  const beforeTimer = requests.length
  const cleanup = ui.revalidateDetails()
  assert.equal(context.detailTimer.delay, 30000)
  assert.equal(requests.length, beforeTimer, "mounting the detail effect does not check packages")
  await context.detailTimer.callback()
  assert.equal(requests.length, beforeTimer + 1)
  assert.equal(requests.at(-1)[0], "/api/vms/100")
  cleanup()
  assert.equal(context.clearedTimer, 1)
  for (const locale of ["en", "sk"]) {
    const messages = JSON.parse(fs.readFileSync(path.join(root, `messages/${locale}/common.json`))).vmLxc.updates
    for (const key of ["checkNow", "checkReadOnlyHelp", "checkCooldown", "checkStale", "checkStaleHelp"])
      assert.ok(messages[key]?.trim())
    assert.match(messages.checkCooldown, /\{seconds\}/)
  }
  console.log("PASS observed-state UI: freshness, badges, safe button, cooldown, modal isolation, EN/SK")
})().catch(error => { console.error(error); process.exitCode = 1 })
