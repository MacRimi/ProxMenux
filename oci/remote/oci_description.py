#!/usr/bin/env python3
"""Render the Proxmox Notes for one ProxMenux OCI container."""
from __future__ import annotations

import argparse
import html
import ipaddress
import json
from pathlib import Path
from urllib.parse import urlparse

DOCS = 'https://macrimi.github.io/ProxMenux/docs/oci-manager'
CODE = 'https://github.com/MacRimi/ProxMenux/tree/main/oci'
LOGO = 'https://raw.githubusercontent.com/MacRimi/ProxMenux/main/images/logo_desc.png'


def safe_url(value):
    if not isinstance(value, str):
        return ''
    parsed = urlparse(value.strip())
    return value.strip() if parsed.scheme in ('http', 'https') and parsed.netloc else ''


def link(label, url):
    url = safe_url(url)
    if not url:
        return ''
    return (f'<a href="{html.escape(url, quote=True)}" target="_blank" '
            f'rel="noopener noreferrer">{html.escape(label)}</a>')


def image_page(reference):
    name = reference.split('@', 1)[0]
    if ':' in name.rsplit('/', 1)[-1]:
        name = name.rsplit(':', 1)[0]
    if name.startswith('lscr.io/linuxserver/'):
        return 'https://docs.linuxserver.io/images/docker-' + name.rsplit('/', 1)[-1] + '/'
    if name.startswith('ghcr.io/'):
        parts = name.split('/')
        if len(parts) >= 3:
            return f'https://github.com/{parts[1]}/' + '/'.join(parts[2:])
    if name.startswith('docker.io/'):
        name = name[len('docker.io/'):]
    if '/' not in name and name and '.' not in name:
        return 'https://hub.docker.com/_/' + name
    if '/' in name and '.' not in name.split('/', 1)[0]:
        return 'https://hub.docker.com/r/' + name
    return ''


def render(template, digest, instance_id, ip=''):
    ui = template.get('catalog_ui') or {}
    contract = template.get('container_contract') or {}
    image = contract.get('image') or {}
    title = ui.get('title') or {}
    if isinstance(title, dict):
        title = title.get('en_US') or next(iter(title.values()), '')
    title = str(title or contract.get('service_name') or template.get('id') or 'OCI')
    reference = str(image.get('reference') or '')
    source = template.get('source') or {}
    image_url = (source.get('image_repository_url') or image_page(reference)
                 or ui.get('repository') or source.get('repository'))
    resources = [('Image', image_url), ('App', ui.get('website')),
                 ('App docs', ui.get('documentation'))]
    repository = ui.get('repository') or source.get('repository')
    if safe_url(repository) and repository != image_url:
        resources.append(('Repository', repository))
    resources = [link(label, url) for label, url in resources]
    resources = [item for item in resources if item]
    try:
        address = str(ipaddress.ip_address(ip)) if ip else ''
    except ValueError:
        address = ''
    endpoints = (template.get('first_run') or {}).get('endpoints') or []
    if not endpoints and ui.get('launch'):
        endpoints = [dict(ui['launch'], label='Web UI')]
    if template.get('id') == 'image-adguard-home':
        endpoints = [{'label': 'Setup (first run)', 'scheme': 'http', 'port': 3000, 'path': '/'},
                     {'label': 'Web UI (after setup)', 'scheme': 'http', 'port': 80, 'path': '/'}]
    access = []
    if address:
        for endpoint in endpoints:
            scheme = endpoint.get('scheme')
            port = endpoint.get('port')
            path = endpoint.get('path') or '/'
            if scheme not in ('http', 'https') or not isinstance(port, int) or not 1 <= port <= 65535:
                continue
            if not isinstance(path, str) or not path.startswith('/'):
                path = '/'
            url = f'{scheme}://{address}:{port}{path}'
            item = f'{link(str(endpoint.get("label") or "Web UI"), url)}: {link(url, url)}'
            if item:
                access.append(item)
    badges = (
        ('Docs', DOCS, 'https://img.shields.io/badge/%F0%9F%93%9A_Docs-blue'),
        ('Code', CODE, 'https://img.shields.io/badge/%F0%9F%92%BB_Code-green'),
        ('Ko-fi', 'https://ko-fi.com/macrimi', 'https://img.shields.io/badge/%E2%98%95_Ko--fi-red'),
    )
    badge_links = ' '.join(
        f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">'
        f'<img src="{badge}" alt="{label}"></a>'
        for label, url, badge in badges
    )
    return f'''<div align="center">
<table style="width: 100%; border-collapse: collapse;"><tr>
<td style="width: 100px; vertical-align: middle;"><img src="{LOGO}" alt="ProxMenux Logo" style="height: 100px;"></td>
<td style="vertical-align: middle;"><h1 style="margin: 0;">{html.escape(title)} OCI</h1><p style="margin: 0;">Created with ProxMenux</p></td>
</tr></table>
<p>{badge_links}</p>
<p>Image: <code>{html.escape(reference)}</code> {' &middot; '.join(resources)}</p>
{''.join(f'<p>{item}</p>' for item in access)}
</div>
<!-- proxmenux-instance={html.escape(instance_id, quote=True)} -->'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--template', required=True, type=Path)
    parser.add_argument('--digest', default='')
    parser.add_argument('--instance', required=True)
    parser.add_argument('--ip', default='')
    args = parser.parse_args()
    print(render(json.loads(args.template.read_text()), args.digest, args.instance, args.ip))


if __name__ == '__main__':
    main()
