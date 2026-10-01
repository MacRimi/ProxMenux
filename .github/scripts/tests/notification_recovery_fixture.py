"""Pinned, inert recovery review. No operational module imports or threads.
Run with python3 -S under bwrap --unshare-net; DBs and export use TMPDIR.
"""
import ast, contextlib, datetime, hashlib, io, json, os, pathlib, sqlite3, subprocess, sys, tarfile, tempfile, threading, types, typing
from unittest.mock import patch
REPO=pathlib.Path('/home/martino/projects/proxmox/notification-maintainer-followup')
BASE=datetime.datetime(2026,9,30,20,0,0).timestamp()
class Clock(datetime.datetime):
    epoch=BASE
    tick=0.0
    @classmethod
    def now(cls,tz=None):
        value=cls.fromtimestamp(cls.epoch,tz)
        cls.epoch+=cls.tick
        return value
TIME=types.SimpleNamespace(time=lambda:Clock.epoch)

def extract(path,name,owner,ns):
    tree=ast.parse(path.read_text())
    nodes=tree.body if owner is None else next(n.body for n in tree.body if isinstance(n,ast.ClassDef) and n.name==owner)
    node=next(n for n in nodes if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
    node.decorator_list=[]
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),ns)
    return ns[name]

from notification_fixture import SCRIPTS as scripts
pns=dict(vars(typing),datetime=Clock,timedelta=datetime.timedelta,json=json,sqlite3=sqlite3,contextmanager=contextlib.contextmanager,re=__import__('re'),_re_disk_base=__import__('re'))
pns['disk_base_name']=extract(scripts/'health_persistence.py','disk_base_name',None,pns)
methods={n:extract(scripts/'health_persistence.py',n,'HealthPersistence',pns) for n in ('_get_conn','_db_connection','_init_database','record_error','_record_error_impl','resolve_error','_resolve_error_impl','get_recovery_evidence','_record_event','_entity_from_details','clear_error','get_active_errors','is_error_active','is_error_acknowledged','_get_setting_impl','get_setting','set_setting','acknowledge_error','_acknowledge_error_impl','get_excluded_interface_names')}
def make_store(directory):
    s=types.SimpleNamespace(db_path=pathlib.Path(directory)/'health.sqlite',_db_lock=threading.RLock(),DEFAULT_SUPPRESSION_HOURS=24,CATEGORY_SETTING_MAP={})
    for n,f in methods.items():
        if n=='_entity_from_details':setattr(s,n,f)
        elif n=='_db_connection':setattr(s,n,types.MethodType(contextlib.contextmanager(f),s))
        else:setattr(s,n,types.MethodType(f,s))
    s._init_database()
    return s
def sql(s,query,args=()):
    with s._db_connection() as c:
        data=c.execute(query,args).fetchall();c.commit();return data
def record(s,key='cpu_usage',category='cpu',reason='CPU high',details=None):
    Clock.epoch=BASE-600
    with patch.dict(sys.modules,{'os':types.SimpleNamespace(path=types.SimpleNamespace(exists=lambda p:True))}):s.record_error(key,category,'WARNING',reason,details)
    Clock.epoch=BASE-10
    with patch.dict(sys.modules,{'os':types.SimpleNamespace(path=types.SimpleNamespace(exists=lambda p:True))}):s.record_error(key,category,'WARNING',reason,details)
    Clock.epoch=BASE
    assert s.get_active_errors()
    return sql(s,'SELECT first_seen FROM errors WHERE error_key=?',(key,))[0][0]
