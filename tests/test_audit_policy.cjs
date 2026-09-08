// Component-state regression tests with isolated hooks and a mocked API.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const app = path.resolve(__dirname, '../AppImage');
const ts = require(path.join(app, 'node_modules/typescript'));
const messages = require(path.join(app, 'messages/en/common.json'));
const t = (key, params = {}) => key.split('.').reduce((v, k) => v?.[k], messages)
  .replace(/\{(\w+)\}/g, (_, k) => params[k] ?? `{${k}}`);
let cursor = 0, states = [], effects = [], initialized = false, submitted, rejectSave = false;
const snapshot = { guests: {}, storages: {}, thresholds: {},
  defaults: { backup: 'required', autostart: 'not_required', storage_role: 'essential', recovery_objective_hours: 48 } };
const hooks = {
  useState(initial) { const i = cursor++; if (!(i in states)) states[i] = initial;
    return [states[i], v => { states[i] = typeof v === 'function' ? v(states[i]) : v; }]; },
  useMemo: fn => fn(), useCallback: fn => fn,
  useEffect(fn) { if (!initialized) effects.push(fn); },
};
const jsx = (type, props) => ({ type, props: props || {} });
const api = async (url, options) => {
  if (options) {
    submitted = JSON.parse(options.body);
    if (rejectSave) throw Object.assign(new Error('conflict'), { status: 409 });
    return { success: true, summary: { revision: 'second' } };
  }
  if (url.includes('inventory')) return { inventory: { sections: {
    guests: [{ vmid: 100, name: 'fixture', type: 'lxc' }], storages: [{ id: 'pbs', type: 'pbs' }],
  } } };
  return { success: true, policy: snapshot, summary: { revision: 'first' }, vocabulary: {
    expectations: ['required', 'not_required', 'unspecified'], roles: ['essential', 'optional', 'unspecified'],
    thresholds: { storage_usage_percent: 90 },
  } };
};
const mod = { exports: {} };
const source = fs.readFileSync(path.join(app, 'components/audit-policy.tsx'), 'utf8');
const js = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
} }).outputText;
new Function('require', 'module', 'exports', js)(name => {
  if (name === 'react') return hooks;
  if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx };
  if (name.endsWith('api-config')) return { fetchApi: api };
  if (name.endsWith('provider')) return { useT: () => t };
  return new Proxy({}, { get: (_, name) => String(name) });
}, mod, mod.exports);
function render() { cursor = 0; const tree = mod.exports.AuditPolicy(); initialized = true; return tree; }
function nodes(tree, type) {
  if (!tree || typeof tree !== 'object') return [];
  if (Array.isArray(tree)) return tree.flatMap(x => nodes(x, type));
  if (typeof tree.type === 'function') return nodes(tree.type(tree.props), type);
  return [...(tree.type === type ? [tree] : []), ...nodes(tree.props?.children, type)];
}
const change = (node, value) => node.props.onChange({ target: { value } });
// The dropdowns are the shared Select, which reports a value rather than
// an event. Unresolved imports come back as their own name, so the
// element type is the component's name.
const choose = (node, value) => node.props.onValueChange(value);
const tick = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  render(); effects.forEach(fn => fn()); await tick();
  // The form is locked until the reader says they are editing it.
  let tree = render();
  assert.equal(nodes(tree, 'fieldset')[0].props.disabled, true,
    'The declaration is editable before anyone asked to edit it');
  const editButton = nodes(tree, 'button').find(
    b => JSON.stringify(b.props.children).includes(messages.actions.edit));
  assert(editButton, 'No edit button to unlock the declaration');
  // A disabled fieldset disables every control it holds, so the button that
  // leaves that state cannot live inside it.
  assert(!nodes(nodes(tree, 'fieldset')[0], 'button').includes(editButton),
    'The edit button sits inside the fieldset it unlocks, so it is never clickable');
  // The dropdown governs its own opening, so the fieldset does not reach it.
  assert(nodes(tree, 'Select').every(sel => sel.props.disabled === true),
    'A locked declaration still opens its dropdowns');
  editButton.props.onClick(); tree = render();
  assert.equal(nodes(tree, 'fieldset')[0].props.disabled, false);
  assert(nodes(tree, 'Select').every(sel => sel.props.disabled === false),
    'Editing does not unlock the dropdowns');

  let select = nodes(tree, 'Select');
  assert.equal(select[0].props.value, 'inherit');
  const inherited = (value) => messages.audit.policy.inherit.replace('{value}', value);
  assert.equal(nodes(select[0], 'SelectItem')[0].props.children, inherited('Required'));
  assert.equal(nodes(select[2], 'SelectItem')[0].props.children, inherited('Essential'));
  choose(select[0], 'unspecified'); choose(select[2], 'unspecified');
  tree = render();
  assert.equal(nodes(tree, 'Select')[0].props.value, 'unspecified');
  nodes(tree, 'form')[0].props.onSubmit({ preventDefault() {} }); await tick();
  assert.equal(submitted.expected_revision, 'first');
  assert.equal(submitted.guests['100'].backup, 'unspecified');
  assert.equal(submitted.storages.pbs.role, 'unspecified');
  tree = render(); choose(nodes(tree, 'Select')[0], 'inherit');
  tree = render();
  const inputs = nodes(tree, 'input');
  assert.equal(inputs[0].props.placeholder, '48');
  assert.equal(inputs[1].props.max, 100);
  change(inputs[1], '-1'); tree = render();
  assert.equal(nodes(tree, 'input')[1].props.value, -1, 'Invalid value is not silently cleared');
  change(nodes(tree, 'input')[1], ''); tree = render();
  rejectSave = true;
  nodes(tree, 'form')[0].props.onSubmit({ preventDefault() {} }); await tick(); tree = render();
  assert.equal(submitted.expected_revision, 'second');
  assert.equal(submitted.guests['100'], undefined);
  assert.equal(nodes(tree, 'fieldset')[0].props.disabled, true);
  assert(JSON.stringify(tree).includes(messages.audit.policy.conflict));
  assert(JSON.stringify(tree).includes(messages.audit.policy.reload));

  // With nothing declared site-wide there is no value to name, and the
  // explicit option that would say the same thing is not offered twice.
  Object.assign(snapshot.defaults, { backup: undefined, autostart: undefined,
    storage_role: undefined });
  cursor = 0; states = []; effects = []; initialized = false;
  render(); effects.forEach(fn => fn()); await tick(); tree = render();
  select = nodes(tree, 'Select');
  const first = nodes(select[0], 'SelectItem');
  assert.equal(first[0].props.children, messages.audit.policy.inheritUnset,
    'The default option names a value nobody declared');
  assert(!first.slice(1).some(i => i.props.value === 'unspecified'),
    'The dropdown offers the same outcome twice');

  console.log('Policy UI: inheritance, explicit unspecified, numeric constraints, revision and conflict tests passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
