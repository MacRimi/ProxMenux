#!/usr/bin/env python3
"""Host-side orchestration; only standard-library dependencies are needed on Proxmox."""
from __future__ import annotations

import base64
import copy
import configparser
import fcntl
import hashlib
import http.cookiejar
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.parse
import uuid
import xml.etree.ElementTree as ET

from allocate_private_network import allocate_network, existing_bridges, existing_networks
import oci_instances
from oci_ui import translate, msg_info, msg_ok, msg_warn, msg_error, msg_info2, stop_spinner, log

HERE = Path(__file__).resolve().parent
LOG_DIR = Path(os.environ.get('OCI_LOG_DIR', '/var/log/proxmenux/oci'))
LOG = os.environ.get('OCI_LOG') or None
RESULT_MARKER = b'PROXMENUX_RESULT='
ERROR_REPORTED = False


class ServiceFailed(RuntimeError):
    """The child installer already printed its own error and log tail."""


def access_address(address, gateway):
    """ip= and gw= options of an access interface: DHCP or a static IPv4."""
    if address == 'dhcp':
        return 'ip=dhcp'
    try:
        interface = ipaddress.IPv4Interface(address) if '/' in address else None
        router = ipaddress.IPv4Address(gateway) if gateway else None
    except ValueError:
        interface = None
    if interface is None or (router is not None and (router not in interface.network or router == interface.ip)):
        raise RuntimeError(f"{translate('Invalid access address:')} {address} {gateway or ''}".rstrip())
    return f'ip={interface}' + (f',gw={router}' if router else '')


def init_log(name):
    """Private run log shared with every child installer through OCI_LOG."""
    global LOG
    if not LOG:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        try:
            LOG_DIR.chmod(0o700)
        except OSError:
            pass
        safe = re.sub(r'[^A-Za-z0-9._-]', '_', name or 'stack')
        path = LOG_DIR / f"{safe}-{time.strftime('%Y%m%d-%H%M%S')}.log"
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600))
        path.chmod(0o600)
        LOG = str(path)
    os.environ['OCI_LOG'] = LOG


def log_tail(lines=12):
    if not LOG:
        return []
    try:
        content = Path(LOG).read_text(errors='replace').splitlines()
    except OSError:
        return []
    return content[-lines:]


def report_error(text, tail=True):
    """msg_error plus the end of the run log, like die() in the bash installers."""
    global ERROR_REPORTED
    ERROR_REPORTED = True
    msg_error(text)
    if not LOG:
        return
    if tail:
        for line in log_tail():
            sys.stderr.write('      '+line+'\n')
    sys.stderr.write(f"    {translate('Full log:')} {LOG}\n")
    sys.stderr.flush()


def persist_instances(deployment, services, primary_id=None):
    template = json.loads(Path(sys.argv[1]).read_text()) if primary_id is not None else {}
    with oci_instances.locked(oci_instances.ROOT):
        if primary_id is not None:
            oci_instances.save_assembly(oci_instances.ROOT, primary_id, template, deployment, services)
            oci_instances.resume_assembly(oci_instances.ROOT, primary_id)
        else:
            oci_instances.publish_stack(oci_instances.ROOT, None, template, deployment, services)


def run(*args, capture=True, timeout=180):
    argv = list(map(str,args))
    if capture:
        try:
            return subprocess.run(argv, check=True, text=True, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, timeout=timeout).stdout
        except subprocess.CalledProcessError as error:
            log(LOG, '$ '+' '.join(argv)+'\n'+(error.stdout or '')+(error.stderr or ''))
            raise
    # Command output belongs to the run log, never to the terminal.
    with open(LOG or os.devnull, 'a') as output:
        return subprocess.run(argv, check=True, text=True, stdout=output,
                              stderr=subprocess.STDOUT, timeout=timeout).stdout


def exists(vmid):
    return any(Path('/etc/pve/nodes').glob(f'*/lxc/{vmid}.conf')) or any(Path('/etc/pve/nodes').glob(f'*/qemu-server/{vmid}.conf'))


