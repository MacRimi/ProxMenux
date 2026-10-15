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
const actionStyle = compile(fs.readFileSync(path.join(root, "lib/update-action-style.ts"), "utf8"), { exports: {} })
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
const wanted = new Set(["checkOsUpdates", "getAggregateUpdateCheck", "renderLxcUpdateBadge", "openApplyTerminal", "handleVMControl"])
const definitions = []
const preferenceDefinitions = []
const status = []
let detailEffect
let resultEffect
let resultTimeout
let osApplyButton
let bulkApplyButton
let osSection
function walk(node) {
  if (ts.isJsxElement(node) && node.openingElement.tagName.getText(tree) === "div"
      && node.openingElement.attributes.properties.some(p => p.name?.getText(tree) === "className"
        && p.initializer?.getText(tree) === '"pb-4"')
      && node.getText(tree).includes('vmLxc.updates.osPackagesTitle')) osSection = node.getText(tree)
  if (ts.isJsxElement(node) && node.openingElement.tagName.getText(tree) === "Button"
      && node.openingElement.attributes.properties.some(p => p.name?.getText(tree) === "onClick"
        && p.initializer?.getText(tree).includes('openApplyTerminal(selectedVM.vmid, "os", { checkedOs: true })')))
    osApplyButton = node.getText(tree)
  if (ts.isJsxElement(node) && node.openingElement.tagName.getText(tree) === "Button"
      && node.openingElement.attributes.properties.some(p => p.name?.getText(tree) === "onClick"
        && p.initializer?.getText(tree).includes('applyBulkUpdate(selectedVM.vmid)')))
    bulkApplyButton = node.getText(tree)
  if (ts.isCallExpression(node) && node.expression.getText(tree) === "useEffect"
      && node.arguments[1]?.getText(tree) === "[selectedVM?.vmid]") {
    detailEffect = node.arguments[0].getText(tree)
  }
  if (ts.isCallExpression(node) && node.expression.getText(tree) === "useEffect"
      && node.arguments[1]?.getText(tree) === "[selectedVM, updatesRefreshing, updatesBaselineCount]")
    resultEffect = node.arguments[0].getText(tree)
  if (ts.isCallExpression(node) && node.expression.getText(tree) === "useEffect"
      && node.arguments[1]?.getText(tree) === "[updatesRefreshing]")
    resultTimeout = node.arguments[0].getText(tree)
  if (ts.isVariableDeclaration(node)) {
    const name = node.name.getText(tree)
    if (wanted.has(name)) definitions.push(`const ${node.getText(tree)};`)
    if (["applySchedulePayload", "loadSchedule", "loadBulkUpdate"].includes(name))
      preferenceDefinitions.push(`const ${node.getText(tree)};`)
    if (["osUpdateStale", "osUpdateStatusKnown", "hasOsUpdates"].includes(name))
      status.push(`const ${node.getText(tree)};`)
  }
  ts.forEachChild(node, walk)
}
walk(tree)
assert.equal(definitions.length, 5)
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
  getLxcOsUpdateState: o => helpers.getLxcOsUpdateState(o, now),
  getUpdateActionButtonClass: actionStyle.getUpdateActionButtonClass,
  refreshCheckLxcUpdates: async id => {
    if (errorToThrow) throw errorToThrow
    requests.push([`/api/vms/${id}/updates/refresh-check`, { method: "POST" }])
    return { ...recent, available: true, count: 2 }
  },
  fetchApi: async endpoint => { requests.push([endpoint]); return { config: { onboot: 1 }, os_info: { id: "debian" } } },
  mutate: async () => { polls++ },
  selectedVMRef: { current: { vmid: 100 } },
  osCheckRequestRef: { current: null },
  selectedVM: { vmid: 100 },
  setInterval: (callback, delay) => { context.detailTimer = { callback, delay }; return 1 },
  clearInterval: id => { context.clearedTimer = id },
  vmModalCacheRef: { current: { details: new Map(), backups: new Map(), mountPoints: new Map(), schedule: new Map(), firewall: new Map() } },
  setVMDetails: value => { details = value },
  setOsCheckingVmid: value => { checking = value },
  setOsCheckError: value => { displayedError = value },
  updatesRefreshing: true,
  updatesBaselineCount: 20,
  updatesBaselineCountRef: { current: 20 },
  setUpdatesResult: value => { context.updateResult = value },
  setUpdatesRefreshing: value => { context.refreshing = value },
  setUpdatesBaselineCount: value => { context.baseline = value },
  setTimeout: callback => { context.resultTimer = callback; return 2 },
  clearTimeout: () => {},
  Button: "Button", RefreshCw: "Refresh", confirm: () => context.confirmed,
  window: { crypto: { randomUUID: () => "ui-test-run" } },
  applyBackupStorage: "", selectedBackupStorage: "", backupStorages: [],
  osCheckingVmid: null, pendingBtnCls: "pending", upToDateBtnCls: "current", neutralBtnCls: "unknown",
  bulkApplying: false, bulkTargets: ["os", "app:test"], bulkHasPendingUpdates: true,
  bulkAllTargetsUpToDate: false, dockerInventoryRefreshing: false, dockerInventoryAvailable: true,
  controlLoading: false, Package: "Package", Shield: "Shield", CheckCircle2: "Current", AlertTriangle: "Unknown",
  osCheckError: null, uc: undefined, osUpdateStale: true,
  setControlLoading: value => { context.controlLoading = value },
  invalidateLxcApps: () => {}, setSelectedVM: value => { context.selectionChanged = value },
  alert: value => { context.alerted = value },
}
for (const name of ["Vmid", "Target", "RunId", "TargetIds", "TargetLabels", "UpdateCommand", "AppName",
    "RunHelper", "AllowHelperWithCustom", "DockerStandaloneTargets", "DockerEngine", "DockerRefresh",
    "BackupStorage", "StartedAt", "Open", "CheckAndUpdate", "CheckedOs"])
  context[`setApply${name}`] = value => { context[`apply${name}`] = value }
