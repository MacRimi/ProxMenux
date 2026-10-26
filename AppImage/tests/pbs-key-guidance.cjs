// Offline regression: execute the actual message JSX and provider lookup.
// Run with Node 22+, NODE_PATH pointing to a TypeScript installation.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const test = require('node:test')
const ts = require('typescript')
const root = path.resolve(__dirname, '..')
const source = fs.readFileSync(path.join(root, 'components/host-backup.tsx'), 'utf8')
const provider = fs.readFileSync(path.join(root, 'lib/i18n/provider.tsx'), 'utf8')
const en = JSON.parse(fs.readFileSync(path.join(root, 'messages/en/common.json')))
const ast = ts.createSourceFile('host-backup.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
function compile(text) {
  return ts.transpileModule(text, { compilerOptions: { jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS } }).outputText
}
function translator(locale) {
  const pure = provider.slice(provider.indexOf('function getMessage('), provider.indexOf('export function I18nProvider'))
  const callback = provider.slice(provider.indexOf('(key: string, params?: TranslationParams) => {', provider.indexOf('const t = useCallback')), provider.indexOf('\n    },', provider.indexOf('const t = useCallback')) + 6)
  return vm.runInNewContext(compile(`${pure}\nconst t = ${callback}; t`), { MESSAGE_CATALOG: { en, fixture: locale }, language: 'fixture' })
}
const React = { createElement: (tag, props, ...children) => ({ tag, props, children }) }
function messages(marker) {
  const found = []
  function visit(node) {
    if (ts.isJsxElement(node) && ['p', 'div'].includes(node.openingElement.tagName.getText(ast)) && node.getText(ast).includes(marker)) {
      let nested = false
      function check(child) {
        if (ts.isJsxElement(child) && ['p', 'div'].includes(child.openingElement.tagName.getText(ast)) && child.getText(ast).includes(marker)) nested = true
        ts.forEachChild(child, check)
      }
      node.children.forEach(check)
      if (!nested) found.push(node.getText(ast))
    }
    ts.forEachChild(node, visit)
  }
  visit(ast)
  return found
}
function render(jsx, locale = {}, match = { name: 'STORAGE<&>', path: '/etc/pve/priv/storage/DIFFERENT<&>.enc' }) {
  return vm.runInNewContext(compile(`const result = (${jsx}); result`), { React, t: translator(locale), pveMatch: match, pveMatchInspect: match })
}
function text(node) {
  if (Array.isArray(node)) return node.map(text).join('')
  if (node == null || typeof node === 'boolean') return ''
  return typeof node === 'object' ? text(node.children) : String(node)
}
function codes(node) {
  if (Array.isArray(node)) return node.flatMap(codes)
  if (!node || typeof node !== 'object') return []
  return node.tag === 'code' ? [node] : codes(node.children)
}
const help = 'Monitor uses /usr/local/share/proxmenux/pbs-key.conf with --keyfile for encrypted PBS backups and restores. The keyfile is stored with mode 0600. Keep a safe copy outside this host.'
test('PBS help is a complete message with unconditional missing-key English fallback', () => {
  const jsx = messages('backup.encryption.pbsHelp')
  assert.equal(jsx.length, 1)
  const output = render(jsx[0])
  assert.equal(text(output), help)
  assert.deepEqual(codes(output).map(text), ['/usr/local/share/proxmenux/pbs-key.conf', '--keyfile', '0600'])
})
test('both PVE dialogs distinguish storage from path with missing-key fallback', () => {
  const jsx = messages('backup.keyfileActions.pveKeyDescription')
  assert.equal(jsx.length, 2)
  for (const message of jsx) {
    const output = render(message)
    assert.equal(text(output), 'PVE storage STORAGE<&> has a keyfile at /etc/pve/priv/storage/DIFFERENT<&>.enc. You can import it into Monitor.')
    assert.deepEqual(codes(output).map(text), ['STORAGE<&>', '/etc/pve/priv/storage/DIFFERENT<&>.enc'])
    assert.match(codes(output)[1].props.className, /break-all/)
  }
})
test('whole-message translations can reorder rich placeholders in all three consumers', () => {
  const locale = { backup: {
    encryption: { pbsHelp: 'Mode {mode}; option {option}; file {keyfile}.' },
    keyfileActions: { pveKeyDescription: 'At {path}: key for {storage}.' },
  } }
  const helpOutput = render(messages('backup.encryption.pbsHelp')[0], locale)
  assert.equal(text(helpOutput), 'Mode 0600; option --keyfile; file /usr/local/share/proxmenux/pbs-key.conf.')
  assert.deepEqual(codes(helpOutput).map(text), ['0600', '--keyfile', '/usr/local/share/proxmenux/pbs-key.conf'])
  for (const jsx of messages('backup.keyfileActions.pveKeyDescription')) {
    const output = render(jsx, locale)
    assert.equal(text(output), 'At /etc/pve/priv/storage/DIFFERENT<&>.enc: key for STORAGE<&>.')
    assert.deepEqual(codes(output).map(text), ['/etc/pve/priv/storage/DIFFERENT<&>.enc', 'STORAGE<&>'])
  }
})
test('shipped locales fall back to complete guidance without changing their catalogs', () => {
  for (const lang of fs.readdirSync(path.join(root, 'messages')).filter(name => fs.statSync(path.join(root, 'messages', name)).isDirectory())) {
    const locale = JSON.parse(fs.readFileSync(path.join(root, 'messages', lang, 'common.json')))
    for (const jsx of messages('backup.keyfileActions.pveKeyDescription')) assert.ok(text(render(jsx, locale)).includes('STORAGE<&>'))
    assert.ok(text(render(messages('backup.encryption.pbsHelp')[0], locale)).includes('--keyfile'))
  }
})
test('both discovery consumers retain matching-only selection and absent handling', () => {
  for (const [name, input] of [['pveMatch', 'pveDiscover'], ['pveMatchInspect', 'pveDiscoverInspect']]) {
    let initializer
    function visit(node) {
      if (ts.isVariableDeclaration(node) && node.name.getText(ast) === name) initializer = node.initializer.getText(ast)
      ts.forEachChild(node, visit)
    }
    visit(ast)
    assert.ok(initializer)
    for (const data of [undefined, { entries: [] }, { entries: [{ matches_repository: false }] }]) {
      assert.equal(vm.runInNewContext(compile(`const result = ${initializer}; result`), { [input]: data }), null)
    }
    const match = { name: 'chosen', path: '/chosen.enc', matches_repository: true }
    assert.equal(vm.runInNewContext(compile(`const result = ${initializer}; result`), { [input]: { entries: [{ matches_repository: false }, match] } }), match)
    assert.ok(source.includes(`{${name} && (`))
    assert.ok(source.includes(`setImportPath(${name}.path)`))
  }
})
module.exports = { messages, render, text, codes }