def retire_stale_contract(path, primary_id):
    if not path.exists():
        return
    if path.is_symlink():
        raise RuntimeError(translate('The previous stack contract is not safe; review it before reusing it'))
    try:
        contract = json.loads(path.read_text())
        if contract.get('schema') != 1 or not isinstance(contract.get('dependencies'),list):
            raise ValueError('unrecognized structure')
        ids = {primary_id}
        for dependency in contract['dependencies']:
            vmid = dependency['vmid']
            if type(vmid) is not int or vmid < 100:
                raise ValueError('invalid VMID')
            ids.add(vmid)
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise RuntimeError(translate('The previous stack contract is not valid; it is not archived automatically')) from error
    live = sorted(vmid for vmid in ids if exists(vmid))
    if live:
        raise RuntimeError(f"{translate('The previous stack contract still has containers or VMs:')} {', '.join(map(str,live))}")
    archive = path.with_name(f'proxmenux-retired-stack-{primary_id}-{uuid.uuid4().hex}.json')
    path.rename(archive)
    msg_info2(f"{translate('Orphan stack contract archived:')} CT {primary_id} → {archive}")
    log(LOG, 'The shared hookscript is kept.')


def write_json(path, value):
    path.write_text(json.dumps(value,indent=2)+'\n')
    path.chmod(0o600)


def create_service(service, directory):
    template = directory / 'template.json'
    deployment = directory / 'deployment.json'
    write_json(template, service['template'])
    child_plan = copy.deepcopy(service['deployment'])
    child_plan['mounts'] = []
    child_plan['stack_managed'] = True
    write_json(deployment, child_plan)
    # The child shares this run log; its steps are relayed as they are drawn
    # (spinner frames included) and its result line is kept (one stack result).
    environment = dict(os.environ, OCI_LOG=LOG or '',
                       OCI_SPINNER='1' if sys.stdout.isatty() or os.environ.get('OCI_SPINNER') == '1' else '0')
    process = subprocess.Popen(['bash', str(HERE/'install_oci.sh'),str(template),str(deployment),'0'],
                               stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env=environment)
    result = None
    try:
        result = relay_child_output(process.stdout)
        if process.wait() or result is None:
            raise ServiceFailed(f"{translate('Could not create the service:')} {service['name']}")
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=30)
    return result


def relay_child_output(stream):
    """Copy the child output to the terminal as it arrives; return its PROXMENUX_RESULT."""
    output = sys.stdout.buffer
    sys.stdout.flush()
    pending = b''
    line_start = True
    result = None

    def parse(line):
        return json.loads(base64.b64decode(line[len(RESULT_MARKER):].strip()))

    while True:
        chunk = os.read(stream.fileno(), 4096)
        if not chunk:
            break
        pending += chunk
        while pending:
            if line_start and pending.startswith(RESULT_MARKER):
                end = pending.find(b'\n')
                if end < 0:
                    break
                result = parse(pending[:end])
                pending = pending[end+1:]
                continue
            if line_start and RESULT_MARKER.startswith(pending):
                break
            cuts = [index for index in (pending.find(b'\n'), pending.find(b'\r')) if index >= 0]
            if cuts:
                cut = min(cuts)+1
                output.write(pending[:cut])
                pending = pending[cut:]
                line_start = True
            else:
                output.write(pending)
                pending = b''
                line_start = False
        output.flush()
    if pending:
        if line_start and pending.startswith(RESULT_MARKER):
            result = parse(pending)
        else:
            output.write(pending)
            output.flush()
    return result


def lan_access_urls(services, subnet, strict=True):
    urls = []
    for service in services:
        endpoint = service['healthcheck'].get('endpoint')
        if not endpoint or not (service['main'] or service.get('frontend')):
            continue
        try:
            addresses = run('lxc-info','-n',service['vmid'],'-iH').splitlines()
            candidates = []
            for value in addresses:
                try:
                    address = ipaddress.ip_address(value.strip())
                except ValueError:
                    continue
                if address.version==4 and address not in subnet and not (
                        address.is_loopback or address.is_link_local or address.is_unspecified or address.is_multicast):
                    candidates.append(str(address))
            if not candidates:
                raise RuntimeError(f"{translate('No LAN address was obtained for the service:')} {service['name']}")
            urls.append({'label':service['name'],
                         'url':f"{endpoint['scheme']}://{candidates[0]}:{endpoint['port']}{endpoint['path']}"})
        except Exception:
            if strict:
                raise
    return urls


