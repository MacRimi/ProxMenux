// Shipped PBS code with only transport, hooks and UI primitives replaced.
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const ts = require('typescript');
const compile = source => ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX}}).outputText;
const catalogs = Object.fromEntries(['en','sk'].map(l => [l, JSON.parse(fs.readFileSync(`AppImage/messages/${l}/common.json`))]));
const translate = locale => (key, params = {}) => {
  const value = key.split('.').reduce((tree, part) => tree?.[part], catalogs[locale]);
  assert.equal(typeof value, 'string', key);
  return value.replace(/\{(\w+)\}/g, (m,k) => params[k] ?? m);
};
const library = {exports: {}};
vm.runInNewContext(compile(fs.readFileSync('AppImage/lib/pbs-messages.ts','utf8')), library);
const messages = library.exports;
const failure = code => Object.assign(new Error('RAW DIAGNOSTIC'), {body: {error:'RAW DIAGNOSTIC',code}});
const flatten = n => !n || typeof n === 'boolean' ? [] : Array.isArray(n) ? n.flatMap(flatten)
  : typeof n === 'object' ? n.type === 'Dialog' && !n.props.open ? [] : [n,...flatten(n.props?.children)] : [n];
const text = n => flatten(n).filter(n => typeof n === 'string' || typeof n === 'number').join('');

function fixture(locale='sk', options={}) {
  let cursor=0, slots=[], effects=[], tree, apiError, reloadError;
  const calls=[], confirmations=[], reloads=[];
  const servers={local_available:false,servers:[{id:'saved',name:'Saved PBS',url:'https://saved.invalid:8007',token_id:'audit@pbs!monitor',has_token:true,fingerprint:''}],detected:[]};
  const status={name:'Fixture',version:'4.2.5',fetched_at:1700000000,services:{'proxmox-backup':'inactive'},datastores:[],tasks:[],sync:[],verify:[],prune:[],errors:{}};
  const t=translate(locale), loaded={};
  const jsx=(type,props) => typeof type === 'function' ? type(props) : ({type,props});
  const react={useState(initial){const i=cursor++;if(!(i in slots))slots[i]=typeof initial==='function'?initial():initial;return [slots[i],value=>{slots[i]=typeof value==='function'?value(slots[i]):value;}];},
    useEffect(fn,deps){const i=cursor++, old=slots[i];if(!old||deps.some((d,j)=>d!==old[j]))effects.push(fn);slots[i]=deps;}};
  function requireModule(name) {
    if(name==='react')return react;
    if(name==='react/jsx-runtime')return {jsx,jsxs:jsx,Fragment:'Fragment'};
    if(name==='swr')return {default:key=>({data:key?.startsWith('/api/pbs/status')?status:key?servers:undefined,error:options.loadError,
      isLoading:false,mutate:async()=>{reloads.push(key);if(reloadError)throw reloadError;}})};
    if(name.includes('i18n/provider'))return {useT:()=>t,useI18n:()=>({language:locale})};
    if(name.includes('pbs-messages'))return messages;
    if(name.includes('api-config'))return {fetchApi:async(path,opts)=>{calls.push({path,...opts});if(apiError)throw apiError;return {id:'new',success:true};}};
    if(name.endsWith('pbs-problem-message'))return load('AppImage/components/pbs-problem-message.tsx');
    if(name.endsWith('pbs-datastore-usage'))return load('AppImage/components/pbs-datastore-usage.tsx');
    if(name.includes('lib/utils'))return {formatStorage:n=>String(n)+' GB'};
    return new Proxy({}, {get:(_,key)=>key});
  }
  function load(path) {if(loaded[path])return loaded[path];const e={};loaded[path]=e;
    vm.runInNewContext(compile(fs.readFileSync(path,'utf8')), {exports:e,require:requireModule,Date,window:{confirm:message=>{confirmations.push(message);return options.confirm===true;}}});return e;}
  const panel=load('AppImage/components/pbs-panel.tsx').PBSPanel;
  return {t,servers,status,calls,confirmations,reloads,jsx,requireModule,
    render(props){cursor=0;effects=[];tree=panel(props);effects.forEach(fn=>fn());return tree;},
    nodes:()=>flatten(tree),text:()=>text(tree),
    button(label){const n=flatten(tree).find(n=>n.type==='Button'&&text(n)===label);assert.ok(n,label);return n;},
    input(field){const n=flatten(tree).find(n=>n.type==='Input'&&n.props.id==='pbs-'+field);assert.ok(n,field);return n;},
    select(label){const n=flatten(tree).find(n=>n.type==='Select'&&flatten(n).some(n=>n.props?.['aria-label']===label));assert.ok(n,label);return n;},
    fail:e=>{apiError=e;},failReload:e=>{reloadError=e;},load,
  };
}

