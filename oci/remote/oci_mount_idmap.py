"""Per-directory mount UID/GID maps, preserved in the OCI deployment contract.

These are Proxmox mount-point maps (container ID -> underlying disk ID), not
changes to the container's global user namespace. The first supported profile
is an unprivileged standalone container with directory host binds.
"""
from __future__ import annotations

import argparse
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import subprocess

from oci_ui import translate

LIMIT = 4294967295
CONTAINER_IDS = 65536
_PVE_MAP = r'''
use JSON::PP; use PVE::LXC::Config; use PVE::LXC;
my $r=decode_json(do { local $/; <STDIN> });
my $mp=PVE::LXC::Config->parse_volume("mp0", "/tmp,mp=/data,idmap=".$r->{idmap});
die "idmap unsupported\n" unless ref($mp->{idmap}) eq "ARRAY";
my $base=[["u",0,100000,65536],["g",0,100000,65536]];
my $resolved=PVE::LXC::resolve_mountpoint_idmap($base,$mp);
PVE::LXC::validate_id_maps($resolved);
print encode_json($resolved);
'''


def normalize_idmap(value, unprivileged=True):
    if value is None or value == '':
        return None
    if not unprivileged:
        raise ValueError(translate('Mount ID mapping requires an unprivileged container'))
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError(translate('Invalid mount ID mapping'))
    rows=[]
    for item in value.split(';'):
        match=re.fullmatch(r'([ug]):([0-9]{1,10}):([0-9]{1,10}):([0-9]{1,10})',item)
        if not match:
            raise ValueError(translate('Invalid mount ID mapping'))
        kind=match[1]; start,disk,count=map(int,match.groups()[1:])
        if not count or start+count>CONTAINER_IDS or disk+count>LIMIT or disk == 0:
            raise ValueError(translate('Mount ID mapping ranges must stay within container IDs 0–65535 and must not map host root'))
        for k,a,b,n in rows:
            if k==kind and (max(a,start)<min(a+n,start+count) or max(b,disk)<min(b+n,disk+count)):
                raise ValueError(translate('Mount ID mapping ranges overlap'))
        rows.append((kind,start,disk,count))
    return ';'.join(f'{k}:{a}:{b}:{n}' for k,a,b,n in sorted(rows,key=lambda row:(row[0]=='g',row[1])))


@lru_cache(maxsize=1)
def supported():
    try:
        proc=subprocess.run(['perl','-e',_PVE_MAP],input=json.dumps({'idmap':'u:0:2000:1;g:0:2000:1'}),
                            text=True,capture_output=True,timeout=10)
        return proc.returncode==0
    except (OSError,subprocess.TimeoutExpired):
        return False


def ensure_supported():
    if not supported():
        raise ValueError(translate('This Proxmox host does not support per-mount ID mapping'))


@lru_cache(maxsize=128)
def _validate_native(value):
    ensure_supported()
    try:
        proc=subprocess.run(['perl','-e',_PVE_MAP],input=json.dumps({'idmap':value}),
                            text=True,capture_output=True,timeout=10)
    except (OSError,subprocess.TimeoutExpired):
        raise ValueError(translate('Proxmox could not validate the mount ID mapping')) from None
    if proc.returncode:
        raise ValueError(translate('The mount ID mapping conflicts with the container ID map'))


def mapped_host_ids(mount, uid, gid, unprivileged=True):
    value=normalize_idmap(mount.get('idmap'),unprivileged)
    if not value:
        return (uid+100000,gid+100000) if unprivileged else (uid,gid)
    rows=[(v[0],*map(int,v[1:])) for v in (item.split(':') for item in value.split(';'))]
    result=[]
    for kind,number in (('u',uid),('g',gid)):
        found=next((disk+number-start for k,start,disk,count in rows if k==kind and start<=number<start+count),None)
        if found is None:
            raise ValueError(translate('The mount ID mapping must cover the application UID and GID before creating its host directory'))
        result.append(found)
    return tuple(result)


