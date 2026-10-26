const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createRequire} = require('node:module');
const app = path.resolve(__dirname, '../AppImage');
const appRequire = createRequire(path.join(app,'package.json'));
const ts = appRequire('typescript');
const cache = new Map();
function load(file) {
  file = path.resolve(file);
  if (cache.has(file)) return cache.get(file).exports;
  const mod = {exports:{}}; cache.set(file,mod);
  const js = ts.transpileModule(fs.readFileSync(file,'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  new Function('require','module','exports',js)(name => {
    if (!name.startsWith('.')) return appRequire(name);
    const base=path.resolve(path.dirname(file),name);
    return load(fs.existsSync(base+'.ts') ? base+'.ts' : base+'.tsx');
  },mod,mod.exports);
  return mod.exports;
}
function translate(locale) {
  const messages=JSON.parse(fs.readFileSync(path.join(app,'messages',locale,'common.json')));
  return (key,params={}) => {
    const text=key.split('.').reduce((o,k)=>o?.[k],messages);
    return typeof text==='string' ? text.replace(/\{(\w+)\}/g,(m,k)=>params[k] ?? m) : key;
  };
}
global.window={location:{origin:'http://localhost'}};
const presentation=load(path.join(app,'lib/audit-presentation.ts'));
const {buildAuditDocument}=load(path.join(app,'lib/audit-document.ts'));
const {storageDiagram}=load(path.join(app,'lib/report-diagrams.ts'));
const base=(id,classification,affected=[])=>({check_id:id,area:id.split('.')[0],severity:'INFO',classification,summary_key:null,summary_params:{},affected,evidence:null});
const coverage=base('backup.guest_coverage','observation',[
  ...[109,111,112,114,9510].map(vmid=>({vmid,classification:'observation',reason_key:'noJobSelectsGuest'})),
  ...['sata0','sata1','sata2','sata3','scsi1'].map(volume=>({vmid:106,volume,reason_key:'dataExcludedFromBackup',classification:'observation'})),
  {vmid:110,volume:'scsi1',reason_key:'dataExcludedFromBackup',classification:'observation'}]);