function overview(locale, sourcePath='AppImage/components/system-overview.tsx') {
  const source=fs.readFileSync(sourcePath,'utf8'), ast=ts.createSourceFile('overview.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX), branches=[];
  function visit(n){if(ts.isConditionalExpression(n)&&n.condition.getText(ast)==='isPbs'&&n.whenTrue.getText(ast).includes('pbs.datastores'))branches.push(n.whenTrue.getText(ast));ts.forEachChild(n,visit);}visit(ast);
  assert.equal(branches.length,2,'overview summary and storage details both consume PBS');
  const f=fixture(locale);
  for(const branch of branches) {
    for(const state of ['partial','network','empty','loading']) {
      const pbsStatus=state==='loading'||state==='network'?undefined:{datastores:state==='empty'?[]:null,errors:{datastores:'RAW DIAGNOSTIC'},error_details:{datastores:{code:'pbs_token_rejected'}}};
      const context={isPbs:true,pbsStatus,pbsError:state==='network'?failure('pbs_connect_failed'):undefined,datastores:pbsStatus?.datastores,
        t:f.t,require:f.requireModule,pbsDiagnostic:messages.pbsDiagnostic,PBSProblemMessage:f.load('AppImage/components/pbs-problem-message.tsx').PBSProblemMessage,
        DatastoreUsageRow:f.load('AppImage/components/pbs-datastore-usage.tsx').DatastoreUsageRow};
      for(const name of ['Card','CardHeader','CardTitle','CardContent','Database','Badge'])context[name]=name;
      vm.runInNewContext(compile('exports.result=('+branch+');'),{...context,exports:context});
      const rendered=text(context.result);
      if(state==='partial') {assert.ok(rendered.includes(f.t('pbs.errors.tokenRejected')));assert.ok(!rendered.includes(f.t('pbs.loading')));assert.ok(!flatten(context.result).some(n=>n.props?.className?.includes('animate-pulse')));}
      if(state==='network')assert.ok(rendered.includes(f.t('pbs.errors.connectFailed')));
      if(state==='empty')assert.ok(rendered.includes(f.t('pbs.noDatastores')));
    }
  }
}

async function main() {
  const backend=fs.readFileSync('AppImage/scripts/pbs_manager.py','utf8')+fs.readFileSync('AppImage/scripts/flask_pbs_routes.py','utf8');
  const codes=new Set([...backend.matchAll(/(?:code|rejected_code)="(pbs_\w+)"/g)].map(m=>m[1]));
  for(const locale of ['en','sk']) {
    const t=translate(locale);
    for(const code of codes) {
      if(code==='pbs_unknown')continue;
      const err=failure(code);err.body.params={count:32};
      assert.notEqual(messages.pbsErrorText(err,t),t('pbs.loadFailed'),code);
      assert.ok(!messages.pbsErrorText(err,t).includes('RAW'));
    }
    for(const err of [null,undefined,'raw',new Error('raw'),{body:null},{code:'constructor'},{code:'__proto__'},{code:'future'},
      ...[null,0,-1,1.2,'32',Infinity,NaN,2**54].map(count=>({code:'pbs_connection_limit',params:{count}}))]) {
      assert.equal(messages.pbsErrorText(err,t),t('pbs.loadFailed'));
    }
    assert.equal(messages.pbsResultText('OK',t),t('pbs.states.ok'));
    assert.equal(messages.pbsResultText('WARNINGS: 2',t),t('pbs.states.warnings',{count:2}));
    assert.equal(messages.pbsResultText(undefined,t),t('pbs.states.unknown'));
    assert.equal(messages.pbsResultText('unknown',t),t('pbs.states.unknown'));
    assert.equal(messages.pbsResultText('TASK ERROR: raw',t),t('pbs.states.error'));
    for(const n of [-1,NaN,Infinity])assert.equal(messages.formatPBSDuration(n,t),'—');
    for(const [n,label] of [[0,'0 s'],[59,'59 s'],[60,'1 min 0 s'],[3599,'59 min 59 s'],[3600,'1 h 0 min'],[86399,'23 h 59 min'],[86400,'1 d 0 h']])assert.equal(messages.formatPBSDuration(n,t),label);
    assert.equal(messages.pbsTaskType('garbage_collection',t),t('pbs.taskTypes.garbageCollection'));
    assert.equal(messages.pbsTaskType('future',t),t('pbs.taskTypes.other',{type:'future'}));
    assert.equal(messages.pbsServiceState('constructor',t),t('pbs.serviceStates.unknown'));
    assert.equal(t('pbs.url'),locale==='sk'?'Adresa HTTPS':'HTTPS address');
    const diagnosticFixture=fixture(locale),problem=diagnosticFixture.load('AppImage/components/pbs-problem-message.tsx').PBSProblemMessage;
    for(const code of codes){
      if(code==='pbs_unknown')continue;
      const err=failure(code);err.body.params={count:32};
      const rendered=problem({problem:err,raw:'RAW DIAGNOSTIC'});
      assert.ok(!text(rendered).includes('RAW DIAGNOSTIC'),'Known '+code+' must not repeat an English application message');
      assert.ok(!flatten(rendered).some(n=>n.type==='details'));
    }
    for(const code of ['future','__proto__','constructor']){
      const rendered=problem({problem:failure(code),raw:'RAW <img> DIAGNOSTIC'});
      assert.ok(text(rendered).includes('RAW <img> DIAGNOSTIC'));assert.ok(flatten(rendered).some(n=>n.type==='details'));
    }
    const unknown=fixture(locale);unknown.status.tasks=[{upid:'unknown',endtime:1700000000,status:'unknown'}];unknown.status.sync=[{id:'unknown','last-run-state':'unknown'}];
    unknown.render();unknown.render();
    const unknownBadges=unknown.nodes().filter(n=>n.type==='Badge'&&text(n)===t('pbs.states.unknown'));
    assert.equal(unknownBadges.length,2);assert.ok(unknownBadges.every(n=>!n.props.className.includes('red-')));
    unknown.status.tasks=[{upid:'warn',endtime:1700000000,status:'WARNINGS: 3'},{upid:'raw',endtime:1700000000,status:'RAW EXTERNAL TASK ERROR'}];unknown.status.sync=[];unknown.render();
    const taskDetails=unknown.nodes().filter(n=>n.type==='details');assert.equal(taskDetails.length,1);assert.ok(text(taskDetails[0]).includes('RAW EXTERNAL TASK ERROR'));
    const f=fixture(locale);f.render();f.render();f.button(t('pbs.manage')).props.onClick();f.render();
    assert.equal(f.input('url').props['aria-describedby'],'pbs-url-help');
    assert.ok(f.text().includes(t('pbs.urlHelp')));assert.ok(f.text().includes(t('pbs.usernameHelp')));
    f.input('name').props.onChange({target:{value:'Draft'}});f.render();
    f.input('password').props.onChange({target:{value:'fake-one-time-password'}});f.render();
    f.button(t('pbs.cancel')).props.onClick();f.render();assert.equal(f.calls.length,0);
    f.button(t('pbs.manage')).props.onClick();f.render();assert.equal(f.input('password').props.value,'');
    f.input('name').props.onChange({target:{value:'Draft'}});f.render();f.input('url').props.onChange({target:{value:'http://bad.invalid'}});f.render();
    f.fail(failure('pbs_invalid_url'));await f.button(t('pbs.save')).props.onClick();f.render();
    assert.ok(f.text().includes(t('pbs.errors.invalidUrl')));assert.equal(f.input('url').props.value,'http://bad.invalid');
    assert.equal(f.calls[0].path,'/api/pbs/servers/login');assert.ok(!Object.hasOwn(JSON.parse(f.calls[0].body),'token_secret'));
    f.button(t('pbs.methodToken')).props.onClick();f.render();await f.button(t('pbs.save')).props.onClick();f.render();
    assert.ok(f.text().includes(t('pbs.tokenSecretHelp')));assert.ok(!f.text().includes(t('pbs.tokenSecretKeepHelp')));
    assert.equal(f.input('token_secret').props['aria-describedby'],'pbs-token_secret-help');
    assert.equal(f.calls[1].path,'/api/pbs/servers');assert.ok(!Object.hasOwn(JSON.parse(f.calls[1].body),'password'));
    f.select(t('pbs.editConnection')).props.onValueChange('saved');f.render();await f.button(t('pbs.remove')).props.onClick();f.render();
    assert.ok(f.text().includes(t('pbs.tokenSecretKeepHelp')));assert.ok(!f.text().includes(t('pbs.tokenSecretHelp')));
    assert.deepEqual(f.confirmations,[t('pbs.removeConfirm')]);assert.equal(f.calls.length,2,'Declined remove has no DELETE');
    const remove=fixture(locale,{confirm:true});remove.render();remove.render();remove.button(t('pbs.manage')).props.onClick();remove.render();remove.select(t('pbs.editConnection')).props.onValueChange('saved');remove.render();
    await remove.button(t('pbs.remove')).props.onClick();remove.render();assert.equal(remove.calls.length,1);assert.equal(remove.calls[0].method,'DELETE');
    const failedRemove=fixture(locale,{confirm:true});failedRemove.render();failedRemove.render();failedRemove.button(t('pbs.manage')).props.onClick();failedRemove.render();failedRemove.select(t('pbs.editConnection')).props.onValueChange('saved');failedRemove.render();failedRemove.fail(new Error('network failure'));
    await failedRemove.button(t('pbs.remove')).props.onClick();failedRemove.render();assert.ok(failedRemove.text().includes(t('pbs.removeFailed')));assert.equal(failedRemove.calls.length,1);
    const failedReload=fixture(locale);failedReload.render();failedReload.render();failedReload.button(t('pbs.manage')).props.onClick();failedReload.render();failedReload.failReload(new Error('raw reload'));
    for(const [field,value] of Object.entries({name:'Valid',url:'https://fixture.invalid',username:'root@pam',password:'fake'})){failedReload.input(field).props.onChange({target:{value}});failedReload.render();}
    assert.equal(failedReload.button(t('pbs.save')).props.disabled,false);
    await failedReload.button(t('pbs.save')).props.onClick();failedReload.render();assert.equal(failedReload.calls.length,1,'No automatic mutation retry after refresh fails');assert.ok(failedReload.text().includes(t('pbs.savedRefreshFailed')));
    const removeReload=fixture(locale,{confirm:true});removeReload.render();removeReload.render();removeReload.button(t('pbs.manage')).props.onClick();removeReload.render();removeReload.select(t('pbs.editConnection')).props.onValueChange('saved');removeReload.render();removeReload.failReload(new Error('network'));
    await removeReload.button(t('pbs.remove')).props.onClick();removeReload.render();assert.equal(removeReload.calls.length,1);assert.ok(removeReload.text().includes(t('pbs.removedRefreshFailed')));
    const store=f.load('AppImage/components/pbs-datastore-usage.tsx').PBSDatastoreCard({store:{name:'Offline',total:null,used:null,error:'RAW DIAGNOSTIC',error_code:'pbs_datastore_offline'}});
    assert.ok(text(store).includes(t('pbs.errors.datastoreOffline')));assert.ok(!text(store).includes('0 GB'));
    overview(locale);
  }
  console.log('PASS: all structured PBS error codes, EN/SK/unknown diagnostics, forms/login/token/remove/cancel, no automatic retry, task/service/duration states and both real overview branches');
}
main().catch(error=>{console.error(error);process.exitCode=1});
module.exports={fixture,overview};
