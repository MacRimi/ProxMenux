// Execute the actual Security handlers against inert UI state and transport.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '../../../..');
const source = fs.readFileSync(path.join(root, 'AppImage/components/security.tsx'), 'utf8');
const catalogs = Object.fromEntries(['en','de','es','fr','it','pt','sk','sv'].map(lang => [lang, require(path.join(root, `AppImage/messages/${lang}/common.json`)).securityPage]));
const begin = source.indexOf('  const handleUninstallLynis = async () => {');
const end = source.indexOf('\n  const loadFail2banDetails =', begin);
assert(begin !== -1 && end > begin);
const eraseTypes = text => text.replace(/fetchApi<\{[^}]+\}>/g, 'fetchApi')
  .replace(/ as \{ partial\?: boolean \} \| undefined/g, '');
const uninstall = eraseTypes(source.slice(begin, end));
const anchor = source.indexOf('if (confirm(st("confirm.deleteAuditReport")))');
assert(anchor !== -1);
const clickBegin = source.lastIndexOf('onClick={(e) => {', anchor);
const clickEnd = source.indexOf('\n                          className=', anchor);
assert(clickBegin !== -1 && clickEnd > anchor);
const click = eraseTypes(source.slice(clickBegin + 'onClick={'.length, clickEnd).trim().replace(/}\s*$/, ''));
async function exercise(lang, action, reply, priorSuccess = '') {
  const state = {report: {id: 'inert'}, expanded: true, success: priorSuccess, error: '', loads: 0, calls: []};
  const st = (key) => key.split('.').reduce((v, k) => v?.[k], catalogs[lang]);
  const ctx = {
    st, Error, confirm: () => true,
    setLynisReport: v => {state.report = v}, setLynisShowReport: v => {state.expanded = v},
    setSuccess: v => {state.success = v}, setError: v => {state.error = v},
    setUninstallingLynis: () => {}, setShowLynisUninstallConfirm: () => {},
    loadSecurityTools: () => {state.loads++},
    fetchApi: (endpoint, options) => {
      assert.equal(endpoint, action === 'delete' ? '/api/security/lynis/report' : '/api/security/lynis/uninstall');
      assert.equal(options.method, action === 'delete' ? 'DELETE' : 'POST');
      state.calls.push(options.method);
      return reply instanceof Error ? Promise.reject(reply) : Promise.resolve(reply);
    },
  };
  const fn = vm.runInNewContext(action === 'delete' ? `(${click})` : `${uninstall}; handleUninstallLynis`, ctx);
  await fn({stopPropagation() {}});
  await new Promise(resolve => setImmediate(resolve));
  return state;
}
(async () => {
  for (const lang of Object.keys(catalogs)) {
    for (const action of ['delete', 'uninstall']) {
      const success = await exercise(lang, action, {success:true, message:'inert'});
      assert.equal(success.report, null, `${lang} ${action} clean report`);
      assert(success.success, `${lang} ${action} clean success`);
      assert.equal(success.error, '', `${lang} ${action} clean no error`);
      assert.equal(success.loads, 1);
      for (const [kind, reply] of [
        ['no_files', {success:false,outcome:'no_files',message:'No report files found to delete'}],
        ['malformed_success', {success:'false',message:'inert malformed response'}],
        ['first_failure', {success:false,partial:false,message:'inert denied'}],
        ['partial_failure', {success:false,partial:true,message:'inert denied'}],
        ['http_failure', Object.assign(new Error('inert denied'), {body:{success:false,partial:true,message:'inert denied'}})],
        ['nonjson_failure', new Error('Invalid JSON response')],
        ['network_failure', new Error('network failure')],
      ]) {
        const state = await exercise(lang, action, reply);
        assert.notEqual(state.report, null, `${lang} ${action} ${kind}: report retained`);
        assert.equal(state.success, '', `${lang} ${action} ${kind}: no success`);
        assert.equal(state.loads, 0, `${lang} ${action} ${kind}: no success refresh`);
        assert(state.error, `${lang} ${action} ${kind}: error visible`);
        const expectedKey = kind === 'no_files' ? (action === 'delete' ? 'deleteReportNoFiles' : 'lynisUninstallNoFiles')
          : kind === 'partial_failure' || kind === 'http_failure' ? 'lynisRemovalPartial'
          : 'lynisRemovalUnconfirmed';
        assert.equal(state.error, catalogs[lang].errors[expectedKey], `${lang} ${action} ${kind}: native whole-message feedback`);
        if (action === 'delete' && kind === 'no_files') {
          const stale = await exercise(lang, action, reply, 'Earlier unrelated success');
          assert.equal(stale.success, '', `${lang} delete clears stale success before failure`);
        }
      }
    }
  }
  console.log('actual Lynis handlers: eight locales, clean/no-files/pre-first/partial/HTTP/non-JSON/network state');
})().catch(err => { console.error(err); process.exitCode = 1 });