def attach_mounts(service, temporary):
    """Populate new managed volumes from the image, preserving its ownership."""
    vmid = service['vmid']
    root = Path(f'/var/lib/lxc/{vmid}/rootfs')
    for index, mount in enumerate(service['deployment']['mounts']):
        target = root / mount['container_path'].lstrip('/')
        seed = temporary / f'seed-{vmid}-{index}'
        seed.mkdir()
        run('pct','mount',vmid)
        try:
            if not target.resolve().is_relative_to(root.resolve()) or target.is_symlink():
                raise RuntimeError(translate('Unsafe volume path'))
            if target.is_dir():
                stat = target.stat()
                owner = (stat.st_uid,stat.st_gid,stat.st_mode & 0o777)
                if mount['type']=='managed-volume':
                    run('cp','-a',str(target)+'/.',str(seed))
            else:
                owner = (100000,100000,0o755)
        finally:
            run('pct','unmount',vmid)
        if mount['type']=='managed-volume':
            value=f"{mount['source']}:{mount['size_gb']},mp={mount['container_path']},backup=1"
        else:
            source=Path(mount['source'])
            if not source.is_absolute() or ',' in str(source) or '\n' in str(source):
                raise RuntimeError(translate('Invalid shared path'))
            if not source.exists():
                source.mkdir(parents=True)
                os.chown(source,*owner[:2])
                source.chmod(owner[2])
            if not source.is_dir():
                raise RuntimeError(translate('The shared destination is not a directory'))
            value=f"{source},mp={mount['container_path']},backup=0"
        run('pct','set',vmid,f'--mp{index}',value)
        if mount['type']=='managed-volume':
            run('pct','mount',vmid)
            try:
                lost=target/'lost+found'
                if lost.is_dir() and not lost.is_symlink():
                    lost.rmdir()
                run('cp','-a',str(seed)+'/.',str(target))
                os.chown(target,*owner[:2])
                target.chmod(owner[2])
            finally:
                run('pct','unmount',vmid)

        if mount.get('read_only'):
            config = run('pct', 'config', vmid)
            current = next(line.split(': ', 1)[1] for line in config.splitlines()
                           if line.startswith(f'mp{index}: '))
            run('pct', 'set', vmid, f'--mp{index}', current + ',ro=1')


def wait_web(primary, url):
    deadline = time.monotonic()+primary['healthcheck']['timeout_seconds']
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while True:
        if run('pct','status',primary['vmid']).strip()!='status: running':
            raise RuntimeError(f"{translate('The container stopped:')} {primary['name']} (CT {primary['vmid']})")
        try:
            with opener.open(url,timeout=4) as response:
                if response.status<400:
                    return
        except Exception:
            pass
        if time.monotonic()>=deadline:
            raise RuntimeError(f"{translate('The application did not pass its HTTP check:')} {primary['name']}")
        time.sleep(3)


def qbittorrent_password_hash(password):
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac('sha512', password.encode(), salt, 100000, 64)
    return base64.b64encode(salt).decode()+':'+base64.b64encode(digest).decode()


def seed_qbittorrent(service):
    """Seed the image's official defaults in its new persistent config volume."""
    vmid = service['vmid']
    root = Path(f'/var/lib/lxc/{vmid}/rootfs')
    run('pct','mount',vmid)
    try:
        directory = root/'config/qBittorrent'
        defaults = root/'defaults/qBittorrent.conf'
        target = directory/'qBittorrent.conf'
        for path in (directory, target, defaults):
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise RuntimeError(translate('Unsafe qBittorrent configuration path'))
        if target.exists():
            raise RuntimeError(translate('qBittorrent already has a configuration; it is not overwritten'))
        config = configparser.ConfigParser(interpolation=None)
        config.optionxform = str
        config.read_string(defaults.read_text())
        if not config.has_section('Preferences'):
            raise RuntimeError(translate('Unrecognized qBittorrent configuration format'))
        config['Preferences'][r'WebUI\Username'] = service['setup_credentials']['username']
        config['Preferences'][r'WebUI\Password_PBKDF2'] = '"@ByteArray('+qbittorrent_password_hash(service['setup_credentials']['password'])+')"'
        directory.mkdir(exist_ok=True,mode=0o700)
        owner = 101000 if service['deployment']['security']['unprivileged'] else 1000
        os.chown(directory,owner,owner)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd,'w') as output:
            config.write(output,space_around_delimiters=False)
        os.chown(target,owner,owner)
    finally:
        run('pct','unmount',vmid)


