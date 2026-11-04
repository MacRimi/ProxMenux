// Exercise both shipped SVG layouts with OVS internal ports and bond topology.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')
const source = fs.readFileSync(path.join(__dirname, '../components/network-flow.tsx'), 'utf8')
const code = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
}).outputText
const sandbox = { exports: {}, require: () => ({}), console }
vm.runInNewContext(code, sandbox)
const data = {
  nics: [
    { id: 'eno1', link: '1 Gb/s', rx: 1, tx: 2, status: 'up' },
    { id: 'eno2', link: '1 Gb/s', rx: 1, tx: 2, status: 'up', bond: 'uplink', role: 'member' },
    { id: 'eno3', link: '1 Gb/s', rx: 1, tx: 2, status: 'up', bond: 'uplink', role: 'member' },
  ],
  bonds: [{ id: 'uplink', mode: 'balance-tcp', rx: 2, tx: 4, status: 'up' }],
  bridges: [{ id: 'switch0', parent: 'eno1' }, { id: 'vmbr1' }],
  consumers: [
    { id: 'host', kind: 'host', label: 'host', bridge: 'switch0', rx: 1, tx: 2 },
    { id: 'vlan100', kind: 'interface', label: 'vlan100 · VLAN 100', bridge: 'switch0', rx: 0, tx: 0 },
    { id: 'tap103i0', kind: 'vm', label: 'VM 103', bridge: 'switch0', rx: 1, tx: 2 },
    { id: 'veth115i0', kind: 'lxc', label: 'LXC 115', bridge: 'switch0', rx: 1, tx: 2 },
    { id: 'tap104i0', kind: 'vm', label: 'VM 104', bridge: 'vmbr1', rx: 1, tx: 2 },
  ],
}
const labels = { down: 'Down', active: 'Active', standby: 'Standby' }
for (const render of [sandbox.renderHorizontal, sandbox.renderVertical]) {
  const result = render(data, 1500, labels, 'Bytes')
  for (const id of ['switch0', 'vmbr1', 'vlan100', 'tap103i0', 'veth115i0', 'tap104i0', 'uplink']) {
    assert.ok(result.svg.includes(`data-node-id="${id}"`), `layout must draw ${id}`)
  }
  assert.ok(result.svg.includes('vlan100 · VLAN 100'))
  assert.ok(!result.svg.includes('NaN'))
  assert.ok(!result.svg.includes('undefined'))
}
console.log('PASS: both Network Flow layouts render OVS bonds, internal VLAN ports and mixed Linux/OVS guests')
