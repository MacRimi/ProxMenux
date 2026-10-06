// Portable offline execution of the actual health mapper and provider lookup.
// Only checked-out source enters Function; catalogs and opaque values are arguments.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const root = path.resolve(__dirname, '..');
const read = p => fs.readFileSync(path.join(root, p), 'utf8');
const parse = p => ts.createSourceFile(p, read(p), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const printer = ts.createPrinter();
const emit = (node, source) => printer.printNode(ts.EmitHint.Unspecified, node, source);
const compile = code => ts.transpileModule(code, {compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020,
}}).outputText;
function walk(node, fn) { fn(node); ts.forEachChild(node, n => walk(n, fn)); }
const provider = parse('AppImage/lib/i18n/provider.tsx');
const helpers = provider.statements.filter(n => ts.isFunctionDeclaration(n) && ['getMessage', 'interpolate'].includes(n.name?.text));
assert.equal(helpers.length, 2);
let lookup;
walk(provider, n => {
  if (ts.isVariableDeclaration(n) && n.name.getText(provider) === 't' &&
      n.initializer && ts.isCallExpression(n.initializer) && n.initializer.expression.getText(provider) === 'useCallback') lookup = n.initializer.arguments[0];
});
assert.ok(lookup, 'actual provider callback');
const catalogs = Object.fromEntries(fs.readdirSync(path.join(root, 'AppImage/messages')).filter(locale =>
  fs.existsSync(path.join(root, 'AppImage/messages', locale, 'common.json'))).map(locale =>
  [locale, JSON.parse(read(`AppImage/messages/${locale}/common.json`))]));
const translatorFactory = new Function('MESSAGE_CATALOG', 'language',
  compile(helpers.map(n => emit(n, provider)).join('\n') + '\nconst t = ' + emit(lookup, provider)) + '\nreturn t;');