const ui = compile(definitions.join("\n") + `
exports.check = checkOsUpdates;
exports.aggregate = getAggregateUpdateCheck;
exports.badge = renderLxcUpdateBadge;
exports.osStatus = (uc) => { ${status.join("\n")} return { osUpdateStatusKnown, hasOsUpdates }; };
exports.revalidateDetails = ${detailEffect};
exports.settleResult = ${resultEffect};
exports.resultTimeout = ${resultTimeout};
exports.openApply = openApplyTerminal;
exports.osApplyButton = () => (${osApplyButton});
exports.bulkApplyButton = () => (${bulkApplyButton});
exports.osSection = () => (${osSection});
exports.control = handleVMControl;
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
context.updatesRefreshing = false
for (const [observation, expected] of [
  [undefined, "unknown"], [legacy, "unknown"], [{ ...recent, error: "failed" }, "unknown"],
  [{ ...recent, available: false }, "unknown"],
  [{ ...recent, available: true, count: 0 }, "unknown"],
  [{ ...recent, available: false, count: 0 }, "current"],
  [{ ...recent, available: true, count: 3 }, "pending"],
]) {
  assert.equal(helpers.getLxcOsUpdateState(observation, now), expected)
  context.selectedVMRef.current = { vmid: 100, status: "stopped", update_check: observation }
  context.selectedVM = context.selectedVMRef.current
  Object.assign(context, ui.osStatus(observation))
  context.applyOpen = false
  context.confirmed = true
  assert.equal(ui.osApplyButton().props.disabled, expected !== "pending")
  assert.equal(ui.bulkApplyButton().props.disabled, expected === "unknown")
  ui.openApply(100, "os")
  assert.equal(context.applyOpen, expected === "pending", "handler must enforce the same boundary as the button")
}
context.confirmed = false
context.applyOpen = false
ui.openApply(100, "os")
assert.equal(context.applyOpen, true, "an explicit installation click must not ask for a second stopped-guest confirmation")
const oldConfirm = context.confirm
let confirmationCalls = 0
context.confirm = () => { confirmationCalls++; return false }
for (const [target, options] of [
  ['os', { checkedOs: true }],
  ['both', { updateCommand: 'registered-app-update', targetIds: ['os', 'app:test'] }],
  ['app', { updateCommand: 'registered-app-update' }],
  ['app', { dockerEngine: true }],
  ['app', { dockerStandaloneTargets: ['registered-container'] }],
]) {
  context.applyOpen = false
  ui.openApply(100, target, options)
  assert.equal(context.applyOpen, true, `explicit ${target} update opens the terminal directly`)
}
assert.equal(confirmationCalls, 0, 'ordinary update entry points never open a browser confirmation')
assert(!source.includes('checkAndUpdate'), 'the abandoned combined check/install action has no UI path')
assert(!fs.existsSync(path.join(root, '../scripts/lxc/check_apply_updates.sh')))
context.confirm = oldConfirm
context.confirmed = true
context.applyOpen = false
context.osCheckingVmid = 100
ui.openApply(100, "os")
assert.equal(context.applyOpen, false, "checking cannot race an update launch")
context.osCheckingVmid = null
context.bulkAllTargetsUpToDate = true
assert.equal(ui.bulkApplyButton().props.disabled, true)
context.bulkAllTargetsUpToDate = false
context.confirmed = true
context.selectedVMRef.current = { vmid: 100, status: "stopped", update_check: { ...recent, available: false, count: 0 } }
ui.openApply(100, "both", { updateCommand: "app-updater", targetIds: ["os", "app:test"] })
assert.equal(context.applyOpen, true, "combined app update remains supported when OS packages are current")
assert.equal(context.applyUpdateCommand, "app-updater")
context.selectedVMRef.current = { vmid: 100, status: "running", update_check: { ...recent, error: "failed" } }
context.applyOpen = false
ui.openApply(100, "both")
assert.equal(context.applyOpen, false, "a combined plan cannot bypass unknown OS state")
ui.openApply(100, "app", { updateCommand: "app-updater" })
assert.equal(context.applyOpen, true, "app-only updates do not depend on OS package observation")
function collectButtons(node) {
  if (!node || typeof node !== "object") return []
  if (Array.isArray(node)) return node.flatMap(collectButtons)
  return [...(node.type === "Button" ? [node] : []), ...collectButtons(node.props?.children)]
}
function collectText(node) {
  if (typeof node === "string") return node
  if (!node || typeof node !== "object") return ""
  if (Array.isArray(node)) return node.map(collectText).join(" ")
  return collectText(node.props?.children)
}
for (const observation of [undefined, legacy, { ...recent, error: "check in progress" },
  { ...recent, available: false, count: 0 }, { ...recent, available: true, count: 3 }]) {
  context.selectedVM = { vmid: 100, status: "running" }
  context.uc = observation
  context.osUpdateStale = helpers.isLxcUpdateStale(observation, now)
  Object.assign(context, ui.osStatus(observation))
  context.osCheckingVmid = 100
  const rendered = ui.osSection()
  assert.match(collectText(rendered), /vmLxc\.updates\.checkInProgress/,
    "an active check takes precedence over old, missing and invalidated observations")
  assert.doesNotMatch(collectText(rendered), /osStatusUnavailable|osUpToDate|noPending/)
  assert.equal(collectButtons(rendered).length, 1, "hide the previous result during a check")
  context.osCheckingVmid = 211
  assert.doesNotMatch(collectText(ui.osSection()), /checkInProgress/,
    "another container's check cannot replace this container's result")
}
context.osCheckingVmid = null
context.uc = { ...recent, error: "check failed" }
Object.assign(context, ui.osStatus(context.uc))
assert.match(collectText(ui.osSection()), /osStatusUnavailable/, "completed failures remain visible")
for (const status of ["running", "stopped"]) {
  for (const observation of [undefined, legacy, { ...recent, error: 'read failed' },
    { ...recent, available: true, count: 0 },
    { ...recent, available: false, count: 0 }, { ...recent, available: true, count: 3 }]) {
    context.selectedVM = { vmid: 100, status, update_check: observation }
    context.selectedVMRef.current = context.selectedVM
    context.uc = observation
    context.osUpdateStale = helpers.isLxcUpdateStale(observation, now)
    Object.assign(context, ui.osStatus(observation))
    const buttons = collectButtons(ui.osSection())
    assert.equal(buttons.length, context.osUpdateStatusKnown ? 2 : 1,
      'retain the original bottom-right OS status when a verified zero is available')
    assert.equal(buttons[0].props.children[1], "vmLxc.updates.checkSystemPackages")
    if (context.osUpdateStatusKnown && !context.hasOsUpdates) {
      const currentStatus = buttons[1]
      assert.equal(currentStatus.props.asChild, true, 'current is a status, not an installation action')
      assert.equal(currentStatus.props.onClick, undefined)
      assert.equal(currentStatus.props.className, context.upToDateBtnCls)
      assert.equal(currentStatus.props.children.type, 'span')
      assert.equal(currentStatus.props.children.props.role, 'status')
      assert.equal(currentStatus.props.children.props.children, 'vmLxc.updates.osUpToDate')
    }
    assert.equal((osSection.match(/vmLxc\.updates\.refreshCheckHelp/g) || []).length, 1,
      'keep the explanation in the check tooltip without duplicating it as an inline paragraph')
    if (status === "stopped") {
      context.applyOpen = false
      context.confirmed = false
      ui.openApply(100, "os", { checkedOs: true })
      assert.equal(context.applyOpen, context.hasOsUpdates, "explicit OS installation has no second popup")
      if (context.hasOsUpdates) assert.equal(context.applyCheckedOs, true)
    }
  }
}
context.selectedVMRef.current = { vmid: 100, status: "running" }
context.updatesRefreshing = true
context.selectedVM = { update_check: { count: 0, error: "verification failed" } }
ui.settleResult()
assert.equal(context.updateResult, null, "unknown must not produce an all-updated banner")
context.selectedVMRef.current = context.selectedVM
ui.resultTimeout()
context.resultTimer()
assert.equal(context.updateResult, null, "timeout must not turn an unknown observation into success")
context.selectedVM = { update_check: { count: 0, error: null } }
ui.settleResult()
assert.equal(context.updateResult.pendingAfter, 0)
assert.equal(context.updateResult.appliedCount, 20)
context.selectedVM = { vmid: 100 }
context.selectedVMRef.current = { vmid: 100 }

;(async () => {
  // Execute the actual loaders with delayed GETs to test guest isolation.
  const preferenceState = {}
  const pendingReads = []
  const preferenceContext = {
    exports: {}, CRON_PRESETS: [{ value: "daily-3am", cron: "0 3 * * *" }],
    selectedVMRef: { current: { vmid: 213 } },
    scheduleLoadRequestRef: { current: 0 }, bulkLoadRequestRef: { current: 0 },
    vmModalCacheRef: { current: { schedule: new Map() } },
    t: key => key,
    fetchApi: (url, options) => new Promise((resolve, reject) => {
      assert.equal(options, undefined, "loading preferences never writes or starts an update")
      pendingReads.push({ url, resolve, reject })
    }),
  }
  for (const name of ["ScheduleEnabled", "ScheduleConfigured", "ScheduleCron", "SchedulePreset",
    "ScheduleTarget", "ScheduleTargets", "ScheduleReleaseDelayDays", "ApplyBackup", "ApplyBackupStorage",
    "ApplyRestart", "ScheduleLastRunAt", "ScheduleLastRunStatus", "ScheduleLastRunReason", "ScheduleLastRunLog",
    "ScheduleLastRunRebootRequired", "ScheduleLastRunRebootPackages", "ExternalCron", "ScheduleError",
    "ScheduleLoaded", "BulkError", "BulkLoaded", "BulkEditMode", "BulkConfigured", "BulkTargets", "BulkPersistedTargets"])
    preferenceContext[`set${name}`] = value => { preferenceState[name] = value }
  assert.equal(preferenceDefinitions.length, 3)
  const preferences = compile(preferenceDefinitions.join("\n") + `
    exports.apply = applySchedulePayload; exports.schedule = loadSchedule; exports.bulk = loadBulkUpdate;
  `, preferenceContext)
  preferences.apply({ backup: true, backup_storage: "local", restart: true })
  preferences.apply({})
  assert.equal(preferenceState.ApplyBackup, false, "a guest without saved options cannot inherit backup")
  assert.equal(preferenceState.ApplyBackupStorage, "", "missing storage clears another guest's choice")
  assert.equal(preferenceState.ApplyRestart, false, "missing restart cannot inherit a reboot")
  preferences.apply({ backup: false, backup_storage: "", restart: false })
  assert.equal(preferenceState.ApplyBackupStorage, "")
  preferenceContext.vmModalCacheRef.current.schedule.set(213, { backup: true, backup_storage: "local", restart: true })
  const previousSchedule = preferences.schedule(213)
  assert.equal(preferenceState.ApplyBackup, true, "use only the selected guest's own cache")
  preferenceContext.selectedVMRef.current = { vmid: 210 }
  const currentSchedule = preferences.schedule(210)
  assert.equal(preferenceState.ApplyBackup, false, "clear inherited options before the GET completes")
  assert.equal(preferenceState.ApplyRestart, false)
  pendingReads[1].resolve({})
  await currentSchedule
  pendingReads[0].resolve({ backup: true, backup_storage: "wrong", restart: true })
  await previousSchedule
  assert.equal(preferenceState.ApplyBackup, false)
  assert.equal(preferenceState.ScheduleLoaded, 210, "old completion cannot mark another guest loaded")
  const older = preferences.schedule(210)
  const newer = preferences.schedule(210)
  pendingReads[3].resolve({ backup: true, backup_storage: "new", restart: false })
  await newer
  pendingReads[2].resolve({ backup: false, backup_storage: "old", restart: true })
  await older
  assert.equal(preferenceState.ApplyBackupStorage, "new", "only the latest request may publish preferences")
  assert.equal(preferenceState.ApplyRestart, false)
  const closed = preferences.schedule(210)
  const closedState = JSON.stringify(preferenceState)
  preferenceContext.selectedVMRef.current = null
  pendingReads[4].reject(new Error("old guest failure"))
  await closed
  assert.equal(JSON.stringify(preferenceState), closedState, "closing the modal forbids late error and loaded writes")
  preferenceContext.selectedVMRef.current = { vmid: 213 }
  const oldBulk = preferences.bulk(213)
  preferenceContext.selectedVMRef.current = { vmid: 210 }
  const newBulk = preferences.bulk(210)
  pendingReads[6].resolve({ targets: ["os", "app:ghstats"] })
  await newBulk
  pendingReads[5].resolve({ targets: ["os", "docker-engine"] })
  await oldBulk
  assert.equal(JSON.stringify(preferenceState.BulkTargets), '["os","app:ghstats"]')
  assert.equal(preferenceState.BulkLoaded, 210)
  const oldBulkSameGuest = preferences.bulk(210)
  const newBulkSameGuest = preferences.bulk(210)
  pendingReads[8].resolve({ targets: ["os", "docker-engine"] })
  await newBulkSameGuest
  pendingReads[7].reject(new Error("superseded bulk failure"))
  await oldBulkSameGuest
  assert.equal(preferenceState.BulkError, null)
  assert.equal(JSON.stringify(preferenceState.BulkTargets), '["os","docker-engine"]')
  const failedSchedule = preferences.schedule(210)
  pendingReads[9].resolve(null)
  await failedSchedule
  assert.equal(preferenceState.ScheduleError, "vmLxc.scheduled.loadFailed", "invalid responses are failed reads")
  const failedBulk = preferences.bulk(210)
  pendingReads[10].resolve([])
  await failedBulk
  assert.equal(preferenceState.BulkError, "vmLxc.bulkUpdate.loadFailed")
  const closedBulk = preferences.bulk(210)
  const closedBulkState = JSON.stringify(preferenceState)
  preferenceContext.selectedVMRef.current = null
  pendingReads[11].resolve({ targets: ["os", "app:wrong-guest"] })
  await closedBulk
  assert.equal(JSON.stringify(preferenceState), closedBulkState)
  const readsBeforeClosedLoad = pendingReads.length
  await preferences.schedule(210)
  await preferences.bulk(210)
  assert.equal(pendingReads.length, readsBeforeClosedLoad, "an unselected guest cannot start a preferences GET")
  assert(pendingReads.every(read => /\/(schedule|bulk-update)$/.test(read.url)), "no guest or updater routes")
  // Exercise the real separate helper: POST submits, GET waits, no apply.
  const io = []
  let jobState = 'running'
  const jobHelpers = compile(fs.readFileSync(path.join(root, 'lib/lxc-update-observation.ts'), 'utf8'), {
    exports: {}, Date, setTimeout: callback => { jobState = 'complete'; callback() },
    require: () => ({ fetchApi: async (url, opts) => {
      io.push([url, opts])
      if (opts?.method === 'POST') return { job_id: 'check-only' }
      return { state: jobState, update_check: { count: 0, available: false }, error: 'index failed' }
    } }),
  })
  assert.equal((await jobHelpers.refreshCheckLxcUpdates(100)).count, 0)
  assert.equal(io[0][0], '/api/vms/100/updates/refresh-check')
  assert.equal(io.filter(entry => entry[1]?.method === 'POST').length, 1)
  assert(io.slice(1).every(entry => entry[0].endsWith('/refresh-check/check-only')))
  jobState = 'failed'
  await assert.rejects(jobHelpers.refreshCheckLxcUpdates(100), /osStatusUnavailable/)
  io.length = 0
  await jobHelpers.checkLxcUpdates(100)
  assert.equal(io[0][0], '/api/vms/100/updates/check', 'legacy helper retains read-only endpoint')
  context.applyOpen = false
  context.updatesRefreshing = false
  await ui.check(100)
  assert.equal(requests[0][0], "/api/vms/100/updates/refresh-check")
  assert.equal(requests[0][1].method, "POST")
  assert.equal(requests[1][0], "/api/vms/100")
  assert.equal(polls, 2)
  assert.equal(details.os_info.id, "debian")
  assert.equal(checking, null)
  errorToThrow = new Error('raw transport error must not appear in translated UI')
  await ui.check(100)
  assert.equal(displayedError, 'vmLxc.updates.osStatusUnavailable')
  errorToThrow = new Error('checkStillRunning')
  await ui.check(100)
  assert.equal(displayedError, 'vmLxc.updates.checkStillRunning')
  const before = requests.length
  errorToThrow = { status: 429, body: { retry_after: 60 } }
  await ui.check(100)
  assert.match(displayedError, /checkCooldown.*60/)
  assert.equal(checking, null)
  assert.equal(requests.length, before)
  assert.equal(polls, 2)
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
    for (const key of ["checkNow", "checkReadOnlyHelp", "checkCooldown", "checkStale", "checkStaleHelp",
      "checkBeforeUpdate", "startBeforeCheck", "notCheckedYet",
      "checkStillRunning"])
      assert.ok(messages[key]?.trim())
    assert.match(messages.checkCooldown, /\{seconds\}/)
  }
  console.log("PASS observed-state UI: freshness, safe actions, per-guest preferences/bulk races, EN/SK")
})().catch(error => { console.error(error); process.exitCode = 1 })
