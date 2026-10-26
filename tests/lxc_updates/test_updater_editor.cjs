// Exercise the actual selector with a tiny JSX/hook harness; no browser or API.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const {spawnSync} = require('node:child_process')
const os = require('node:os')
const root = path.resolve(__dirname, '../../AppImage')
const ts = require(path.join(root, 'node_modules/typescript'))
const source = fs.readFileSync(path.join(root, 'components/app-updater-editor.tsx'), 'utf8')
const result = ts.transpileModule(source, {compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
}, reportDiagnostics: true})
assert.equal(result.diagnostics.length, 0)
const flatten = node => !node || typeof node !== 'object' ? [] : [node, ...(
  [node.props?.children].flat(Infinity).flatMap(flatten)
)]

// Check the real shared Button and cn/tailwind-merge, not only editor props.
function loadSource(relative) {
  const compiled = ts.transpileModule(fs.readFileSync(path.join(root, relative), 'utf8'), {
    compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX},
  })
  const context = {exports: {}, require: name => name === '@/lib/utils'
    ? loadSource('lib/utils.ts') : require(path.join(root, 'node_modules', name))}
  vm.runInNewContext(compiled.outputText, context)
  return context.exports
}
const actualButton = loadSource('components/ui/button.tsx').Button
const navbarSource = fs.readFileSync(path.join(root, 'components/proxmox-dashboard.tsx'), 'utf8')
const appPanelSource = fs.readFileSync(path.join(root, 'components/lxc-app-panel.tsx'), 'utf8')
function assertSaveContrast(save) {
  const dom = actualButton.render(save.props, null)
  assert.equal(dom.props.disabled, save.props.disabled)
  assert.match(dom.props.className, /\btext-white\b/)
  assert.match(dom.props.className, /disabled:opacity-50/)
  assert(!dom.props.className.includes('disabled:opacity-100'), 'retain the shared disabled appearance')
  assert(!dom.props.className.includes('disabled:bg-blue-800'), 'do not override the disabled background')
  const background = dom.props.className.split(' ').find(token => /^bg-blue-\d+$/.test(token))
  assert.equal(background, 'bg-blue-500')
  assert(navbarSource.includes(`data-[state=active]:${background}`), 'match the active navigation tab blue')
}
let englishEditor

