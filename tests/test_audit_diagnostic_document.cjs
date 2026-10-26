// Render the quick-diagnosis document from the real builder, in every
// language, without a browser or an API. A short report that throws on
// click is worse than a long one that prints.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const app = path.resolve(__dirname, '../AppImage');
const appRequire = createRequire(path.join(app, 'package.json'));
const ts = appRequire('typescript');

function load(rel, imports = {}) {
  const source = fs.readFileSync(path.join(app, rel), 'utf8');
  const compiled = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020,
  }}).outputText;
  const module = { exports: {} };
  new Function('require', 'module', 'exports', compiled)(
    name => imports[name] || appRequire(name), module, module.exports);
  return module.exports;
}

global.window = { location: { origin: 'http://localhost:8008' } };
const shell = load('lib/report-shell.ts');
const evidence = load('lib/evidence-format.ts');
const diagrams = load('lib/report-diagrams.ts', { './report-shell': shell });
const presentation = load('lib/audit-presentation.ts', { './evidence-format': evidence });
const doc = load('lib/audit-document.ts', {
  './report-shell': shell, './report-diagrams': diagrams,
  './audit-presentation': presentation, './evidence-format': evidence,
});

const finding = (check_id, classification, area, extra = {}) => ({
  check_id, classification, area, incomplete: false, summary_key: 'attention',
  summary_params: { count: '3', total: '9' }, evidence: 'raw evidence',
  affected: Array.from({ length: 25 }, (_, i) => ({
    name: `object-${i}`, classification, reason_key: 'hostBackupStale',
  })),
  ...extra,
});

const FINDINGS = [
  finding('backup.host_recovery', 'critical', 'backup'),
  finding('system.security_updates', 'warning', 'system'),
  finding('guests.autostart', 'observation', 'guests'),
  finding('storage.zfs_scrub_age', 'conformant', 'storage'),
  { ...finding('system.update_chain', 'unverified', 'system'), affected: [] },
];

for (const locale of ['en', 'es', 'de', 'fr', 'it', 'pt', 'sk', 'sv']) {
  const messages = JSON.parse(
    fs.readFileSync(path.join(app, 'messages', locale, 'common.json')));
  const t = (key, values = {}) => {
    let text = key.split('.').reduce((o, k) => o?.[k], messages) ?? key;
    for (const [k, v] of Object.entries(values)) text = text.replaceAll(`{${k}}`, v);
    return text;
  };
  const input = {
    profile: 'diagnostic', findings: FINDINGS, t, locale,
    run: { run_id: 'r1', started_at: 1788700000, finished_at: 1788700100,
           status: 'partial', metadata: {} },
    inventory: { sections: { identity: { node: 'fixture' } }, unavailable: {} },
  };
  const html = doc.buildAuditDocument(input);

  // What it must contain: the findings that ask for a decision.
  assert.ok(html.includes(t('audit.checks.backup.host_recovery.title')),
    `${locale}: the critical finding is missing`);
  assert.ok(html.includes(t('audit.checks.system.security_updates.title')),
    `${locale}: the warning is missing`);
  // And the blind spot it could not read.
  assert.ok(html.includes(t('audit.document.diagnosticUnread')),
    `${locale}: unread readings are not declared`);
  // What it must not: conformant results, observations, the annex.
  assert.ok(!html.includes(t('audit.checks.storage.zfs_scrub_age.title')),
    `${locale}: a conformant result reached the quick diagnosis`);
  assert.ok(!html.includes(t('audit.checks.guests.autostart.title')),
    `${locale}: an observation reached the quick diagnosis`);
  assert.ok(!html.includes('raw evidence'),
    `${locale}: the technical annex reached the quick diagnosis`);
  // Long tables are cut rather than printed whole.
  assert.ok(html.includes('object-7') && !html.includes('object-9'),
    `${locale}: affected rows are not capped at eight`);
  assert.ok(html.includes(t('audit.document.diagnosticMoreRows', { count: '17' })),
    `${locale}: the cut is not declared`);
  assert.ok(!html.includes('undefined') && !html.includes('audit.document.'),
    `${locale}: an untranslated key or an undefined value was rendered`);
}

