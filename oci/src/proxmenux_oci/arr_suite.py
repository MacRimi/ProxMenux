"""Selectable core Arr suite, reusing the catalog's individual image contracts."""
import copy
import json
from pathlib import Path

from .i18n import translate
from .stack import DefaultsUI, StackError

PLAYERS = ('jellyfin', 'plex', 'emby')
MEDIA_APPS = {'sonarr','radarr','lidarr','qbittorrent','sabnzbd','bazarr','unpackerr',*PLAYERS}


class SuiteChildUI(DefaultsUI):
    """Reuse image hardware questions without repeating the stack storage wizard."""
    def __init__(self, ui, profile):
        self.ui = ui
        self.prompts = set()
        def visit(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in ('prompt','path_prompt','enable_prompt') and isinstance(item,str):
                        # The installer may send either the template text or its translation.
                        self.prompts.add(item)
                        self.prompts.add(translate(item))
                    visit(item)
            elif isinstance(value,list):
                for item in value: visit(item)
        visit(profile)

    def ask(self, text, default=None, required=True):
        return self.ui.ask(text,default,required) if text in self.prompts else super().ask(text,default,required)

    def choose(self, text, options, default=None):
        return self.ui.choose(text,options,default) if text in self.prompts else default

    def confirm(self, text, default=False):
        return self.ui.confirm(text,default) if text in self.prompts else default

    def password(self, text, required=True):
        return self.ui.password(text,required=required)


def build_suite(template, ui, mode='advanced'):
    from .installer import build_deployment, _hostname_default, DEFAULT_MODE
    choices = template['proxmox']['installer_profile']['applications']
    profile = template['proxmox']['installer_profile']
    selected = ui.checklist(translate('Arr suite: applications to install'), [(x, x.capitalize()) for x in choices],
                            profile.get('default_applications',['prowlarr','sonarr','radarr','qbittorrent']))
    if set(selected) - set(choices):
        raise StackError(translate('Invalid suite application'))
    player = ui.choose(translate('Media server'), [(x,x.capitalize()) for x in PLAYERS]+[('none',translate('None'))], 'jellyfin')
    if player not in (*PLAYERS,'none'):
        raise StackError(translate('Media server selection cancelled or invalid'))
    if player != 'none': selected = list(selected)+[player]
    if not selected:
        raise StackError(translate('Select at least one suite application'))
    if 'unpackerr' in selected and not set(selected) & {'sonarr','radarr','lidarr'}:
        raise StackError(translate('Unpackerr requires Sonarr, Radarr or Lidarr in this suite'))
    name = _hostname_default(ui.ask(translate('Stack name'), 'suite-arr'))
    base = ui.ask(translate('Base VMID (empty = next free block)'), '', required=False)
    from . import host
    from . import network as access
    from .installer import ask_bridge, ask_storage
    storage = ask_storage(ui, translate('Storage for rootfs and private configuration'), 'rootdir', 'local-lvm', mode)
    cache = ask_storage(ui, translate('Storage for the OCI image cache'), 'vztmpl', 'local', mode)
    bridge = ask_bridge(ui, translate('Access bridge'), 'vmbr0', mode)
    reachable = [app for app in selected if app != 'unpackerr']
    labels, gateway = access.ask_addresses(ui, bridge, [app.capitalize() for app in reachable])
    addresses = dict(zip(reachable, labels.values()))
    timezone = ui.ask(translate('Timezone'), host.timezone())
    onboot = ui.confirm(translate('Start each LXC with Proxmox (no coordinated startup)'), False)
    shared = ui.ask(translate('Shared host media directory'), '/mnt/oci-shared/media') if set(selected) & MEDIA_APPS else None
    if shared and (not shared.startswith('/') or shared == '/' or '..' in shared.split('/') or any(c in shared for c in ',\n\r')):
        raise StackError(translate('Invalid shared path'))
    ordered = list(selected)
    services = []
    credentials = None
    if 'qbittorrent' in selected:
        password = ui.password(translate('qBittorrent WebUI password (user: admin)'), required=True)
        if not password:
            raise StackError(translate('qBittorrent requires a non-empty password'))
        credentials = {'username':'admin','password':password}
    for app in ordered:
        path = Path(__file__).resolve().parents[2] / 'catalog/apps' / (app+'.json')
        child = json.loads(path.read_text())
        if not child['compatibility']['automatic_install_candidate']:
            raise StackError(f"{app}: {translate('individual template is blocked')}")
        child_ui = (DefaultsUI() if mode == DEFAULT_MODE else
                    SuiteChildUI(ui, child['proxmox'].get('installer_profile', {})))
        plan = build_deployment(copy.deepcopy(child), child_ui, mode)
        plan.update(hostname=_hostname_default(name+'-'+app), start_after_create=False, onboot=onboot, template_storage=cache)
        plan['rootfs']['storage'] = storage
        for env in plan['environment']:
            if env['name'] == 'TZ': env['value'] = timezone
            if env['name'] in ('PUID','PGID'): env['value'] = '1000'
        config_path = '/app/config' if app=='seerr' else '/config'
        config = next(copy.deepcopy(m) for m in plan['mounts'] if m['container_path']==config_path)
        config.update(type='managed-volume', source=storage, size_gb=max(config.get('size_gb') or 0,8), backup=True)
        plan['mounts'] = [config]
        if app in MEDIA_APPS:
            plan['mounts'].append({'type':'host-bind','source':shared,'container_path':'/data','size_gb':None,'backup':False,'read_only':False,'create_if_missing':True})
        endpoint = child['first_run']['endpoints'][0] if child['first_run']['endpoints'] else None
        health = {'type':'http','timeout_seconds':360,'endpoint':endpoint} if endpoint else {'type':'running','timeout_seconds':60}
        if app == 'qbittorrent':
            child['first_run']['credentials'] = []
        services.append({'name':app,'main':False,'kind':'application','offset':len(services),
                         'aliases':[app], 'frontend':app!='unpackerr', 'template':child,'deployment':plan,
                         'healthcheck':health, 'frontend_ipv4':addresses.get(app)})
        if app in ('seerr','unpackerr'):
            services[-1]['config_owner'] = 1000
        if app == 'unpackerr':
            services[-1]['deferred_setup'] = True
        if app == 'qbittorrent':
            services[-1]['setup_credentials'] = credentials
    if mode != DEFAULT_MODE:
        from .custom_mounts import ask_stack_custom_mounts
        ask_stack_custom_mounts(ui, services, storage)
        from .extra_devices import ask_stack_extra_devices
        ask_stack_extra_devices(ui, services)
    return {'deployment_kind':'generic-multi-lxc-stack','suite_arr':True,'lifecycle_mode':'independent','stack_name':name,
            'base_vmid':int(base) if base else None,'services':services,'shared_media':shared,'media_player':player,
            'completion_notes':[
                translate('Independent LXCs: no main container or hookscript. Each one keeps its own Start with Proxmox setting.'),
                f"{translate('Shared host content (not included in LXC backups):')} {shared} -> /data"
                if shared else translate('No shared media content.'),
                translate('Libraries: /data/media/movies, /data/media/series and /data/media/music. Select them in the media server.'),
                translate('Complete the media server and Seerr accounts, the Bazarr providers and the SABnzbd Usenet credentials when they are selected.'),
                translate('Seerr/Bazarr connections, the SABnzbd client and the Lidarr profiles, root folder and client are configured manually in this version.'),
                translate('Gluetun/VPN not yet available: this suite does not route downloads through a VPN.')
            ],
            'rootfs_storage':storage,'template_storage':cache,'onboot':onboot,'start_after_create':True,
            'network':{'frontend_bridge':bridge,'frontend_gateway':gateway,'private_allocation':'automatic','private_bridge':'vmbr10',
                       'private_subnet':'10.77.0.0/24','private_host_address':'10.77.0.1/24'}}
