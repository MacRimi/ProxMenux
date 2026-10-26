// Run the shipped deletion client with only its authenticated transport replaced.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const source = fs.readFileSync('AppImage/lib/guest-backup-archives.ts', 'utf8');
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
const backup = { volid: 'local:backup/vzdump-lxc-100-fixture.tar.zst', storage: 'local' };

async function run(responses) {
  const calls = [];
  const context = { exports: {}, AbortSignal, Date, setTimeout: callback => callback(), require: name => {
    assert.equal(name, './api-config');
    return { fetchApi: async (path, options) => {
      calls.push({ path, options });
      assert.ok(responses.length, `unexpected call: ${path}`);
      const response = responses.shift();
      if (response instanceof Error) throw response;
      return response;
    } };
  } };
  vm.runInNewContext(js, context);
  let results, error;
  try { results = JSON.parse(JSON.stringify(await context.exports.deleteGuestBackups(100, [backup]))); }
  catch (caught) { error = caught; }
  return { calls, results, error };
}

(async () => {
  const success = await run([{ results: [{ volid: backup.volid, status: 'deleted' }] }]);
  assert.equal(success.results[0].status, 'deleted');
  assert.deepEqual(JSON.parse(success.calls[0].options.body), { confirm: true, backups: [backup] });
  assert.equal(success.calls[0].options.method, 'POST');
  assert.equal(success.calls.length, 1);
  const task = 'UPID:pve1:01:02:03:imgdel:100:root@pam:';
  const pending = { results: [{ volid: backup.volid, status: 'pending', task }] };
  const completed = await run([pending, { volid: backup.volid, status: 'pending' }, { volid: backup.volid, status: 'deleted' }]);
  assert.equal(completed.results[0].status, 'deleted');
  assert.equal(completed.calls.length, 3);
  assert.equal(completed.calls[1].path, `/api/vms/100/backups/delete-status?task=${encodeURIComponent(task)}`);
  assert.equal(completed.calls.filter(call => call.options.method === 'POST').length, 1);
  const failed = await run([pending, { volid: backup.volid, status: 'unconfirmed', error: 'protected' }]);
  assert.equal(failed.results[0].status, 'unconfirmed');
  const lostPost = await run([new Error('network failure')]);
  assert.equal(lostPost.error.message, 'network failure');
  assert.equal(lostPost.calls.length, 1, 'never retry destructive POST');
  const lostStatus = await run([pending, new Error('timeout'), new Error('timeout'), new Error('timeout')]);
  assert.equal(lostStatus.results[0].status, 'unconfirmed');
  assert.equal(lostStatus.calls.length, 4, 'bounded read failures');
  for (const response of [{ results: [] }, { results: [{ volid: 'other', status: 'deleted' }] },
                           { results: [{ volid: backup.volid, status: 'accepted' }] }]) {
    assert.equal((await run([response])).error.message, 'deletionUnconfirmed');
  }
  const foreignStatus = await run([pending, { volid: 'other', status: 'deleted' }]);
  assert.equal(foreignStatus.results[0].status, 'unconfirmed');

  const component = fs.readFileSync('AppImage/components/guest-backup-list.tsx', 'utf8');
  const english = JSON.parse(fs.readFileSync('AppImage/messages/en/common.json')).vmLxc.backups;
  for (const [, key] of component.matchAll(/t\("vmLxc\.backups\.([A-Za-z]+)"/g)) {
    assert.ok(typeof english[key] === 'string' && english[key].length, `English translation: ${key}`);
  }
  assert.ok(component.includes('disabled={disabled || !!backup.protected'));
  assert.ok(component.includes('!backup.protected'));
  assert.ok(component.includes('DialogDescription'));
  const parent = fs.readFileSync('AppImage/components/virtual-machines.tsx', 'utf8');
  assert.ok(parent.includes('<GuestBackupList'));
  assert.ok(parent.includes('await fetchVmBackups(selectedVM.vmid, true)'));
  console.log('PASS: native task completion, partial/unconfirmed outcomes, lost responses, no destructive retries, translated UI and forced refresh');
})().catch(error => { console.error(error); process.exitCode = 1; });
