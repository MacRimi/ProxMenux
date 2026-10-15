// Exercise actual shared-cache and badge code, without a browser or API.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const root = path.resolve(__dirname, '../../AppImage')
const ts = require(path.join(root, 'node_modules/typescript'))
function compile(source, context) {
  const result = ts.transpileModule(source, {compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
  }, reportDiagnostics: true})
  assert.equal(result.diagnostics.length, 0)
  vm.runInNewContext(result.outputText, context)
  return context.exports
}
let requests = 0
const cache = compile(fs.readFileSync(path.join(root, 'lib/lxc-apps-cache.ts'), 'utf8'), {
  exports: {}, require: () => ({fetchApi: () => { requests++; throw new Error('unexpected HTTP') }}),
})
const app = {id: 'one', update_via: 'docker', container_name: 'example', state: {installed_version: '1.0'}}
cache.setLxcAppsCached(101, {_revision: 10, apps: [app]})
const watch = {...app, state_revision: 10, installed_version: '1.0', docker_image_reference: 'example:latest',
  docker_available_version: '2.0', docker_update_available: true, docker_binding_error: null}
cache.syncLxcAppsState(101, [watch])
assert.equal(cache.getLxcAppsCached(101).sidecar.apps[0].docker_available_version, '2.0')
cache.syncLxcAppsState(101, [{...watch, docker_available_version: '2.1'}])
assert.equal(cache.getLxcAppsCached(101).sidecar.apps[0].docker_available_version, '2.1', 'metadata changes without a new app probe')
cache.syncLxcAppsState(101, [{...watch, docker_available_version: null, docker_update_available: null, docker_binding_error: 'inventory_unavailable'}])
assert.equal(cache.getLxcAppsCached(101).sidecar.apps[0].docker_available_version, null)
cache.setLxcAppsCached(101, {_revision: 11, apps: [{...app, container_name: 'replacement'}]})
cache.syncLxcAppsState(101, [watch])
assert.equal(cache.getLxcAppsCached(101).sidecar.apps[0].docker_available_version, undefined, 'old observation cannot decorate edited registration')
assert.equal(requests, 0)