const lynis=base('security.lynis_warnings','observation',[...['enp3s0','tap106i0','tap105i0'].map(details=>({test:'NETW-3015',message:'Found promiscuous interface',details,solution:'Do not show this advice',classification:'observation'}))]);
const age=base('backup.last_backup_age','warning',[{vmid:101,storage:'PBS-Cloud',classification:'warning',reason_key:'olderThanSchedule'},{vmid:109,storage:'any',classification:'observation',reason_key:'noStoredBackupUnscheduled'}]);
age.evidence=JSON.stringify([{vmid:101,expected_storage:'PBS-Cloud',last_backup:1787763643,age_hours:259.1,max_age_hours:252}]);
for(const locale of ['en','es','de','fr','it','pt','sk','sv']) {
  const t=translate(locale);
  assert(!t('audit.checks.backup.last_backup_age.rationale').includes('ProxMenux'));
  assert(!t('audit.presentation.limitReference').includes('ProxMenux'));
  const groups=presentation.presentFinding(coverage,t,locale);
  assert.equal(groups[0].rows.length,5); assert.equal(groups[1].rows.length,2);
  assert(presentation.affectedDescription(coverage,t).includes('6'));
  assert(!presentation.affectedDescription(coverage,t).includes('11'));
  const lxcExcluded=base('backup.guest_coverage','observation',[{vmid:120,name:'container',type:'lxc',volume:'mp0',reason_key:'dataExcludedFromBackup',classification:'observation'}]);
  assert.equal(presentation.presentFinding(lxcExcluded,t,locale)[0].rows[0].cells[0],'container · LXC 120');
  const unavailable=base('backup.last_backup_age','unverified',[{vmid:120,storage:'offline',classification:'unverified',reason_key:'destinationUnavailable'}]);
  const unavailableText=JSON.stringify(presentation.presentFinding(unavailable,t,locale));
  assert(!unavailableText.includes(t('audit.presentation.notFound')));
  assert(unavailableText.includes(t('audit.classifications.unverified')));
  const text=JSON.stringify(presentation.presentFinding(lynis,t,locale));
  assert(!text.includes('Do not show this advice'));
  assert(text.includes('tap106i0'));
  assert.equal(presentation.presentFinding(lynis,t,locale).length,1);
  assert.equal(presentation.presentFinding(age,t,locale).length,2);
  assert.notEqual(presentation.auditDuration(259.1,locale),presentation.auditDuration(252,locale));
  for(const [policy,labelKey] of [['schedule and grace','limitSchedule'],['declared recovery objective','limitDeclared'],['fallback; no recovery objective declared and schedule not read','limitReference']]) {
    const data={...age,affected:[age.affected[0]],evidence:JSON.stringify([{vmid:101,expected_storage:'PBS-Cloud',last_backup:1787763643,age_hours:259.1,max_age_hours:252,age_policy:policy}])};
    const group=presentation.presentFinding(data,t,locale)[0];
    assert(group.columns.includes(t('audit.presentation.backupAge')));
    assert(group.columns.includes(t('audit.presentation.backupLimit')));
    assert(!group.columns.includes(t('audit.presentation.ageLimit')));
    assert(group.rows[0].cells.includes(presentation.auditDuration(259.1,locale)));
    assert(group.rows[0].cells.some(cell=>cell.includes(t('audit.presentation.'+labelKey)) && cell.includes(presentation.auditDuration(252,locale))));
  }
  const legacyText=JSON.stringify(presentation.presentFinding(age,t,locale));
  assert(!legacyText.includes(t('audit.presentation.limitSchedule')));
  const implicitDestination={...age,affected:[{vmid:112,storage:'local',classification:'warning',reason_key:'olderThanFallback'}],evidence:JSON.stringify([{vmid:112,expected_storage:'any visible destination (no explicit target)',storage:'local',last_backup:1787763643,age_hours:800,max_age_hours:720,age_policy:'fallback; no recovery objective declared and schedule not read'}])};
  const implicitText=JSON.stringify(presentation.presentFinding(implicitDestination,t,locale));
  assert(implicitText.includes(presentation.auditDuration(720,locale)),
    `${locale}: a backup without an explicit job destination lost its limit`);
  const failedRuns=base('backup.job_results','warning',[
    {vmid:106,status:'job errors',when:1787760000,upid:'UPID:first',classification:'warning',reason_key:'backupRunFailed'},
    {vmid:106,status:'job errors',when:1787763600,upid:'UPID:last',classification:'warning',reason_key:'backupRunFailed'},
    {vmid:110,status:'storage unavailable',when:1787767200,upid:'UPID:other',classification:'warning',reason_key:'backupRunFailed'},
  ]);
  const failedGroups=presentation.presentFinding(failedRuns,t,locale);
  assert.equal(failedGroups.length,1);
  assert.equal(failedGroups[0].rows.length,2,
    `${locale}: repeated backup failures were not grouped`);
  assert.equal(failedGroups[0].rows.find(row=>row.cells[0].includes('106')).cells[1],'2');
  assert(failedGroups[0].rows.some(row=>row.cells.includes('UPID:last')),
    `${locale}: the latest backup task reference was not retained`);
  const connected={...base('storage.connected_storage','conformant'),evidence:JSON.stringify({storages:[
    {storage:'store-fixture',type:'pbs',status:'active',dependencies:[{vmid:101}],jobs:['backup-1'],capacity_known:true,used_percent:42.5},
  ],scope:'PVE-side observations only'})};
  const connectedGroups=presentation.presentFinding(connected,t,locale);
  assert.equal(connectedGroups.length,1);
  assert.deepEqual(connectedGroups[0].columns,[t('audit.document.storage'),t('audit.document.type'),
    t('audit.document.state'),t('audit.presentation.capacity'),t('audit.presentation.fact')]);
  assert(connectedGroups[0].rows[0].cells.some(cell=>cell.includes('42')),
    `${locale}: connected storage capacity was not presented`);
  const thin={...base('storage.thin_pool_overprovisioning','warning',[
    {pool:'pve/data',metric:'metadata',classification:'warning',reason_key:'thinMetadataPressure'},
  ]),evidence:JSON.stringify([{pool:'pve/data',allocated_bytes:214748364800,
    pool_bytes:107374182400,allocation_percent:200,data_percent:81.2,metadata_percent:92.4}])};
  const thinGroups=presentation.presentFinding(thin,t,locale);
  assert.equal(thinGroups.length,1);
  assert.deepEqual(thinGroups[0].columns,[t('audit.presentation.resource'),
    t('audit.presentation.capacity'),t('audit.presentation.data'),
    t('audit.presentation.metadata'),t('audit.presentation.fact')]);
  assert(thinGroups[0].rows[0].cells[1].includes('GiB'),
    `${locale}: thin-pool byte values were not made readable`);
  const passing={...base('system.time_synchronisation','conformant'),evidence:'NTP: yes\nNTPSynchronized: yes'};
  const input={profile:'full',run:null,findings:[coverage,age,lynis,passing,base('system.security_updates','unverified')],inventory:null,t,locale};
  const html=buildAuditDocument(input);
  const header=html.split('<div class="exec-box">')[1].split('<div class="audit-counters">')[0];
  assert(header.includes('<strong>4/5</strong>'));
  assert(header.includes('stroke-dasharray="80 100"'));
  assert(header.includes(t('audit.presentation.verified')));
  assert(!header.includes('health-ring'));
  assert(!header.includes('health-lbl'));
  assert(!header.includes('15 de 26'));
  assert(header.includes('audit-result-heading'));
  assert(header.includes('stroke="currentColor"'));
  const checkedHtml=html.split('id="verified-checks"')[1].split('id="unverified-checks"')[0];
  assert.equal((checkedHtml.match(/href="#finding-/g)||[]).length,4);
  assert(checkedHtml.includes(t('audit.presentation.verifiedChecks')+' · 4'));
  assert(checkedHtml.includes(t('audit.checks.system.time_synchronisation.title')));
  assert(!checkedHtml.includes('href="#finding-system.security_updates"'));
  assert(html.indexOf('id="verified-checks"') < html.indexOf(t('audit.presentation.overview')));
  assert(!html.includes('audit.document.area'));
  for(const [findings,expected] of [
    [[base('x','critical'),base('y','observation'),base('z','not_applicable')],'2/2'],
    [[{...base('x','warning'),incomplete:true,decision:'accepted'},base('y','conformant')],'1/2'],
    [[{...base('x','unverified'),decision:'accepted'}],'0/1'],
    [[base('x','not_applicable')],'—'],
    [[],'—']]) {
    const doc=buildAuditDocument({...input,findings});
    assert(doc.includes(`<strong>${expected}</strong>`));
    const verifiedSection=doc.split('id="verified-checks"')[1]?.split('</table>')[0] || '';
    const expectedCount=expected==='—'?0:Number(expected.split('/')[0]);
    assert.equal((verifiedSection.match(/href="#finding-/g)||[]).length,expectedCount);
    if(expected==='—') assert(doc.includes('stroke-dasharray="0 100"'));
  }
  assert(!html.includes('health-icon" style="font-size:26px'));
  assert(html.includes(t('audit.presentation.incomplete')));
  assert(!html.includes('{count}'));
  assert(!html.includes('audit.presentation.'));
  const main=html.split('id="evidence-')[0];
  assert(!main.includes('noJobSelectsGuest'));
  assert(!main.includes('Do not show this advice'));
  assert(html.includes(t('audit.presentation.evidenceObserved')),
    `${locale}: conformant findings have no visible evidence`);
  assert(!html.includes('id="evidence-system.time_synchronisation"'),
    `${locale}: conformant raw evidence still bloats the appendix`);
  const structuredPassing=buildAuditDocument({...input,findings:[connected]});
  assert.equal((structuredPassing.match(/store-fixture/g)||[]).length,1,
    `${locale}: structured conformant evidence was printed twice`);
  const dangerous={...coverage,affected:[{vmid:109,name:'<img src=x onerror=alert(1)>',classification:'observation'}]};
  assert(!buildAuditDocument({...input,findings:[dangerous]}).includes('<img src=x'));
}
const diagram=storageDiagram([{vmid:1,name:'one',disks:[{storage:'local'},{storage:'local'}],backups:[]}],{guests:'Guests',storage:'Storage',backup:'Jobs',unprotected:'No job'});
assert(!diagram.includes('>2</text>'));
console.log('Audit presentation: eight languages, truthful counts, calendar age, Lynis grouping, no advice, escaping and incomplete results passed.');
module.exports={load,translate,base,coverage,age,lynis,buildAuditDocument};
