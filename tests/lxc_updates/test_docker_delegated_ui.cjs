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