// With nothing to decide it says so instead of printing an empty section.
const messages = JSON.parse(fs.readFileSync(path.join(app, 'messages/en/common.json')));
const t = (key, values = {}) => {
  let text = key.split('.').reduce((o, k) => o?.[k], messages) ?? key;
  for (const [k, v] of Object.entries(values)) text = text.replaceAll(`{${k}}`, v);
  return text;
};
const clear = doc.buildAuditDocument({
  profile: 'diagnostic', findings: [FINDINGS[3]], t, locale: 'en',
  run: { run_id: 'r1', started_at: 1788700000, finished_at: 1788700100, metadata: {} },
  inventory: { sections: { identity: { node: 'fixture' } }, unavailable: {} },
});
assert.ok(clear.includes(t('audit.document.diagnosticClear')),
  'a host with nothing to decide is not told so');
assert.ok(!clear.includes(t('audit.document.diagnosticActions')),
  'an empty findings section was printed');

// A disk finding shows what happened, not six rows repeating that
// something did. The columns are the inventory's own, so the finding and
// the observation table read as one account of the disk.
{
  const messages = JSON.parse(fs.readFileSync(path.join(app, 'messages/es/common.json')));
  const t = (key, values = {}) => {
    let text = key.split('.').reduce((o, k) => o?.[k], messages) ?? key;
    for (const [k, v] of Object.entries(values)) text = text.replaceAll(`{${k}}`, v);
    return text;
  };
  const groups = presentation.presentFinding({
    check_id: 'hardware.disk_errors', classification: 'warning',
    area: 'hardware', evidence: null,
    affected: [
      { name: 'sdh', type: 'io_error', severity: 'critical', count: 284364,
        first_seen: '2026-05-20T23:03:39', last_seen: '2026-09-07T19:31:47',
        message: 'ata8.00: error: { IDNF }', classification: 'warning',
        reason_key: 'diskErrorsActive' },
      { name: 'sda', type: 'smart_error', severity: 'warning', count: 13,
        first_seen: 1788000000, last_seen: 1788600000, message: 'read failed',
        classification: 'warning', reason_key: 'diskWarningsActive' },
    ],
  }, t, 'es', []);

  assert.equal(groups.length, 2, 'events are not grouped by device');
  assert.deepEqual(groups.map(g => g.title), ['sdh', 'sda']);
  assert.deepEqual(groups[0].columns, [
    t('audit.document.event'), t('audit.document.severity'),
    t('audit.document.occurrences'), t('audit.document.firstSeen'),
    t('audit.document.lastSeen'), t('audit.document.detail'),
  ], 'the finding does not use the inventory table columns');
  const [type, severity, count, first, last, detail] = groups[0].rows[0].cells;
  assert.equal(type, 'io_error');
  assert.equal(severity, t('audit.classifications.critical'),
    'the stored English severity reached a translated view');
  assert.equal(count, '284364');
  assert.ok(first.includes('2026') && last.includes('2026'),
    'ISO timestamps were not rendered as dates');
  assert.equal(detail, 'ata8.00: error: { IDNF }');
  assert.equal(first, new Date(2026, 4, 20, 23, 3, 39).toLocaleString('es'),
    'a local SQLite timestamp was converted as UTC');
  // The other Monitor tables store epoch seconds; both forms must render.
  const epochRow = groups[1].rows[0].cells;
  assert.ok(epochRow[3].includes('2026') && epochRow[4].includes('2026'),
    'epoch timestamps were not rendered as dates');
  console.log('Disk findings: inventory columns, translated severity, both date forms.');
}

// "Could not be evaluated" describes the assessment, not the host. The
// reason is recorded against each source; it used to sit two collapsed
// panels below a line that explained nothing.
{
  const messages = JSON.parse(fs.readFileSync(path.join(app, 'messages/es/common.json')));
  const t = (key, values = {}) => {
    let text = key.split('.').reduce((o, k) => o?.[k], messages) ?? key;
    for (const [k, v] of Object.entries(values)) text = text.replaceAll(`{${k}}`, v);
    return text;
  };
  // Exactly what .55 recorded: a backup destination that refused the
  // connection, which is why the age of its copies is unverified.
  const line = presentation.unreadSources([
    { source: 'cmd:["pvesm", "list", "local"]', collected_at: 1788728305 },
    { source: 'cmd:["pvesm", "list", "pbs"]', collected_at: 1788728305,
      error: "exit 111: pbs: error fetching datastores - 500 Can't connect to\n192.168.0.72:8007 (Connection refused)" },
  ], t);
  assert.ok(line.startsWith(t('audit.presentation.couldNotRead')),
    'the line does not say that something could not be read');
  assert.ok(line.includes('pvesm list pbs'),
    'the command was left in its serialised form');
  assert.ok(!line.includes('cmd:['), 'the raw source key leaked into the reader\'s view');
  assert.ok(line.includes('Connection refused'), 'the reason was dropped');
  assert.ok(!line.includes('\n'), 'a multi-line error was not flattened');
  assert.ok(!line.includes('pvesm list local'),
    'a source that was read fine was listed as unreadable');
  assert.equal(presentation.unreadSources([{ source: 'x', collected_at: 1 }], t), '',
    'a check whose sources all worked printed an empty notice');
  assert.equal(presentation.unreadSources(undefined, t), '');
  console.log('Unread sources: named, flattened, only the ones that failed.');
}