def cpu(s,current=20,history=None,warning=85,critical=95):
    ns=dict(vars(typing),time=TIME,os=types.SimpleNamespace(cpu_count=lambda:4),health_persistence=s,psutil=types.SimpleNamespace(cpu_percent=lambda **kw:current,cpu_count=lambda:4))
    fn=extract(scripts/'health_monitor.py','_check_cpu_with_hysteresis','HealthMonitor',ns)
    if history is None:history=[{'value':20,'time':BASE-i*10} for i in range(1,11)]
    target=types.SimpleNamespace(state_history={'cpu_usage':list(history)},CPU_WARNING=85,CPU_CRITICAL=95,CPU_RECOVERY=75,CPU_WARNING_DURATION=300,CPU_CRITICAL_DURATION=300,CPU_RECOVERY_DURATION=120,_check_cpu_temperature=lambda:None)
    refresh=extract(scripts/'health_monitor.py','_refresh_thresholds','HealthMonitor',{})
    with patch.dict(sys.modules,{'health_thresholds':types.SimpleNamespace(get=lambda section,key:({'warning':warning,'critical':critical}.get(key) if section=='cpu' else None))}):refresh(target)
    return fn(target)
def poll(s,first,key='cpu_usage',category='cpu',reason='CPU high',details=None,first_done=True,foreign=False,restored=False):
    events=[]
    meta={'category':category,'reason':reason,'severity':'WARNING','first_seen':first,'details':details}
    c=types.SimpleNamespace(_hostname='node-a',_ENTITY_MAP={'cpu':('node',''),'pve_services':('node',''),'network':('node','')},_first_poll_done=first_done,_known_errors={key:meta},_notified_severity={key:'WARNING'},_last_notified={key:BASE-1},SAME_ERROR_COOLDOWN=86400,_get_cooldown_from_db=lambda *a:BASE-1,_queue=types.SimpleNamespace(put=events.append),_guest_storage_error_is_now_foreign=lambda *a:foreign,_save_known_errors_meta=lambda:None)
    ns=dict(vars(typing),time=TIME,json=json,re=__import__('re'),NotificationEvent=lambda *a,**kw:types.SimpleNamespace(event_type=a[0],severity=a[1],data=a[2],**kw),startup_grace=types.SimpleNamespace(should_suppress_category=lambda *a:False))
    c._guest_storage_error_is_now_foreign=extract(scripts/'notification_events.py','_guest_storage_error_is_now_foreign','PollingCollector',ns)
    fn=extract(scripts/'notification_events.py','_check_persistent_health','PollingCollector',ns)
    with patch.dict(sys.modules,{'health_persistence':types.SimpleNamespace(health_persistence=s),'flask_server':types.SimpleNamespace(get_proxmox_node_name=lambda:'node-a',get_cached_pvesh_cluster_resources_vm=lambda:[{'vmid':100,'type':'lxc','node':'node-b' if foreign else 'node-a'}]),'datetime':types.SimpleNamespace(**{**vars(datetime),'datetime':Clock})}):
        if restored:
            c._KNOWN_ERRORS_SETTING_KEY='pollingcollector_known_errors_v1'
            s.set_setting(c._KNOWN_ERRORS_SETTING_KEY,json.dumps(c._known_errors));c._known_errors={}
            extract(scripts/'notification_events.py','_load_known_errors_meta','PollingCollector',ns)(c)
            c._first_poll_done=bool(c._known_errors)
        fn(c)
    return [e.data for e in events],c
def service(store, rc=0, stdout='active\n', raised=False, services=('pvedaemon',), clustered=False):
    calls=[]
    def run(argv, **kw):
        calls.append((argv, kw))
        assert argv[:2] == ['systemctl', 'is-active']
        if raised: raise TimeoutError('inert timeout')
        return types.SimpleNamespace(returncode=rc, stdout=stdout)
    ns=dict(vars(typing),time=TIME,os=types.SimpleNamespace(path=types.SimpleNamespace(exists=lambda p:clustered)),subprocess=types.SimpleNamespace(run=run),health_persistence=store)
    result=extract(scripts/'health_monitor.py','_check_pve_services','HealthMonitor',ns)(types.SimpleNamespace(PVE_SERVICES=list(services)))
    return result,calls

@contextlib.contextmanager
def case():
    Clock.epoch=BASE
    with tempfile.TemporaryDirectory(prefix='recovery-review-db-',dir=os.environ.get('TMPDIR')) as d:yield make_store(d)