def same_download_path(actual, expected):
    return isinstance(actual,str) and actual.startswith('/') and actual.rstrip('/')==expected.rstrip('/')


def configure_qbittorrent(service, selected):
    port = service['healthcheck']['endpoint']['port']
    base = f"http://{service['ip']}:{port}"
    cookies = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(cookies))

    def api(path, values=None, with_status=False):
        request = urllib.request.Request(base+'/api/v2/'+path,
            data=urllib.parse.urlencode(values).encode() if values is not None else None,
            headers={'Referer':base+'/'})
        with opener.open(request,timeout=30) as response:
            body = response.read()
            return (getattr(response,'status',200),body) if with_status else body

    status, body = api('auth/login',service['setup_credentials'],with_status=True)
    # 5.2 uses HTTP 204 and a port-scoped cookie; older releases return "Ok.".
    legacy = status==200 and body.strip()==b'Ok.'
    modern = status==204 and not body.strip()
    cookie_name = f'QBT_SID_{port}' if modern else 'SID'
    if not (legacy or modern) or not any(c.name==cookie_name and c.value for c in cookies):
        raise RuntimeError(translate('qBittorrent: invalid login response or missing session cookie'))
    try:
        probe = json.loads(api('app/preferences'))
        if not isinstance(probe,dict) or not isinstance(probe.get('save_path'),str):
            raise RuntimeError(translate('qBittorrent: authenticated access to the preferences could not be verified'))
        preferences = {'save_path':'/data/downloads/','temp_path':'/data/downloads/incomplete/', 'temp_path_enabled':True}
        api('app/setPreferences',{'json':json.dumps(preferences)})
        actual = json.loads(api('app/preferences'))
        if (not all(same_download_path(actual.get(k),preferences[k]) for k in ('save_path','temp_path'))
                or actual.get('temp_path_enabled') is not True):
            raise RuntimeError(translate('qBittorrent did not apply the download paths'))
        categories = json.loads(api('torrents/categories'))
        for app,category in [('sonarr','tv'),('radarr','movies')]:
            if app not in selected:
                continue
            path = '/data/downloads/'+category
            action = 'editCategory' if category in categories else 'createCategory'
            api('torrents/'+action,{'category':category,'savePath':path})
            if not same_download_path(json.loads(api('torrents/categories')).get(category,{}).get('savePath'),path):
                raise RuntimeError(f"{translate('qBittorrent did not apply the category:')} {category}")
    finally:
        api('auth/logout',{})