def application_ids(deployment, template=None, config=None):
    """The installer profile/environment overrides the effective init identity."""
    import oci_runtime_settings as runtime
    uid,gid=runtime._config_ids(config)
    runtime_user=str((template or {}).get('proxmox',{}).get('installer_profile',{}).get('runtime',{}).get('user') or '')
    if re.fullmatch(r'[0-9]+:[0-9]+', runtime_user):
        uid,gid=map(int,runtime_user.split(':'))
    env={v['name']:v.get('value') for v in deployment.get('environment',[])}
    for kind,names in (('u',('PUID','USER_ID','UID')),('g',('PGID','GROUP_ID','GID'))):
        selected=[env[n] for n in names if env.get(n) not in (None,'')]
        if selected:
            text=str(selected[-1])
            if not re.fullmatch(r'[0-9]{1,10}',text) or int(text)>=CONTAINER_IDS:
                raise ValueError(translate('The application user or group is outside the supported range'))
            if kind=='u': uid=int(text)
            else: gid=int(text)
    owner=(template or {}).get('proxmox',{}).get('installer_profile',{}).get('volume_owner',{})
    resolved=(owner.get('uid',uid),owner.get('gid',gid))
    if any(isinstance(v,bool) or not re.fullmatch(r'[0-9]{1,10}',str(v)) or not 0<=int(v)<CONTAINER_IDS for v in resolved):
        raise ValueError(translate('The application user or group is outside the supported range'))
    return tuple(map(int,resolved))


def _filesystem(source):
    path=Path(source)
    while not path.exists() and path != path.parent:
        path=path.parent
    try:
        proc=subprocess.run(['findmnt','--noheadings','--output','FSTYPE','--target',str(path)],
                            text=True,capture_output=True,timeout=10)
        filesystem=proc.stdout.strip() if proc.returncode==0 else ''
    except (OSError,subprocess.TimeoutExpired):
        filesystem=''
    if filesystem not in ('ext4','xfs','btrfs','zfs'):
        raise ValueError(translate('The host directory filesystem does not support this mount ID mapping profile'))
    if filesystem=='zfs':
        try:
            version=Path('/sys/module/zfs/version').read_text().split('-',1)[0]
            major,minor=map(int,version.split('.')[:2])
            if (major,minor)<(2,2):
                raise ValueError
        except (OSError,ValueError):
            raise ValueError(translate('Mount ID mapping requires OpenZFS 2.2 or newer')) from None


def _check_nested_mounts(source):
    import oci_host_mounts as host_mounts
    resolved=str(Path(source).resolve()).rstrip('/')
    try:
        lines=host_mounts.MOUNTINFO.read_text().splitlines()
    except OSError:
        raise ValueError(translate('Proxmox could not validate the mount ID mapping')) from None
    for line in lines:
        fields=line.partition(' - ')[0].split()
        if len(fields)>4 and host_mounts._field(fields[4]).startswith(resolved+'/'):
            raise ValueError(translate('Mount ID mapping does not support nested host mounts'))


def _archive_config(deployment,template,archive):
    from oci_installation_state import image_from_archive
    image=image_from_archive(archive)
    declared=(template or {}).get('proxmox',{}).get('installer_profile',{}).get('runtime',{}).get('user')
    declared=str(declared if declared not in (None,'') else image['defaults'].get('User') or '')
    user,separator,group=declared.partition(':')
    known_u=not declared or user.isdigit() or user=='root'
    known_g=not declared or group.isdigit() or group=='root' or user in ('0','root') and not separator
    uid=int(user) if user.isdigit() else 0
    gid=int(group) if group.isdigit() else 0
    env={v['name']:v.get('value') for v in deployment.get('environment',[])}
    owner=(template or {}).get('proxmox',{}).get('installer_profile',{}).get('volume_owner',{})
    known_u=known_u or owner.get('uid') is not None or any(env.get(n) not in (None,'') for n in ('PUID','USER_ID','UID'))
    known_g=known_g or owner.get('gid') is not None or any(env.get(n) not in (None,'') for n in ('PGID','GROUP_ID','GID'))
    if not (known_u and known_g) and any(m.get('idmap') and m.get('create_if_missing') and not Path(m['source']).exists()
                                       for m in deployment.get('mounts',[])):
        raise ValueError(translate('The image application UID and GID must be known before creating an ID-mapped host directory'))
    return f'lxc.init.uid: {uid}\nlxc.init.gid: {gid}\n'.encode()


