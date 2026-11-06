const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const source = fs.readFileSync('AppImage/lib/backup-retention.ts', 'utf8');
const context = { exports: {} };
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, context);
const { parseRetention, buildRetention } = context.exports;
for (const policy of ['keep-all=1', 'keep-last=3', 'keep-last=3,keep-weekly=2', 'keep-hourly=24,keep-daily=7,keep-monthly=12,keep-yearly=2']) {
  const { fields, keepAll } = parseRetention(policy);
  assert.equal(buildRetention(fields, keepAll), policy);
}
assert.equal(buildRetention({}, false), '', 'empty policy remains explicit');
assert.equal(buildRetention({}, true), 'keep-all=1');
assert.equal(buildRetention({ daily: '3', hourly: '0', last: '' }, false), 'keep-daily=3');
assert.equal(buildRetention({ last: '3' }, true), 'keep-last=3', 'existing job editor precedence preserved');
const component = fs.readFileSync('AppImage/components/backup-storage-retention.tsx', 'utf8');
const english = JSON.parse(fs.readFileSync('AppImage/messages/en/common.json')).backup.storageRetention;
for (const [, key] of component.matchAll(/t\("backup\.storageRetention\.([A-Za-z]+)"/g)) {
  assert.ok(typeof english[key] === 'string' && english[key], `translation: ${key}`);
}
assert.ok(component.includes('digest: editing.digest'));
assert.ok(component.includes('method: "PUT"'));
assert.ok(!component.includes('/prune'));
assert.ok(fs.readFileSync('AppImage/components/vm-backup-jobs.tsx', 'utf8').includes('from "../lib/backup-retention"'));
assert.ok(fs.readFileSync('AppImage/components/backup-tab.tsx', 'utf8').includes('<BackupStorageRetention />'));
console.log('PASS: shared native retention properties, keep-all/count round trips, explicit empty policy, translations and digest wiring');