def configure_arr(services):
    """Use generated API keys and upstream schemas, without changing image files."""
    apps = {s['name']:s for s in services}
    keys = {}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for name, service in apps.items():
        if name == 'qbittorrent':
            msg_info(translate('Configuring qBittorrent...'))
            configure_qbittorrent(service,apps)
            msg_ok(translate('qBittorrent configured'))
            continue
        if name not in ('prowlarr','sonarr','radarr','lidarr'):
            continue
        config = run('pct','exec',service['vmid'],'--','cat','/config/config.xml')
        keys[name] = ET.fromstring(config).findtext('ApiKey')
        if not keys[name]:
            raise RuntimeError(f"{name}: {translate('the API key was not generated on the first start')}")

    def api(name, path, payload=None):
        service = apps[name]
        port = service['healthcheck']['endpoint']['port']
        request = urllib.request.Request(f"http://{service['ip']}:{port}{path}",
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={'X-Api-Key':keys[name],'Content-Type':'application/json'})
        with opener.open(request, timeout=30) as response:
            body = response.read()
            return json.loads(body) if body else None

    for name, folder in (('sonarr','series'),('radarr','movies')):
        if name not in apps:
            continue
        text = arr_texts(name)
        msg_info(text['root_info'])
        api(name,'/api/v3/system/status')
        root = '/data/media/'+folder
        if not any(x.get('path') == root for x in api(name,'/api/v3/rootfolder')):
            api(name,'/api/v3/rootfolder',{'path':root})
        msg_ok(f"{text['root_ok']}: {root}")
        if 'qbittorrent' in apps:
            msg_info(text['client_info'])
            qbit = apps['qbittorrent']
            schema = next((x for x in api(name,'/api/v3/downloadclient/schema')
                           if x.get('implementation')=='QBittorrent'),None)
            if schema is None:
                raise RuntimeError(f"{name}: {translate('the qBittorrent schema is not available')}")
            schema.pop('id',None)
            schema.update(name='qBittorrent',enable=True,priority=1)
            category_key = 'tvCategory' if name=='sonarr' else 'movieCategory'
            values = dict(qbit['setup_credentials'],host=qbit['ip'],port=qbit['healthcheck']['endpoint']['port'],
                          useSsl=False,urlBase='',apiKey='')
            values[category_key] = 'tv' if name=='sonarr' else 'movies'
            if not {'host','port','username','password',category_key}.issubset({f['name'] for f in schema['fields']}):
                raise RuntimeError(f"{name}: {translate('incompatible qBittorrent schema')}")
            for field in schema['fields']:
                if field['name'] in values:
                    field['value'] = values[field['name']]
            api(name,'/api/v3/downloadclient/test',schema)
            api(name,'/api/v3/downloadclient',schema)
            msg_ok(text['client_ok'])
        if 'prowlarr' not in apps:
            continue
        msg_info(text['prowlarr_info'])
        if any(x.get('name') == name for x in api('prowlarr','/api/v1/applications')):
            msg_ok(text['prowlarr_ok'])
            continue
        schema = next((x for x in api('prowlarr','/api/v1/applications/schema')
                       if x.get('implementation','').lower()==name),None)
        if schema is None:
            raise RuntimeError(f"{translate('Prowlarr does not offer the application schema:')} {name}")
        schema.pop('id',None)
        schema.update(name=name,syncLevel='fullSync')
        values = {'apiKey':keys[name],
                  'baseUrl':f"http://{apps[name]['ip']}:{apps[name]['healthcheck']['endpoint']['port']}",
                  'prowlarrUrl':f"http://{apps['prowlarr']['ip']}:{apps['prowlarr']['healthcheck']['endpoint']['port']}"}
        for field in schema['fields']:
            if field['name'] in values:
                field['value'] = values[field['name']]
        api('prowlarr','/api/v1/applications',schema)
        msg_ok(text['prowlarr_ok'])
    if 'qbittorrent' not in apps:
        msg_info2(translate('The download client still needs to be configured.'))
    msg_info2(translate('Indexers and quality profiles still need to be configured.'))
    return keys


def arr_texts(name):
    """Visible steps of the Sonarr/Radarr wiring, one literal per application."""
    if name == 'sonarr':
        return {'root_info': translate('Configuring the Sonarr root folder...'),
                'root_ok': translate('Sonarr root folder configured'),
                'client_info': translate('Connecting Sonarr to qBittorrent...'),
                'client_ok': translate('Sonarr connected to qBittorrent'),
                'prowlarr_info': translate('Adding Sonarr to Prowlarr...'),
                'prowlarr_ok': translate('Sonarr added to Prowlarr')}
    return {'root_info': translate('Configuring the Radarr root folder...'),
            'root_ok': translate('Radarr root folder configured'),
            'client_info': translate('Connecting Radarr to qBittorrent...'),
            'client_ok': translate('Radarr connected to qBittorrent'),
            'prowlarr_info': translate('Adding Radarr to Prowlarr...'),
            'prowlarr_ok': translate('Radarr added to Prowlarr')}