def _native_global_idmap(deployment,config=None):
    """This profile resolves per-mount maps against PVE's native user map."""
    sources=[deployment.get('custom_lxc',[])]
    if config is not None:
        text=config.decode() if isinstance(config,bytes) else str(config)
        sources.append(text.splitlines())
    expected={'u 0 100000 65536','g 0 100000 65536'}
    for lines in sources:
        maps=[' '.join(line.partition(':')[2].split()) for line in lines if line.startswith('lxc.idmap:')]
        if maps and (len(maps)!=2 or set(maps)!=expected):
            raise ValueError(translate('The native unprivileged idmap is required'))


def check_deployment(deployment, template=None, config=None, standalone=True, require_supported=False):
    mapped=[m for m in deployment.get('mounts',[]) if m.get('idmap') not in (None,'')]
    if not mapped:
        return
    _native_global_idmap(deployment,config)
    unprivileged=deployment.get('security',{}).get('unprivileged',True) is not False
    if (not standalone or any(deployment.get(k) for k in ('stack_managed','host_monitor','deployment_kind','replay_profile',
                                                       'rootfs_adaptation_replay_required','native_config'))):
        raise ValueError(translate('Mount ID mapping currently supports standalone OCI applications only'))
    for mount in mapped:
        value=normalize_idmap(mount['idmap'],unprivileged)
        if mount.get('type')!='host-bind' or any(value==p or value.startswith(p+'/')
                for value in (mount.get('source',''),mount.get('container_path',''))
                for p in ('/sys','/proc','/dev','/etc','/usr','/bin','/sbin','/lib','/lib64','/run','/var/run')):
            raise ValueError(translate('Mount ID mapping currently supports host directory mounts only'))
        import oci_host_mounts as host_mounts
        source=Path(host_mounts.valid_path(mount.get('source','')))
        host_mounts.validate_source(str(source),allow_missing=mount.get('create_if_missing') is True)
        if source.exists() and not source.is_dir():
            raise ValueError(translate('Mount ID mapping currently supports host directory mounts only'))
        if mount.get('grant_access'):
            raise ValueError(translate('Mount ID mapping cannot be combined with an ACL permission grant'))
        if not source.exists() and mount.get('create_if_missing'):
            mapped_host_ids(mount,*application_ids(deployment,template,config),unprivileged)
        if require_supported:
            _validate_native(value)
            _filesystem(str(source))
            _check_nested_mounts(str(source))


def same_mapping(actual,mount,unprivileged=True):
    return normalize_idmap(actual.get('idmap'),unprivileged)==normalize_idmap(mount.get('idmap'),unprivileged)


def create_host_directory(mount,deployment,template=None,config=None):
    """Only own a newly created leaf directory; keep all existing owners intact."""
    path=Path(mount['source'])
    if path.exists():
        if not path.is_dir():
            raise ValueError(translate('The host directory does not exist'))
        return False
    owners=mapped_host_ids(mount,*application_ids(deployment,template,config)) if mount.get('idmap') else None
    try:
        path.mkdir(parents=True,exist_ok=False,mode=0o775)
    except FileExistsError:
        if not path.is_dir():
            raise ValueError(translate('The host directory does not exist'))
        return False
    if mount.get('idmap'):
        os.chown(path,*owners)
        path.chmod(0o775)
    return True


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('operation',choices=('validate','owners'))
    parser.add_argument('--deployment',type=Path,required=True)
    parser.add_argument('--template',type=Path)
    parser.add_argument('--config',type=Path)
    parser.add_argument('--target')
    parser.add_argument('--archive',type=Path)
    args=parser.parse_args()
    plan=json.loads(args.deployment.read_text())
    template=json.loads(args.template.read_text()) if args.template else None
    config=args.config.read_bytes() if args.config else None
    if args.archive and any(m.get('idmap') for m in plan.get('mounts',[])):
        config=_archive_config(plan,template,args.archive)
    check_deployment(plan,template,config,require_supported=True)
    if args.operation=='owners':
        mount=next(m for m in plan['mounts'] if m['container_path']==args.target)
        print('\t'.join(map(str,mapped_host_ids(mount,*application_ids(plan,template,config)))))


if __name__=='__main__':
    main()