// Lynis repeats a warning once per thing it applies to. Ten promiscuous
// interfaces printed as ten rows saying "NETW-3015 · —" described none
// of them; collapsed, each row carries a warning and how often it was
// raised.
{
  const messages = JSON.parse(fs.readFileSync(path.join(app, 'messages/es/common.json')));
  const t = (key, values = {}) => {
    let text = key.split('.').reduce((o, k) => o?.[k], messages) ?? key;
    for (const [k, v] of Object.entries(values)) text = text.replaceAll(`{${k}}`, v);
    return text;
  };
  const warn = (test, message, details = '') => ({
    test, message, details, classification: 'observation', reason_key: 'lynisWarning' });
  const finding = affected => ({ check_id: 'security.lynis_warnings',
    classification: 'observation', area: 'security', evidence: null, affected });

  const plain = presentation.presentFinding(finding([
    warn('PKGS-7392', 'Found one or more vulnerable packages.'),
    ...Array.from({ length: 10 }, () => warn('NETW-3015', 'Found promiscuous interface')),
    warn('MAIL-8818', 'SMTP banner discloses software'),
  ]), t, 'es', []);
  assert.equal(plain.length, 1, 'warnings are still split into a group each');
  assert.equal(plain[0].rows.length, 3, '12 warnings did not collapse to 3 rows');
  assert.deepEqual(plain[0].columns, [t('audit.presentation.lynisTest'),
    t('audit.presentation.lynisWarning'), t('audit.document.occurrences')],
    'a detail column was printed with nothing to put in it');
  const promiscuous = plain[0].rows.find(r => r.cells[0] === 'NETW-3015');
  assert.equal(promiscuous.cells[2], '10', 'repetitions were not counted');

  // Where Lynis names what it found, the names are kept and joined.
  const named = presentation.presentFinding(finding([
    warn('NETW-3015', 'Found promiscuous interface', 'ens4f0'),
    warn('NETW-3015', 'Found promiscuous interface', 'eno1'),
  ]), t, 'es', []);
  assert.equal(named[0].columns.length, 4, 'the detail column is missing');
  assert.equal(named[0].rows[0].cells[3], 'ens4f0, eno1');
  console.log('Lynis warnings: one row per warning, repetitions counted, names kept.');
}

// The inventory profile is the other short document: structure and
// configuration, with nothing assessed. An assessment summary counting
// nothing and a findings section listing nothing are two empty frames
// around the only thing its reader opened it for.
const structure = doc.buildAuditDocument({
  profile: 'inventory', findings: [], t, locale: 'en',
  run: { run_id: 'r1', started_at: 1788700000, finished_at: 1788700100, metadata: {} },
  inventory: { sections: {
    identity: { node: 'fixture', pve_version: '9.2.4' },
    cluster: { member: false },
    hardware: { cpu_model: 'Xeon', memory_total: 1, disks: [],
                memory_modules: [], controllers: [] },
    network: { bridges: {}, adapters: [] },
  }, unavailable: {} },
});
assert.ok(structure.includes(t('audit.document.structureTitle')),
  'the structure report is still titled as an audit');
assert.ok(!structure.includes(t('audit.document.executiveSummary')),
  'an assessment summary counting nothing was printed');
assert.ok(!structure.includes(t('audit.document.findings')),
  'a findings section listing nothing was printed');
assert.ok(!structure.includes(t('audit.presentation.annex')),
  'the technical annex was printed with no evidence to carry');
assert.ok(structure.includes(t('audit.document.scope')),
  'the structure report does not say what it covers');
console.log('Structure report: no assessment frames, own title, scope kept.');

console.log('Quick diagnosis: eight languages, only what needs deciding, capped tables, declared blind spots and cuts.');