def prepare_suite_config(service):
    """Prepare only newly allocated configuration volumes, never image binaries."""
    if service['name'] not in ('sabnzbd','seerr','unpackerr'):
        return
    vmid = service['vmid']
    root = Path(f'/var/lib/lxc/{vmid}/rootfs')
    path = root/('app/config' if service['name']=='seerr' else 'config')
    run('pct','mount',vmid)
    try:
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise RuntimeError(translate('Unsafe private configuration path'))
        if service.get('config_owner') is not None:
            owner = service['config_owner'] + (100000 if service['deployment']['security']['unprivileged'] else 0)
            os.chown(path,owner,owner)
        if service['name']=='sabnzbd':
            target = path/'sabnzbd.ini'
            fd = os.open(target,os.O_WRONLY | os.O_CREAT | os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as output:
                output.write('[misc]\ndownload_dir = /data/downloads/usenet-incomplete\ncomplete_dir = /data/downloads/usenet\n')
            os.chown(target,101000,101000)
    finally:
        run('pct','unmount',vmid)


def configure_unpackerr(services, keys):
    worker = next((s for s in services if s['name']=='unpackerr'),None)
    if worker is None:
        return
    msg_info(translate('Configuring Unpackerr...'))
    variables = {}
    for service in services:
        name = service['name']
        if name not in ('sonarr','radarr','lidarr'):
            continue
        prefix = 'UN_'+name.upper()+'_0_'
        variables[prefix+'URL'] = f"http://{service['ip']}:{service['healthcheck']['endpoint']['port']}"
        variables[prefix+'API_KEY'] = keys[name]
        variables[prefix+'PATHS_0'] = '/data/downloads'
        variables[prefix+'DELETE_ORIG'] = 'false'
    config = Path(f"/etc/pve/lxc/{worker['vmid']}.conf")
    content = config.read_text()
    for key,value in variables.items():
        if '\n' in value or '\r' in value:
            raise RuntimeError(translate('Invalid Unpackerr variable'))
        content = re.sub(r'^lxc\.environment\.runtime: '+re.escape(key)+r'=.*\n','',content,flags=re.M)
        content += 'lxc.environment.runtime: '+key+'='+value+'\n'
    config.write_text(content)
    run('pct','start',worker['vmid'],capture=False)
    for _ in range(3):
        time.sleep(1)
        if run('pct','status',worker['vmid']).strip()!='status: running':
            raise RuntimeError(translate('Unpackerr stopped during its first start'))
    msg_ok(translate('Unpackerr configured'))


def finish_independent_suite(services, subnet):
    log(LOG, 'First start to configure the applications; each container is independent.')
    for service in services:
        if service.get('deferred_setup'):
            continue
        msg_info(f"{translate('Starting the service:')} {service['name']}")
        run('pct','start',service['vmid'],capture=False,timeout=600)
        if service['healthcheck']['type']=='http':
            wait_web(service,service['healthcheck']['url'])
        msg_ok(f"{translate('Service ready:')} {service['name']}")
    keys = configure_arr(services)
    configure_unpackerr(services,keys)
    result = {'suite_arr':True,'lifecycle_mode':'independent',
              'stack_vmids':{s['name']:s['vmid'] for s in services},
              'urls':lan_access_urls(services,subnet),'credentials':[]}
    for service in services:
        if service['name']=='qbittorrent':
            result['credentials'].append(dict(service['setup_credentials'],label='qBittorrent',change_required=False))
    return result


def main():
    deployment = json.loads(Path(sys.argv[2]).read_text())
    if deployment.get('deployment_kind') != 'generic-multi-lxc-stack':
        raise RuntimeError(translate('Invalid stack contract'))
    if len(sys.argv)>3 and sys.argv[3]=='1':
        msg_info2(f"{translate('Containers:')} {len(deployment['services'])}")
        msg_info2(translate('Startup: independent, without hookscript') if deployment.get('suite_arr')
                  else translate('Startup: coordinated by the stack startup hook'))
        msg_ok(translate('Dry run completed; no changes were made.'))
        return
    if os.geteuid()!=0:
        raise RuntimeError(translate('The installer must run as root on Proxmox VE'))
    init_log(deployment.get('stack_name') or 'stack')
    services = copy.deepcopy(deployment['services'])
    independent = bool(deployment.get('suite_arr'))
    primary = None if independent else next(s for s in services if s['main'])
    created = []
    bridge_created = False
    lifecycle = None
    node = socket.gethostname()
    # Serialize this installer's allocation through creation, and let pct enforce ownership.
    msg_info(translate('Reserving a private network...'))
    with open('/run/lock/proxmenux-private-network.lock','w') as lock, tempfile.TemporaryDirectory(prefix='proxmenux-stack-') as tmp:
        fcntl.flock(lock,fcntl.LOCK_EX)
        base = deployment.get('base_vmid') or int(run('pvesh','get','/cluster/nextid').strip())
        while any(exists(base+s['offset']) for s in services):
            if deployment.get('base_vmid'):
                raise RuntimeError(translate('The requested VMID block is already in use'))
            base += 1
        selection = allocate_network(deployment,existing_bridges(),existing_networks())
        if selection is None:
            raise RuntimeError(translate('The private network must be assigned automatically'))
        bridge, subnet = selection
        deployment['network'].update(private_bridge=bridge, private_subnet=str(subnet),
                                     private_host_address=str(subnet.network_address+1)+'/24')
        primary_id = base
        aliases = []
        for s in services:
            s['vmid'] = base+s['offset']
            s['ip'] = str(subnet.network_address+30+s['offset'])
            for alias in s['aliases']:
                if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',alias):
                    raise RuntimeError(translate('Invalid service alias'))
                aliases.append({'hostname':alias,'address':s['ip']})
        if not independent:
            lifecycle = Path(f'/etc/pve/priv/proxmenux-stack-{primary_id}.json')
            retire_stale_contract(lifecycle,primary_id)
        try:
            log(LOG, f"Stack {deployment['stack_name']}: CT {base}-{base+len(services)-1}; network {subnet} on {bridge}")
            run('pvesh','create',f'/nodes/{node}/network','--iface',bridge,'--type','bridge','--autostart','1','--cidr',str(subnet.network_address+1)+'/24')
            bridge_created = True
            run('ip','link','add','name',bridge,'type','bridge')
            run('ip','address','add',str(subnet.network_address+1)+'/24','dev',bridge)
            run('ip','link','set',bridge,'up')
            msg_ok(f"{translate('Private network:')} {bridge} ({subnet})")
            if deployment.get('suite_arr') and deployment.get('shared_media'):
                shared = Path(deployment['shared_media'])
                for folder in [shared, shared/'downloads', shared/'downloads/incomplete', shared/'downloads/tv',
                               shared/'downloads/movies',shared/'downloads/music',shared/'downloads/usenet',shared/'downloads/usenet-incomplete',
                               shared/'media', shared/'media/series', shared/'media/movies',shared/'media/music']:
                    if not folder.exists():
                        folder.mkdir(parents=True)
                        os.chown(folder,101000,101000)
                        folder.chmod(0o775)
            results = {}
            for order,s in enumerate(services,1):
                plan = s['deployment']
                s['public_environment'] = {e['name']:e['value'] for e in plan['environment'] if '@STACK_LAN_IP@' in e['value']}
                for e in plan['environment']:
                    e['value'] = e['value'].replace('@STACK_LAN_IP@',s['ip'])
                plan['vmid'] = s['vmid']
                plan['extra_hosts'] = aliases
                plan['network'].update(bridge=bridge,ipv4=s['ip']+'/24',gateway=None)
                if exists(s['vmid']):
                    raise RuntimeError(f"{translate('The VMID was taken during the installation:')} {s['vmid']}")
                msg_info2(f"{translate('Service:')} {s['name']}")
                with tempfile.TemporaryDirectory(dir=tmp) as service_tmp:
                    results[s['name']] = create_service(s,Path(service_tmp))
                created.append(s['vmid'])
                if s['deployment']['mounts']:
                    msg_info(translate('Attaching the volumes...'))
                attach_mounts(s,Path(tmp))
                if s['deployment']['mounts']:
                    msg_ok(translate('Volumes attached'))
                if deployment.get('suite_arr'):
                    prepare_suite_config(s)
                if deployment.get('suite_arr') and s['name']=='qbittorrent':
                    seed_qbittorrent(s)
                if not independent:
                    run('pct','set',s['vmid'],'--startup',f'order={order*10},up=5,down=30')
                if s['main'] or s.get('frontend'):
                    address = access_address(s.get('frontend_ipv4') or 'dhcp', deployment['network'].get('frontend_gateway'))
                    run('pct','set',s['vmid'],'--net1',f"name=eth1,bridge={deployment['network']['frontend_bridge']},{address},host-managed=1,firewall=1,type=veth")
                if s['healthcheck']['type']=='http':
                    endpoint = s['healthcheck']['endpoint']
                    s['healthcheck']['url'] = f"{endpoint['scheme']}://{s['ip']}:{endpoint['port']}{endpoint['path']}"
            if independent:
                fcntl.flock(lock,fcntl.LOCK_UN)
                result = finish_independent_suite(services,subnet)
                persist_instances(deployment, services)
                result.update(completion_notes=list(deployment.get('completion_notes',[])), log=LOG)
                print('PROXMENUX_RESULT='+base64.b64encode(json.dumps(result).encode()).decode(),flush=True)
                return
            hook_spec = Path(tmp)/'lifecycle.json'
            write_json(hook_spec,{'schema':1,'stack':deployment['stack_name'],'dependencies':[
                {'vmid':s['vmid'],'label':s['name'],'healthcheck':s['healthcheck']} for s in services if not s['main'] and not s.get('deferred_setup')]})
            if len(services) > 1:
                msg_info(translate('Installing the stack startup hook...'))
                run('bash',HERE/'stack_dependency_hook.sh','--install',primary_id,hook_spec,capture=False)
                msg_ok(translate('Stack startup hook installed'))
            fcntl.flock(lock,fcntl.LOCK_UN)
            msg_info(translate('Starting the main container and its dependencies...') if len(services) > 1
                     else translate('Starting the container...'))
            run('pct','start',primary_id,capture=False,timeout=600)
            msg_ok(f"{translate('Container started')}: CT {primary_id} ({primary['name']})")
            endpoint = primary['healthcheck']['endpoint']
            url = f"{endpoint['scheme']}://{primary['ip']}:{endpoint['port']}{endpoint['path']}"
            msg_info(translate('Waiting for the application to respond...'))
            wait_web(primary,url)
            addresses=run('lxc-info','-n',primary_id,'-iH').splitlines()
            lan = next((a for a in addresses if re.fullmatch(r'\d+\.\d+\.\d+\.\d+',a) and ipaddress.ip_address(a) not in subnet),None)
            if not lan:
                raise RuntimeError(translate('No LAN address was obtained'))
            public_url = f"{endpoint['scheme']}://{lan}:{endpoint['port']}{endpoint['path']}"
            msg_ok(f"{translate('Application responding:')} {public_url}")
            if primary['public_environment']:
                msg_info(translate('Applying the LAN address to the application URLs...'))
                run('pct','shutdown',primary_id,'--timeout','180',timeout=200)
                config=Path(f'/etc/pve/lxc/{primary_id}.conf')
                text=config.read_text()
                for key,value in primary['public_environment'].items():
                    if '\n' in value or '\r' in value:
                        raise RuntimeError(translate('Multi-line variables are not supported'))
                    text=re.sub(r'^lxc\.environment\.runtime: '+re.escape(key)+r'=.*\n','',text,flags=re.M)
                    text+='lxc.environment.runtime: '+key+'='+value.replace('@STACK_LAN_IP@',lan)+'\n'
                config.write_text(text)
                run('pct','start',primary_id,capture=False,timeout=600)
                wait_web(primary,url)
                msg_ok(translate('LAN address applied to the application URLs'))
            result=results[primary['name']]
            persist_instances(deployment, services, primary_id)
            # The credentials of the main service come from its own installation.
            result.update(vmid=primary_id,ip=lan,stack_vmids={s['name']:s['vmid'] for s in services},
                          urls=[{'label':'Web UI','url':public_url}],
                          credentials=result.get('credentials') or [])
            result.update(completion_notes=[note.replace('{main_vmid}',str(primary_id))
                                            for note in deployment.get('completion_notes', [])], log=LOG)
            print('PROXMENUX_RESULT='+base64.b64encode(json.dumps(result).encode()).decode(),flush=True)
        except BaseException as error:
            # Keep volumes and configs for diagnosis; never delete a database on a late startup failure.
            stop_spinner()
            if isinstance(error, ServiceFailed):
                report_error(str(error), tail=False)
            elif isinstance(error, SystemExit):
                if isinstance(error.code, str):
                    report_error(error.code)
            else:
                report_error(str(error) or type(error).__name__)
            if created:
                msg_warn(f"{translate('Installation incomplete. These containers and their data are kept:')} "
                         f"{', '.join('CT '+str(vmid) for vmid in created)}")
            accesses = lan_access_urls([s for s in services if s.get('vmid') in created],subnet,strict=False)
            if accesses:
                msg_warn(translate('LAN access to the kept containers (stack configuration incomplete):'))
                for access in accesses:
                    msg_info2(access['label']+': '+access['url'])
            if not created and bridge_created:
                with open(LOG or os.devnull, 'a') as output:
                    subprocess.run(['ip','link','delete',bridge,'type','bridge'],check=False,stdout=output,stderr=output)
                    subprocess.run(['pvesh','delete',f'/nodes/{node}/network/{bridge}'],check=False,stdout=output,stderr=output)
            raise


if __name__=='__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        if not ERROR_REPORTED:
            report_error(str(error) or type(error).__name__)
        sys.exit(1)
    except SystemExit as error:
        if isinstance(error.code, str):
            if not ERROR_REPORTED:
                report_error(error.code)
            sys.exit(1)
        raise