const translator = (language, messages = catalogs) => translatorFactory(messages, language);
const source = parse('AppImage/components/health-status-modal.tsx');
let mapper;
walk(source, n => {
  if (ts.isVariableDeclaration(n) && n.name.getText(source) === 'translateHealthText') mapper = n.initializer;
});
assert.ok(mapper, 'actual modal mapper');
const mapperFactory = new Function('t', compile('const translateHealthText = ' + emit(mapper, source)) + '\nreturn translateHealthText;');
const makeMapper = t => mapperFactory(t);
const select = makeMapper((key, params) => JSON.stringify([key, params || {}]));
const render = (input, locale = 'it', messages = catalogs) => makeMapper(translator(locale, messages))(input);
const format = (template, params) => template.replace(/\{(\w+)\}/g, (token, name) => params[name] === undefined ? token : String(params[name]));
// Frozen EN/IT additions: independent expected values, not candidate-derived.
const expected = {
  "noTemperatureSensor": ["No temperature sensor detected - install lm-sensors if hardware supports it", "Nessun sensore di temperatura rilevato. Installa lm-sensors se l’hardware lo supporta."],
  "noSwapConfigured": ["No swap configured", "Swap non configurato"],
  "noFailedLogins": ["No failed login attempts in 24h", "Nessun tentativo di accesso fallito nelle ultime 24 ore"],
  "pendingSecurityUpdates": ["Security updates pending: {count}", "Aggiornamenti di sicurezza in sospeso: {count}"],
  "pendingSecurityUpdatesUnpatched": ["Security updates pending: {count} (days unpatched: {days})", "Aggiornamenti di sicurezza in sospeso: {count} (giorni senza applicazione: {days})"],
  "pendingSecurityUpdatesDays": ["Security updates pending: {count} (days waiting: {days})", "Aggiornamenti di sicurezza in sospeso: {count} (giorni di attesa: {days})"],
  "cpuHighSustained": ["Sustained high CPU usage", "Utilizzo CPU elevato e prolungato"],
  "temperatureElevated": ["Temperature elevated", "Temperatura elevata"],
  "cpuSustained": ["CPU >{threshold}% sustained for {seconds}s", "CPU >{threshold}% per {seconds} s"],
  "cpuCheckFailed": ["CPU check failed: {error}", "Controllo CPU non riuscito: {error}"],
  "sensorHighSamplesSpan": ["Sensor temperature {temperature}°C >80°C; high samples span {duration}", "Temperatura sensore {temperature}°C >80°C; campioni elevati nell’arco di {duration}"],
  "ramHighSustained": ["High RAM usage sustained", "Utilizzo RAM elevato a lungo"],
  "swapRamPressure": ["Swap nearly full with RAM tight", "Swap quasi pieno e poca RAM disponibile"],
  "ramSustained": ["RAM >{threshold}% sustained for {seconds}s", "RAM >{threshold}% per {seconds} s"],
  "memoryPressure": ["Memory pressure: swap {swapPercent}% used and only {ramAvailablePercent}% RAM available", "Pressione memoria: swap usato al {swapPercent}% e solo {ramAvailablePercent}% di RAM disponibile"],
  "memoryCheckFailed": ["Memory check failed: {error}", "Controllo memoria non riuscito: {error}"],
  "systemNotUpdatedMonths": ["System not updated in {days} days (>18 months)", "Sistema non aggiornato da {days} giorni (>18 mesi)"],
  "systemNotUpdatedYear": ["System not updated in {days} days (>1 year)", "Sistema non aggiornato da {days} giorni (>1 anno)"],
  "runningKernelUpdate": ["Kernel update available for running {kernel}", "Aggiornamento disponibile per il kernel in uso: {kernel}"],
  "kernelPveUpdates": ["Kernel updates available: {kernelCount}; Proxmox updates available: {pveCount}", "Aggiornamenti disponibili: {kernelCount} kernel + {pveCount} Proxmox"],
  "pendingPackageUpdates": ["Package updates pending: {count}", "Aggiornamenti di pacchetti in sospeso: {count}"],
  "updatesAptError": ["Failed to check for updates (apt-get error)", "Controllo aggiornamenti non riuscito (errore apt-get)"],
  "updatesAptTimeout": ["apt-get timed out - repository may be unreachable", "Timeout di apt-get: il repository potrebbe non essere raggiungibile"],
  "kernelPackagesMore": ["{technicalIdentity} (+{count} more)", "{technicalIdentity} (+{count} altri)"],
  "nonRunningKernelUpdates": ["Kernel updates available: {count} (none for the running kernel{optionalKernel})", "Aggiornamenti kernel disponibili: {count} (nessuno per il kernel in uso{optionalKernel})"],
  "unknownDetail": ["Unknown", "Sconosciuto"],
  "pveVersionAvailable": ["PVE {current} -> {new} available", "PVE {current} -> {new} disponibile"],
  "updatesCheckUnavailable": ["Updates check unavailable: {error}", "Controllo aggiornamenti non disponibile: {error}"],
  "fail2banInactive": ["Fail2Ban installed but service not active", "Fail2Ban installato; servizio inattivo"],
  "fail2banCheckUnavailable": ["Unable to check Fail2Ban: {error}", "Impossibile controllare Fail2Ban: {error}"],
  "uptimeKernelAdvice": ["Uptime: {days} days (>1 year; consider updating kernel/system)", "Tempo di attività: {days} giorni (>1 anno; valuta l’aggiornamento di kernel/sistema)"],
  "uptimeUnavailable": ["Unable to determine uptime", "Impossibile determinare il tempo di attività"],
  "failedLoginsWithinThreshold": ["Failed login attempts in 24h: {count} (within threshold)", "Tentativi di accesso falliti nelle ultime 24 ore: {count} (entro la soglia)"],
  "loginCheckUnavailable": ["Unable to check login attempts", "Impossibile controllare i tentativi di accesso"],
  "securityCheckUnavailable": ["Security check unavailable: {error}", "Controllo sicurezza non disponibile: {error}"],
  "certificateExpired": ["Certificate expired", "Certificato scaduto"],
  "certificateExpiresDays": ["Certificate expiry (days): {days}", "Scadenza certificato (giorni): {days}"],
  "certificateInconclusive": ["Certificate check inconclusive", "Controllo certificato non conclusivo"]
};
const cases = [];
// CPU and sensor
cases.push(...[
  ["No temperature sensor detected - install lm-sensors if hardware supports it", "noTemperatureSensor", {}],
  ["Sustained high CPU usage", "cpuHighSustained", {}],
  ["Temperature elevated", "temperatureElevated", {}],
  ["CPU >90% sustained for 180s", "cpuSustained", {"threshold": "90", "seconds": "180"}],
  ["CPU >85.5% sustained for 0s", "cpuSustained", {"threshold": "85.5", "seconds": "0"}],
  ["CPU check failed: permission denied", "cpuCheckFailed", {"error": "permission denied"}],
  ["Sensor temperature 87.5°C >80°C; high samples span 2m 3s", "sensorHighSamplesSpan", {"temperature": "87.5", "duration": "2m 3s"}],
  ["Sensor temperature 81°C >80°C; high samples span 7s", "sensorHighSamplesSpan", {"temperature": "81", "duration": "7s"}]
]);
// Memory
cases.push(...[
  ["No swap configured", "noSwapConfigured", {}],
  ["High RAM usage sustained", "ramHighSustained", {}],
  ["Swap nearly full with RAM tight", "swapRamPressure", {}],
  ["RAM >90% sustained for 60s", "ramSustained", {"threshold": "90", "seconds": "60"}],
  ["RAM >95.5% sustained for 0s", "ramSustained", {"threshold": "95.5", "seconds": "0"}],
  ["Memory pressure: swap 98% used and only 3% RAM available", "memoryPressure", {"swapPercent": "98", "ramAvailablePercent": "3"}],
  ["Memory pressure: swap 0% used and only 0% RAM available", "memoryPressure", {"swapPercent": "0", "ramAvailablePercent": "0"}],
  ["Memory check failed: unavailable", "memoryCheckFailed", {"error": "unavailable"}]
]);
// Updates and technical identities
cases.push(...[
  ["3 security update(s) pending", "pendingSecurityUpdates", {"count": "3"}],
  ["3 security update(s) pending (14 days unpatched)", "pendingSecurityUpdatesUnpatched", {"count": "3", "days": "14"}],
  ["3 security update(s) pending for 14 days", "pendingSecurityUpdatesDays", {"count": "3", "days": "14"}],
  ["System not updated in 549 days (>18 months)", "systemNotUpdatedMonths", {"days": "549"}],
  ["System not updated in 366 days (>1 year)", "systemNotUpdatedYear", {"days": "366"}],
  ["Kernel update available for running 7.0.7-1-pve", "runningKernelUpdate", {"kernel": "7.0.7-1-pve"}],
  ["2 kernel + 4 Proxmox update(s) available", "kernelPveUpdates", {"kernelCount": "2", "pveCount": "4"}],
  ["12 package update(s) pending", "pendingPackageUpdates", {"count": "12"}],
  ["Failed to check for updates (apt-get error)", "updatesAptError", {}],
  ["apt-get timed out - repository may be unreachable", "updatesAptTimeout", {}],
  ["proxmox-kernel-7.0.7-1-pve-signed 7.0.7-1 -> 7.0.7-2 (+2 more)", "kernelPackagesMore", {"technicalIdentity": "proxmox-kernel-7.0.7-1-pve-signed 7.0.7-1 -> 7.0.7-2", "count": "2"}],
  ["proxmox-kernel-7.0:amd64 (+1 more)", "kernelPackagesMore", {"technicalIdentity": "proxmox-kernel-7.0:amd64", "count": "1"}],
  ["linux-image:amd64 1:7.0+deb1~pve -> 1:7.0+deb2~pve (+3 more)", "kernelPackagesMore", {"technicalIdentity": "linux-image:amd64 1:7.0+deb1~pve -> 1:7.0+deb2~pve", "count": "3"}],
  ["2 kernel update(s) available (none for running kernel 7.0.7-1-pve)", "nonRunningKernelUpdates", {"count": "2", "optionalKernel": " 7.0.7-1-pve"}],
  ["2 kernel update(s) available (none for running kernel)", "nonRunningKernelUpdates", {"count": "2", "optionalKernel": ""}],
  ["Unknown", "unknownDetail", {}],
  ["PVE 9.0.3 -> 9.0.4 available", "pveVersionAvailable", {"current": "9.0.3", "new": "9.0.4"}],
  ["PVE 1:9.0.3+deb1~pve -> 1:9.0.4+deb2~pve available", "pveVersionAvailable", {"current": "1:9.0.3+deb1~pve", "new": "1:9.0.4+deb2~pve"}],
  ["Updates check unavailable: timeout", "updatesCheckUnavailable", {"error": "timeout"}]
]);
// Security, uptime and certificates
cases.push(...[
  ["No failed login attempts in 24h", "noFailedLogins", {}],
  ["Fail2Ban installed but service not active", "fail2banInactive", {}],
  ["Unable to check Fail2Ban: not permitted", "fail2banCheckUnavailable", {"error": "not permitted"}],
  ["Uptime 400 days (>1 year, consider updating kernel/system)", "uptimeKernelAdvice", {"days": "400"}],
  ["Unable to determine uptime", "uptimeUnavailable", {}],
  ["3 failed attempts in 24h (within threshold)", "failedLoginsWithinThreshold", {"count": "3"}],
  ["Unable to check login attempts", "loginCheckUnavailable", {}],
  ["Security check unavailable: timeout", "securityCheckUnavailable", {"error": "timeout"}],
  ["Certificate expired", "certificateExpired", {}],
  ["Certificate expires in 30 days", "certificateExpiresDays", {"days": "30"}],
  ["Certificate expires in 0 days", "certificateExpiresDays", {"days": "0"}],
  ["Certificate check inconclusive", "certificateInconclusive", {}]
]);
// Opaque errors are single payloads: no splitting or recursive interpolation.
for (const [key, prefix] of [
  ['cpuCheckFailed', 'CPU check failed: '],
  ['memoryCheckFailed', 'Memory check failed: '],
  ['updatesCheckUnavailable', 'Updates check unavailable: '],
  ['fail2banCheckUnavailable', 'Unable to check Fail2Ban: '],
  ['securityCheckUnavailable', 'Security check unavailable: '],
]) {
  for (const error of ['', ' \t \r\n ', 'first line\nsecond line\r\n{count}; {error} $& \\path "quoted" café', 'Certificate expired; No swap configured\n']) {
    cases.push([prefix + error, key, {error}]);
  }
}
// Execute every case even on RED, so missing families are visible in the log.
let failures = 0;
function check(label, fn) {
  try { fn(); } catch (error) { failures++; console.error(`FAIL ${label}: ${error.message}`); }
}
assert.equal(Object.keys(expected).length, 38, 'frozen additive key count');
assert.deepEqual([...new Set(cases.map(row => row[1]))].sort(), Object.keys(expected).sort(), 'every new key exercised');
for (const row of cases) {
  const [input, key, params] = row;
  const [english, italian] = expected[key];
  check(`${key}: selection`, () => assert.equal(select(input), JSON.stringify(['healthStatus.details.' + key, params])));
  for (const [locale, expected] of [['en', english], ['it', italian]]) {
    check(`${key}: ${locale} catalog`, () => assert.equal(catalogs[locale].healthStatus.details[key], expected));
    check(`${key}: ${locale} output`, () => assert.equal(render(input, locale), format(expected, params)));
  }
  // Shipped translations and fallback are distinct from unconditional missing-key proof.
  for (const locale of Object.keys(catalogs)) {
    const local = catalogs[locale].healthStatus?.details?.[key];
    check(`${key}: shipped ${locale}`, () => assert.equal(render(input, locale), format(local ?? english, params)));
  }
  check(`${key}: injected missing key`, () => assert.equal(
    render(input, 'missing', {...catalogs, missing: {healthStatus: {details: {}}}}), format(english, params)));
}
for (const [input, key, params] of [
  ['All systems operational', 'allOperational', {}],
  ['Normal', 'normal', {}],
  ["No I/O errors in dmesg", "noIoErrors", {}],
  ["Mounted read-write, space OK", "rootFilesystemOk", {}],
  ["No SMART warnings in journal", "noSmartWarnings", {}],
  ["No critical errors", "noCriticalErrors", {}],
  ["No cascading errors", "noCascadingErrors", {}],
  ["No error spikes", "noErrorSpikes", {}],
  ["No persistent patterns", "noPersistentPatterns", {}],
  ["Certificate valid", "certificateValid", {}],
  ["Cluster detected (corosync.conf present)", "clusterDetected", {}],
  ["Active", "active", {}],
  ["UP", "up", {}],
  ["Kernel/PVE up to date", "kernelUpToDate", {}],
  ["Proxmox VE is up to date", "proxmoxUpToDate", {}],
  ["No security updates pending", "noSecurityUpdates", {}],
  ["No container startup errors", "noContainerErrors", {}],
  ["No OOM events detected", "noOomEvents", {}],
  ["No QMP timeouts detected", "noQmpTimeouts", {}],
  ["No VM startup failures", "noVmFailures", {}],
  ["Dismissed by user", "dismissedByUser", {}],
  ['Latency 2.5ms to gateway', 'gatewayLatency', {latency: '2.5'}],
  ['51 failed login attempts in 24h', 'failedLogins', {count: '51'}],
  ['2 IP(s) currently banned by Fail2Ban (jails: sshd, pve)', 'fail2banBannedIps', {count: '2', jails: 'sshd, pve'}],
  ['Uptime 1 day', 'uptimeDays', {count: '1'}],
  ['Uptime 2 days', 'uptimeDays', {count: '2'}],
  ['9 package(s) pending', 'pendingPackages', {count: '9'}],
  ['Last updated 10 day(s) ago', 'updatedDaysAgo', {count: '10'}],
  ['42.5% used', 'storageUsage', {percent: '42.5'}],
  ['Storage: 2 Proxmox storages unavailable: local, nas (startup)', 'startupStoragesChecking', {storages: 'local, nas'}],
  ['Storage: nas not yet available (startup)', 'startupStorageChecking', {storage: 'nas'}],
  ['nas not yet available (startup)', 'startupStorageChecking', {storage: 'nas'}],
  ["[Startup] Storage 'nas' is configured but not found on the server. (checking...)", 'startupStorageNotFound', {storage: 'nas'}],
  ["[Startup] Storage 'nas' is not available (connection error or backend issue). (checking...)", 'startupStorageUnavailable', {storage: 'nas'}],
  ["[Startup] Storage 'nas' has status: offline. (checking...)", 'startupStorageStatus', {storage: 'nas', status: 'offline'}],
  ['nfs storage available', 'storageAvailable', {type: 'nfs'}],
  ['nfs mount reachable', 'mountReachable', {type: 'nfs'}],
  ['rootfs 21.5% used (3G)', 'rootfsUsed', {percent: '21.5', size: '3G'}],
  ['2 running CT(s) within safe rootfs usage', 'runningCtsSafe', {count: '2'}],
  ['3 PVE block storage(s) within safe usage', 'pveStorageSafe', {count: '3'}],
  ['4 remote mount(s) healthy', 'remoteMountsHealthy', {count: '4'}],
]) {
  check(`existing ${key}`, () => assert.equal(select(input), JSON.stringify(['healthStatus.details.' + key, params])));
  for (const locale of Object.keys(catalogs)) check(`existing ${key} ${locale}`, () => assert.equal(render(input, locale), translator(locale)('healthStatus.details.' + key, params)));
}
for (const input of ['', undefined]) check('empty input', () => assert.equal(render(input), ''));
const passthrough = [
  'New backend reason', 'Disk check unavailable: unsupported',
  'custom {count}; /srv/path\nline2',
  'toString', 'constructor', '__proto__', 'hasOwnProperty',
  'Sensor temperature 87°C still elevated',
  'Uptime 400 days, system recently updated',
  'Certificate expired; No swap configured',
  'Normal; 3 security update(s) pending',
  '3 security update(s) pending; Certificate expired',
  'CPU >90% sustained for 180s; Temperature elevated',
  'Sensor temperature 87.5°C >80°C; high samples span 2m 3s; Certificate expired',
  'System not updated in 549 days (>18 months); No swap configured',
  'unknown', 'Certificate expires in -1 days', 'Certificate expires in 1 day',
  'certificate expired', 'No swap configured ', ' No swap configured',
  'CPU >90% sustained for 180 seconds', 'CPU >90% sustained for 180s extra',
  'CPU >90..5% sustained for 180s', 'CPU >.5% sustained for 180s',
  'RAM >95..5% sustained for 60s',
  'Sensor temperature 87..5°C >80°C; high samples span 2m 3s',
  'Sensor temperature 87°C >80°C; high samples span 2m',
  'Memory pressure: swap 98.5% used and only 3% RAM available',
  '3 security updates pending', '3 security update(s) pending (14 days unpatched) extra',
  'Kernel update available for running 7.0.7-1-pve (extra)',
  '2 kernel update(s) available (none for running kernel 7.0.7-1-pve extra)',
  'PVE 9.0.3 -> 9.0.4 available (extra)',
  'not a package (+2 more)', 'proxmox-kernel-7.0 (+2 more) extra',
  'proxmox-kernel-7.0 1 -> 2 -> 3 (+2 more)',
  'proxmox-kernel-7.0 1 -> 2', // Pure technical identities need no translation.
  'proxmox-kernel-7.0:amd64',
];
// Non-error atoms with trailing line breaks retain their exact bytes.
for (const [input, key] of cases) {
  if (!key.endsWith('CheckFailed') && !key.endsWith('CheckUnavailable')) {
    passthrough.push(input + '\n', input + '\r\n');
  }
}
for (const input of passthrough) {
  check(`passthrough ${JSON.stringify(input)}`, () => assert.equal(select(input), input));
  for (const locale of Object.keys(catalogs)) check(`passthrough ${locale} ${JSON.stringify(input)}`, () => assert.equal(render(input, locale), input));
}
if (failures) throw new Error(`${failures} health-text assertions failed`);
console.log(`PASS: actual health mapper/provider; ${new Set(cases.map(row => row[1])).size} new keys, ${cases.length} message variants, ${Object.keys(catalogs).length} shipped locales and unconditional missing-key fallback`);