for (const locale of ['en', 'es', 'de', 'fr', 'it', 'pt', 'sk', 'sv']) {
  const messages = JSON.parse(fs.readFileSync(path.join(root, `messages/${locale}/common.json`)))
  let help = null
  const t = key => {
    const value = key.split('.').reduce((object, part) => object?.[part], messages)
    assert.equal(typeof value, 'string', `${locale}: missing ${key}`)
    return value
  }
  const context = {exports: {}, require: name => {
    if (name === 'react') return {useId: () => 'test-command', useState: () => [help, value => {help = value}]}
    if (name === 'react/jsx-runtime') return {jsx: (type, props) => ({type, props}), jsxs: (type, props) => ({type, props})}
    if (name === '@/lib/i18n/provider') return {useT: () => t}
    return new Proxy({}, {get: (_, key) => String(key)})
  }}
  vm.runInNewContext(result.outputText, context)
  if (locale === 'en') englishEditor = context.exports.AppUpdaterEditor
  let saves = 0, method = 'none', command = ''
  const props = {method, command, helperAvailable: true, helperSlug: 'qbittorrent', configured: false,
    saving: false, changed: true, onMethodChange: value => {method = value}, onCommandChange: value => {command = value},
    onSave: () => {saves++}, onCancel: () => {}, onRemove: () => {}}
  const render = overrides => flatten(context.exports.AppUpdaterEditor({...props, method, command, ...overrides}))
  let tree = render()
  if (locale === 'es') assert.equal(t('vmLxc.updates.updaterChoiceHint'), 'Elige y guarda un método de actualización.')
  assert.equal(tree.filter(n => n.props['aria-pressed'] === true).length, 0)
  assert.equal(tree.filter(n => n.type === 'Textarea').length, 0)
  let save = tree.find(n => n.type === 'Button' && n.props.onClick === props.onSave)
  assert.equal(save.props.disabled, true)
  assert.match(save.props.className, /bg-blue-500/)
  assert.match(save.props.className, /hover:bg-blue-600/)
  assert.match(save.props.className, /text-white/)
  assertSaveContrast(save)
  const helperButton = tree.find(n => n.type === 'Button' && n.props.children === t('vmLxc.updates.helperMethod'))
  helperButton.props.onClick()
  assert.equal(method, 'helper')
  assert.equal(saves, 0, 'selecting must not execute or save')
  tree = render()
  const helperField = tree.find(n => n.type === 'Textarea')
  const canonicalHelper = helperField.props.value
  assert.equal(canonicalHelper, 'PHS_SILENT=1 bash -c "$(curl -fsSL https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/ct/qbittorrent.sh)"')
  assert(!canonicalHelper.includes('_proxmenux_updater'), 'internal guards must not appear in the editor')
  assert(!helperField.props.readOnly, 'the helper launcher must be editable')
  helperField.props.onChange({target: {value: canonicalHelper}})
  assert.equal(method, 'helper', 'an unchanged launcher remains the official method')
  const editedHelper = canonicalHelper.replace('PHS_SILENT=1', 'PHS_SILENT=0')
  helperField.props.onChange({target: {value: editedHelper}})
  assert.equal(method, 'custom', 'editing must route execution through the saved custom command')
  assert.equal(command, editedHelper)
  assert.equal(render().find(n => n.type === 'Textarea').props.value, editedHelper)
  helperButton.props.onClick()
  assert.equal(render().find(n => n.type === 'Textarea').props.value, canonicalHelper)
  assert.equal(command, editedHelper, 'switching back to helper preserves the unsaved custom draft')
  command = ''
  tree = render()
  assert.equal(tree.find(n => n.props.onClick === props.onSave).props.disabled, false)
  assertSaveContrast(tree.find(n => n.props.onClick === props.onSave))
  for (const overrides of [{saving: true}, {changed: false}]) {
    const disabledSave = render(overrides).find(n => n.props.onClick === props.onSave)
    assert.equal(disabledSave.props.disabled, true)
    assertSaveContrast(disabledSave)
  }
  const helperInfo = tree.find(n => n.props['aria-label'] === t('vmLxc.updates.helperMethodHelp'))
  assert.match(helperInfo.props.className, /text-blue-500/)
  helperInfo.props.onClick()
  tree = render()
  assert.equal(tree.find(n => n.type === 'Dialog').props.open, true)
  assert(tree.some(n => n.type === 'a' && n.props.href.endsWith('/ct/qbittorrent.sh')))
  assert(tree.some(n => n.type === 'a' && n.props.href === 'https://community-scripts.org/docs/tools/pve/update-apps'))
  const helperLinks = tree.filter(n => n.type === 'a')
  assert.equal(helperLinks.length, 2)
  for (const link of helperLinks) {
    assert.match(link.props.className, /text-blue-400 hover:text-blue-300/)
    assert(appPanelSource.includes('text-blue-400 hover:text-blue-300'), 'use the same colors as the App web links')
  }
  assert(tree.some(n => n.type === 'code' && n.props.children === canonicalHelper))
  assert(!render({helperSlug: "bad'; touch /tmp/injected"}).some(n => n.type === 'code'))
  assert(!render({helperSlug: undefined}).some(n => n.type === 'code'))
  assert.equal(tree.filter(n => n.type === 'Textarea').length, 1)
  assert.equal(render({helperSlug: undefined}).find(n => n.props.onClick === props.onSave).props.disabled, true)
  const customInfo = tree.find(n => n.props['aria-label'] === t('vmLxc.updates.customMethodHelp'))
  assert.match(customInfo.props.className, /text-blue-500/)
  customInfo.props.onClick()
  tree = render()
  const headingIndex = tree.findIndex(n => n.type === 'p' && n.props.children === t('vmLxc.updates.customExamplesHeading'))
  const descriptionIndex = tree.findIndex(n => n.type === 'DialogDescription')
  const firstExampleIndex = tree.findIndex(n => n.type === 'code')
  assert(headingIndex > descriptionIndex && headingIndex < firstExampleIndex, 'examples heading follows the introduction')
  if (locale === 'es') assert.equal(t('vmLxc.updates.customExamplesHeading'), 'Ejemplos para adaptar:')
  const examples = tree.filter(n => n.type === 'code').map(n => n.props.children)
  assert.equal(examples.length, 4)
  assert(examples.includes('/opt/my-app/update.sh'))
  assert(examples[1].includes("curl -fsSL 'https://example.com/my-app/update.sh'"))
  assert(examples[1].includes('-o "$script" &&\nbash "$script"'), 'never execute a failed download')
  assert(examples[1].includes('trap'), 'clean up the temporary download')
  for (const example of examples) {
    const syntax = spawnSync('sh', ['-n'], {input: example, encoding: 'utf8'})
    assert.equal(syntax.status, 0, syntax.stderr)
  }
  if (locale === 'en') {
    const fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'proxmenux-helper-launcher-'))
    try {
      // The visible command stays short; the actual backend adds protection.
      fs.symlinkSync('/bin/bash', path.join(fixture, 'bash'))
      const fetch = '#!/bin/sh\nprintf "%s" "$FETCH_BODY"\nexit "$FETCH_STATUS"\n'
      fs.writeFileSync(path.join(fixture, 'curl'), fetch, {mode: 0o755})
      for (const tool of ['wget', 'curl']) {
        const wget = path.join(fixture, 'wget')
        if (tool === 'wget') fs.writeFileSync(wget, fetch, {mode: 0o755})
        else fs.unlinkSync(wget)
        const command = canonicalHelper.replaceAll('qbittorrent.sh', 'qbittorrent.sh2')
          .replace('curl -fsSL', tool === 'wget' ? 'wget -qLO -' : 'curl -fsSL')
        const prepared = spawnSync('python3', ['-c',
          'import sys; from lxc_apps import protect_download_update_command; sys.stdout.write(protect_download_update_command(sys.stdin.read()))'], {
          input: command, encoding: 'utf8', env: {...process.env, PYTHONPATH: path.join(root, 'scripts')},
        })
        assert.equal(prepared.status, 0, prepared.stderr)
        assert(prepared.stdout.includes('updater download failed'), 'both curl and historical wget launchers remain protected')
        for (const [status, body, expected] of [[8, '', 1], [8, 'echo SHOULD_NOT_RUN', 1],
          [0, '', 1], [0, 'echo SCRIPT_RAN; exit 0', 0], [0, 'echo SCRIPT_RAN; exit 23', 23]]) {
          const run = spawnSync('/bin/sh', ['-c', prepared.stdout], {
            encoding: 'utf8', env: {...process.env, PATH: fixture, FETCH_STATUS: String(status), FETCH_BODY: body},
          })
          assert.equal(run.status, expected, run.stderr)
          assert(!run.stdout.includes('SHOULD_NOT_RUN'), 'a partial failed download must not execute')
          assert.equal(run.stdout.includes('SCRIPT_RAN'), status === 0 && body !== '')
        }
      }
    } finally {
      fs.rmSync(fixture, {recursive: true, force: true})
    }
  }
  if (locale === 'en') {
    const fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'proxmenux-online-example-'))
    try {
      const bin = path.join(fixture, 'bin')
      fs.mkdirSync(bin)
      fs.writeFileSync(path.join(bin, 'curl'), '#!/bin/sh\nexit "$EXAMPLE_FETCH_STATUS"\n', {mode: 0o755})
      fs.writeFileSync(path.join(bin, 'bash'), '#!/bin/sh\n: > "$EXAMPLE_EXECUTION_MARKER"\n', {mode: 0o755})
      for (const status of [0, 22]) {
        const marker = path.join(fixture, `ran-${status}`)
        const run = spawnSync('/bin/sh', ['-c', examples[1]], {encoding: 'utf8', env: {
          ...process.env, PATH: `${bin}:${process.env.PATH}`, TMPDIR: fixture,
          EXAMPLE_FETCH_STATUS: String(status), EXAMPLE_EXECUTION_MARKER: marker,
        }})
        assert.equal(run.status, status, run.stderr)
        assert.equal(fs.existsSync(marker), status === 0, 'do not run a failed or incomplete download')
      }
      assert.deepEqual(fs.readdirSync(fixture).sort(), ['bin', 'ran-0'], 'temporary scripts must be removed')
    } finally {
      fs.rmSync(fixture, {recursive: true, force: true})
    }
  }
  assert(examples.some(code => code.includes('apt-get install -y --only-upgrade my-package')))
  assert(examples.some(code => code.includes('install -b -m 0755 /tmp/my-app.new')))
  assert.equal(command, '', 'help examples must not change the saved command')
  assert.equal(saves, 0, 'opening help must not execute or save')
  assert.match(tree.find(n => n.type === 'DialogContent').props.className, /overflow-y-auto/)
  method = 'custom'
  tree = render()
  assert.equal(tree.find(n => n.props.onClick === props.onSave).props.disabled, true)
  tree.find(n => n.type === 'Textarea').props.onChange({target: {value: '/opt/my-app/update.sh'}})
  tree = render()
  assert.equal(tree.find(n => n.props.onClick === props.onSave).props.disabled, false)
  tree = render({helperAvailable: false})
  assert(!tree.some(n => n.type === 'Button' && n.props.children === t('vmLxc.updates.helperMethod')))
  method = 'helper'
  tree = render({helperAvailable: false})
  assert.equal(tree.find(n => n.props.onClick === props.onSave).props.disabled, true)
  console.log(`PASS ${locale}: explicit selection, navbar blue, dimmed disabled Save, examples heading, local/online scripts, no execution, validation`)
}