const source = fs.readFileSync(path.join(root, 'components/virtual-machines.tsx'), 'utf8')
assert.match(
  source,
  /const independentlyUpdatedApps = registeredApps\.filter\(\s*\(a\) => a\.update_via !== "docker",\s*\)/,
  'Docker-delegated apps must not render a second Updates section',
)
assert.match(
  source,
  /image\.update_available === false \? "text-green-500" : "text-foreground\/80"/,
  'a current Docker image must show its installed version in green',
)
const tree = ts.createSourceFile('vm.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
const pieces = []
function walk(node) {
  if (ts.isFunctionDeclaration(node) && node.name?.text === 'hasLxcPendingUpdates') pieces.push(node.getText(tree))
  if (ts.isVariableDeclaration(node) && node.name.getText(tree) === 'getAggregateUpdateCheck') pieces.push(`const ${node.getText(tree)};`)
  ts.forEachChild(node, walk)
}
walk(tree)
assert.equal(pieces.length, 2)
const badges = compile(pieces.join('\n') + '\nexports.aggregate = getAggregateUpdateCheck; exports.pending = hasLxcPendingUpdates;', {exports: {}})
const guest = {type: 'lxc', app_watches: [{...watch, name: 'First'}, {...watch, id: 'two', name: 'Second'}]}
assert.equal(badges.pending(guest), true)
assert.equal(badges.aggregate(guest).count, 1, 'two apps in one image count once')
assert.equal(badges.aggregate(guest).packages.length, 1)
guest.app_watches.push({id: 'engine', helper_slug: 'docker'})
guest.docker_inventory = {update_count: 1, images: [{reference: 'example:latest', update_available: true}]}
assert.equal(badges.aggregate(guest).count, 1, 'registering Engine does not double count image')

for (const locale of ['en', 'es', 'de', 'fr', 'it', 'pt', 'sk', 'sv']) {
  const messages = JSON.parse(fs.readFileSync(path.join(root, `messages/${locale}/common.json`)))
  for (const key of ['updatedWithDockerImage', 'dockerBindingUnavailable']) assert.equal(typeof messages.vmLxc.updates[key], 'string')
  for (const key of ['dockerWorkloadsHeading', 'runsInsideDocker', 'upstreamDelegatedTitle', 'upstreamDelegatedHelp']) assert.equal(typeof messages.vmLxc.appEditor[key], 'string')
}
console.log('PASS Docker delegation: live cache, lifecycle invalidation, edit protection, no extra HTTP, unique image counts, eight locales')

// Exercise the actual bulk-choice construction, keeping target identities
// intact while distinguishing a custom updater from a same-named image.
const choicesSource = source.slice(source.indexOf('const bulkAppChoices ='), source.indexOf('const bulkChoiceIds ='))
assert(choicesSource.startsWith('const bulkAppChoices ='))
for (const locale of ['en', 'sk']) {
  const messages = JSON.parse(fs.readFileSync(path.join(root, `messages/${locale}/common.json`)))
  const t = (key, values = {}) => {
    const value = key.split('.').reduce((obj, part) => obj?.[part], messages)
    assert.equal(typeof value, 'string', key)
    return value.replace(/\{(\w+)\}/g, (_, name) => values[name] ?? '')
  }
  const registeredApps = [
    {id: 'custom', name: 'ghstats', update_command: 'existing updater'},
    {id: 'helper', name: 'Helper app', update_method: 'helper', helper_slug: 'helper-app'},
    {id: 'unique', name: 'Only custom', update_command: 'another updater'},
    {id: 'engine', name: 'Docker', helper_slug: 'docker'},
  ].map(Object.freeze)
  const units = [
    {id: 'docker-unit:ghstats', kind: 'standalone', display_name: 'ghstats', dependent_services: []},
    {id: 'docker-unit:helper', kind: 'compose', display_name: 'Helper app', dependent_services: ['database']},
    {id: 'docker-unit:unique', kind: 'standalone', display_name: 'Only image', dependent_services: []},
  ].map(Object.freeze)
  const before = JSON.stringify({registeredApps, units})
  const result = compile(choicesSource + '\nexports.choices = bulkChoices;', {
    exports: {}, t, registeredApps, helperExists: true, uc: {helper_slug: 'helper-app'},
    dockerWorkloadsRegistered: true, dockerRegistered: true,
    selectedVM: {docker_inventory: {update_units: units}}, followedImageReferences: new Set(),
  }).choices
  assert.deepEqual(Array.from(result, x => x.id), ['os', 'app:custom', 'app:helper', 'app:unique',
    'docker-engine', 'docker-unit:ghstats', 'docker-unit:helper', 'docker-unit:unique'])
  assert.equal(result.find(x => x.id === 'app:custom').label, `ghstats — ${t('vmLxc.updates.customCommandTitle')}`)
  assert.equal(result.find(x => x.id === 'docker-unit:ghstats').label, `ghstats — ${t('vmLxc.bulkUpdate.dockerImageMethod')}`)
  assert.equal(result.find(x => x.id === 'app:helper').label, `Helper app — ${t('vmLxc.updates.helperMethod')}`)
  assert.equal(result.find(x => x.id === 'docker-unit:helper').label, 'Helper app — Docker Compose')
  assert.equal(result.find(x => x.id === 'app:unique').label, 'Only custom')
  assert.equal(result.find(x => x.id === 'docker-unit:unique').label, 'Only image')
  assert.equal(result.find(x => x.id === 'docker-unit:helper').detail,
    t('vmLxc.bulkUpdate.includesDependencies', {names: 'database'}))
  assert.equal(JSON.stringify({registeredApps, units}), before, 'display must never edit registrations or units')
  assert.equal(typeof messages.vmLxc.bulkUpdate.osDockerScope, 'string')
}
console.log('PASS bulk display: duplicate method names, unchanged unique names/target IDs/dependencies and frozen input, EN/SK')

const actionStyle = compile(fs.readFileSync(path.join(root, 'lib/update-action-style.ts'), 'utf8'), {exports: {}})
let bulkButton
function findBulkButton(node) {
  if (ts.isJsxElement(node) && node.openingElement.tagName.getText(tree) === 'Button') {
    const props = node.openingElement.attributes.properties
    if (props.some(p => ts.isJsxAttribute(p) && p.name.text === 'onClick'
      && p.initializer?.getText(tree).includes('applyBulkUpdate('))) bulkButton = props
  }
  ts.forEachChild(node, findBulkButton)
}
findBulkButton(tree)
assert(bulkButton, 'actual bulk execution button exists')
function bulkProp(name, context) {
  const prop = bulkButton.find(p => p.name?.text === name)
  assert(prop && ts.isJsxExpression(prop.initializer))
  return compile('exports.value = (' + prop.initializer.expression.getText(tree) + ');', {
    exports: {}, getUpdateActionButtonClass: actionStyle.getUpdateActionButtonClass, ...context,
  }).value
}
const enabledBulk = {bulkApplying: false, osCheckingVmid: null, updatesRefreshing: false,
  osUpdateStatusKnown: true, bulkAllTargetsUpToDate: false, bulkHasPendingUpdates: true,
  bulkTargets: ['os', 'app:one'], dockerInventoryRefreshing: false, dockerInventoryAvailable: true}
assert.equal(bulkProp('disabled', enabledBulk), false)
assert.match(bulkProp('className', enabledBulk), /text-purple-300/)
const unknownBulk = {...enabledBulk, osUpdateStatusKnown: false, bulkHasPendingUpdates: false}
assert.equal(bulkProp('disabled', unknownBulk), true, 'consistent action color must not enable an unknown OS')
assert.equal(bulkProp('className', unknownBulk), bulkProp('className', enabledBulk))
const currentBulk = {...enabledBulk, bulkAllTargetsUpToDate: true, bulkHasPendingUpdates: false}
assert.equal(bulkProp('disabled', currentBulk), true)
assert.match(bulkProp('className', currentBulk), /text-green-400/)
assert.equal(bulkProp('disabled', {...enabledBulk, bulkApplying: true}), true)
assert.equal(bulkProp('disabled', {...enabledBulk, bulkTargets: ['os', 'docker-unit:one'],
  dockerInventoryAvailable: false}), true)
const helperLabelSource = source.slice(source.indexOf('const cls = getUpdateActionButtonClass(hasUpd'),
  source.indexOf('const cls = getUpdateActionButtonClass(hasUpd') + 550)
const helperLabel = helperLabelSource.slice(0, helperLabelSource.indexOf('return ('))
const unknownHelper = compile(helperLabel + '\nexports.value = {cls, label};', {
  exports: {}, hasUpd: false, upToD: false, t: k => k,
  getUpdateActionButtonClass: actionStyle.getUpdateActionButtonClass,
}).value
assert.match(unknownHelper.cls, /text-purple-300/)
assert.equal(unknownHelper.label, 'vmLxc.updates.runUpdater', 'unknown version must not be presented as a detected upgrade')
console.log('PASS actual update actions: shared author colors, unknown remains unknown, bulk guards unchanged')