// Integrate the editor with the actual parent open/save/cancel functions.
async function testParentRoundTrip() {
  const parentSource = fs.readFileSync(path.join(root, 'components/virtual-machines.tsx'), 'utf8')
  const ast = ts.createSourceFile('virtual-machines.tsx', parentSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const names = ['openCustomCmdEditor', 'saveCustomCommand', 'closeCustomCmdEditor']
  const declarations = {}
  function visit(node) {
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && names.includes(node.name.text)) {
      declarations[node.name.text] = `const ${node.getText(ast)};`
    }
    ts.forEachChild(node, visit)
  }
  visit(ast)
  for (const name of names) assert(declarations[name], `missing actual parent function ${name}`)
  const compiled = ts.transpileModule(names.map(n => declarations[n]).join('\n') + '\n' +
    names.map(n => `exports.${n} = ${n};`).join('\n'), {compilerOptions: {module: ts.ModuleKind.CommonJS}})
  const saved = new Map([
    ['a', {id: 'a', name: 'Odoo', helper_slug: 'odoo', update_method: 'helper', update_command: ''}],
    ['b', {id: 'b', name: 'Other app', update_method: 'custom', update_command: '/opt/other/update.sh'}],
  ])
  let writes = 0
  const parent = {exports: {}, customCmdDraft: '', updaterMethodDraft: 'none',
    setCustomCmdEditingApp: value => {parent.editing = value},
    setCustomCmdDraft: value => {parent.customCmdDraft = value},
    setUpdaterMethodDraft: value => {parent.updaterMethodDraft = value},
    setCustomCmdSaving: value => {parent.saving = value},
    patchAppWatch: async (vmid, app, patch) => {
      assert.equal(vmid, 101)
      saved.set(app.id, {...saved.get(app.id), ...patch})
      writes++
    }, t: key => key, alert: error => {throw Error(error)},
  }
  vm.runInNewContext(compiled.outputText, parent)
  const render = () => flatten(englishEditor({method: parent.updaterMethodDraft, command: parent.customCmdDraft,
    helperAvailable: true, helperSlug: saved.get(parent.editing)?.helper_slug, configured: true,
    saving: false, changed: true, onMethodChange: parent.setUpdaterMethodDraft,
    onCommandChange: parent.setCustomCmdDraft, onCancel: parent.exports.closeCustomCmdEditor,
    onSave: () => {}, onRemove: () => {}}))
  parent.exports.openCustomCmdEditor(saved.get('a'))
  let field = render().find(n => n.type === 'Textarea')
  assert(field.props.value.includes('/ct/odoo.sh'))
  const edited = field.props.value.replace('PHS_SILENT=1', 'PHS_SILENT=0')
  field.props.onChange({target: {value: edited}})
  assert.equal(writes, 0, 'editing must not persist before Save')
  parent.exports.closeCustomCmdEditor()
  assert.equal(saved.get('a').update_method, 'helper', 'Cancel leaves the original choice unchanged')
  parent.exports.openCustomCmdEditor(saved.get('a'))
  field = render().find(n => n.type === 'Textarea')
  assert(field.props.value.includes('PHS_SILENT=1'))
  field.props.onChange({target: {value: edited}})
  await parent.exports.saveCustomCommand(101, saved.get('a'))
  assert.equal(saved.get('a').update_method, 'custom')
  assert.equal(saved.get('a').update_command, edited, 'Save must not discard the edited helper launcher')
  parent.exports.openCustomCmdEditor(saved.get('a'))
  assert.equal(render().find(n => n.type === 'Textarea').props.value, edited, 'reopen the exact saved custom command')
  parent.exports.openCustomCmdEditor(saved.get('b'))
  assert.equal(render().find(n => n.type === 'Textarea').props.value, '/opt/other/update.sh', 'keep commands separate per app')
  parent.exports.openCustomCmdEditor(saved.get('a'))
  parent.setUpdaterMethodDraft('helper')
  await parent.exports.saveCustomCommand(101, saved.get('a'))
  assert.equal(saved.get('a').update_method, 'helper')
  assert.equal(saved.get('a').update_command, '', 'explicitly selecting helper restores the official path')
  assert.equal(saved.get('b').update_command, '/opt/other/update.sh')
  console.log('PASS actual parent: edit, cancel, save, reopen, per-app isolation, restore helper')
}
testParentRoundTrip().catch(error => {console.error(error); process.exitCode = 1})
