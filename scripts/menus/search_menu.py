#!/usr/bin/env python3
# ==========================================================
# ProxMenux - Menu search
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# ==========================================================
# Description:
# Finds an option by name or by related words across the ProxMenux menu,
# the OCI catalog and the Helper-Scripts, and opens it where it lives.
# ==========================================================
"""Search across the ProxMenux menu, the OCI catalog and the Helper-Scripts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import unicodedata
import urllib.request

BASE = Path('/usr/local/share/proxmenux')
SCRIPTS = BASE / 'scripts'
INDEX = Path(__file__).resolve().with_name('search_index.json')
OCI_INDEX = BASE / 'oci/engine/catalog/index.json'
HELPERS_URL = 'https://raw.githubusercontent.com/MacRimi/ProxMenux/refs/heads/main/json/helpers_cache.json'
HELPERS_CACHE = BASE / 'helpers_cache.json'
HELPERS_MAX_AGE = 24 * 3600
# Results come in this order: the menu itself, then the two catalogs.
SOURCES = ('ProxMenux', 'OCI Manager', 'Community Scripts')
# Words an OCI application is also found by, when its name does not say them.
OCI_KEYWORDS = {'sharecovex': 'samba smb cifs nfs share compartir archivos time machine'}

_translations = None
# The Monitor asks in the language of its own interface.
_language = None
# The page of the documentation that explains each section of the
# customizable post-installation script.
POST_INSTALL_DOCS = {
    'Basic Settings': 'post-install/basic-settings', 'System': 'post-install/system',
    'Virtualization': 'post-install/virtualization', 'Network': 'post-install/network',
    'Storage': 'post-install/storage', 'Security': 'post-install/security',
    'Customization': 'post-install/customization', 'Monitoring': 'post-install/monitoring',
    'Performance': 'post-install/performance', 'Optional': 'post-install/optional',
}
# The section of those pages that explains each setting.
POST_INSTALL_SECTIONS = {
    'APTUPGRADE': 'post-install/basic-settings#upgrade', 'TIMESYNC': 'post-install/basic-settings#time',
    'NOAPTLANG': 'post-install/basic-settings#languages', 'UTILS': 'post-install/basic-settings#utilities',
    'JOURNALD': 'post-install/system#journald', 'LOGROTATE': 'post-install/system#logrotate',
    'LIMITS': 'post-install/system#limits', 'MEMORYFIXES': 'post-install/system#memory',
    'KEXEC': 'post-install/system#kexec', 'KERNELPANIC': 'post-install/system#panic',
    'GUESTAGENT': 'post-install/virtualization#guestAgent', 'VFIO_IOMMU': 'post-install/virtualization#vfio',
    'APTIPV4': 'post-install/network#ipv4', 'NET': 'post-install/network#sysctl',
    'OPENVSWITCH': 'post-install/network#ovs', 'TCPFASTOPEN': 'post-install/network#bbr',
    'PERSISNET': 'post-install/network#names',
    'ZFSARC': 'post-install/storage#arc', 'ZFSAUTOSNAPSHOT': 'post-install/storage#autoSnap',
    'ZFSAUTOTRIM': 'post-install/storage#autotrim', 'VZDUMP': 'post-install/storage#vzdump',
    'DISABLERPC': 'post-install/security#rpcbind',
    'BASHRC': 'post-install/customization#bashrc', 'MOTD': 'post-install/customization#motd',
    'NOSUBBANNER': 'post-install/customization#banner',
    'OVHRTM': 'post-install/monitoring#ovh', 'PIGZ': 'post-install/performance#pigz',
    'ZRAM_SWAP': 'post-install/optional#zram', 'AMDFIXES': 'post-install/optional#amd',
    'FASTFETCH': 'post-install/optional#fastfetch', 'PVEAM': 'post-install/optional#pveam',
    'CEPH': 'post-install/optional#ceph', 'ENABLE_HA': 'post-install/optional#ha',
    'FIGURINE': 'post-install/optional#figurine', 'LOG2RAM': 'post-install/optional#log2ram',
}
# The automated script names a few settings after a variant of its own.
AUTO_POST_INSTALL_ALIASES = {'install_log2ram_auto': 'LOG2RAM'}


def translate(text):
    """The text in the language of the menu; the text itself when it has none."""
    global _translations
    if _translations is None:
        _translations = {}
        try:
            language = _language or json.loads((BASE / 'config.json').read_text()).get('language', 'en')
            if isinstance(language, str) and re.fullmatch(r'[a-z]{2}', language) and language != 'en':
                loaded = json.loads((BASE / 'lang' / f'{language}.json').read_text(encoding='utf-8'))
                if isinstance(loaded, dict):
                    _translations = loaded
        except (OSError, ValueError):
            pass
    value = _translations.get(text)
    return value if isinstance(value, str) and value else text


def option_key(option_id):
    """A short key for an option, safe in a URL and in the Monitor's terminal."""
    return hashlib.sha1(option_id.encode('utf-8')).hexdigest()[:16]


def tidy(text):
    """A menu label on one line: the menus pad theirs to line them up."""
    return re.sub(r'\s+', ' ', text).strip()


def fold(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value.casefold()) if not unicodedata.combining(c))


def returns_to_a_menu(script):
    """Whether a script ends by opening a menu itself, as the sub-menus do."""
    try:
        return bool(re.search(r'exec bash "\$(LOCAL_SCRIPTS|MENU_REPO)/', script.read_text(errors='ignore')))
    except OSError:
        return False


# What the Monitor's Catalog tab shows of an option: a VM it creates is an
# application, with its logo and category.
CATALOG_FIELDS = ('name', 'group', 'type', 'icon', 'category', 'via', 'resources', 'links', 'screenshots')
# Scripts that are not in the ProxMenux repository and that the menus run,
# whole or in one of their steps: who maintains each and where its scripts
# are downloaded from. An option of the index names the one it is
# ("third_party") or the ones it uses ("uses").
THIRD_PARTY = {
    'community-scripts': dict(name='Community Scripts', url='https://community-scripts.org',
                              scripts=('https://raw.githubusercontent.com/community-scripts/ProxmoxVE/',)),
    'osx-proxmox': dict(name='OSX-PROXMOX', url='https://osx-proxmox.com', scripts=('https://install.osx-proxmox.com',)),
    'proxmox-toolbox': dict(name='Tontonjo', url='https://github.com/Tontonjo/proxmox_toolbox',
                            scripts=('https://raw.githubusercontent.com/Tontonjo/proxmox_toolbox/',)),
    'proxsave': dict(name='tis24dev', url='https://github.com/tis24dev/proxsave',
                     scripts=('https://raw.githubusercontent.com/tis24dev/proxsave/',)),
    'nvidia-patch': dict(name='keylase/nvidia-patch', url='https://github.com/keylase/nvidia-patch',
                         scripts=('https://raw.githubusercontent.com/keylase/nvidia-patch/',)),
    'ovh-rtm': dict(name='OVHcloud', url='https://www.ovhcloud.com',
                    scripts=('https://last-public-ovh-infra-yak.snap.mirrors.ovh.net/',)),
}
# Settings of the customizable post-installation script that use one.
POST_INSTALL_USES = {'OVHRTM': ['ovh-rtm'], 'BASHRC': ['community-scripts']}


def third_party(names):
    """Who maintains the third-party scripts named, with their page."""
    return [dict(name=THIRD_PARTY[n]['name'], url=THIRD_PARTY[n]['url']) for n in names if n in THIRD_PARTY]


# The Catalog tab shows the sections of the main menu, each listing what its
# own menu lists. The menu's settings and the two catalogs stay out: the tab
# shows the applications and the scripts in its own way.
CATALOG_OUTSIDE = {'Community Scripts', 'OCI manager Apps (Technology Preview)', 'Settings'}
# A menu opened from inside a section belongs to that section.
SUBMENUS = {
    'Customizable post-installation script': 'Settings post-install Proxmox',
    'System Utilities Installer': 'Utilities and Tools',
    'Create VM System NAS': 'Create VM from template or script',
    'Create VM System Windows': 'Create VM from template or script',
    'Create VM System Linux': 'Create VM from template or script',
    'Create VM System Others (based Linux)': 'Create VM from template or script',
}


def main_sections():
    """The sections of the main menu, in its order: (name, script)."""
    try:
        text = (SCRIPTS / 'menus/main_menu.sh').read_text()
    except OSError:
        return []
    names = re.findall(r'^\s*([0-9a-z])\s+"\$\(translate "([^"]+)"\)"', text, re.M)
    scripts = dict(re.findall(r'^\s*([0-9a-z])\) (?:exec )?bash "\$LOCAL_SCRIPTS/([^"]+)"', text, re.M))
    return [(name, scripts[key]) for key, name in names if key in scripts]


def section_externals(script):
    """The Community Scripts scripts that a section's menu offers itself, by
    slug, in its order."""
    try:
        text = (SCRIPTS / script).read_text()
    except OSError:
        return []
    slugs = re.findall(r'^[^#\n]*community-scripts/ProxmoxVE/main/tools/pve/([a-z0-9-]+)\.sh', text, re.M)
    return list(dict.fromkeys(slugs))


def external_keys(name, script, placed):
    """The third-party scripts a section's menu lists apart, in its order: a
    Community Scripts script by its slug, any other by the option that runs
    it. An option that only opens a menu of them gives way to what that menu
    runs."""
    keys = []

    def add(item):
        key = f"cs:{item['cs']}" if item.get('cs') else f"pmx:{option_key(item['id'])}" if item.get('third_party') else ''
        if key and key not in keys:
            keys.append(key)
    for item in sorted((i for i in placed if i['section'] == name and i['menu'] == name and i.get('apart')),
                       key=lambda i: i['order']):
        children = [c for c in placed if c['menu'] == item.get('english')]
        if item.get('cs') or item.get('third_party') or not children:
            add(item)
        else:
            for child in children:
                add(child)
    for slug in section_externals(script):
        if f"cs:{slug}" not in keys:
            keys.append(f"cs:{slug}")
    return keys


def catalog_sections(placed=()):
    return [dict(name=name, title=tidy(translate(name)), external=external_keys(name, script, placed))
            for name, script in main_sections() if name not in CATALOG_OUTSIDE]


def catalog_placement(entries):
    """Where the Catalog tab shows each option: the section of the main menu
    it belongs to, whether opening that section lists it, as its menu does,
    or only a search finds it, and its place in that menu."""
    scripts = {name: script for name, script in main_sections() if name not in CATALOG_OUTSIDE}
    texts = {}
    for item in entries:
        menu = item.get('menu', '')
        section = SUBMENUS.get(menu, menu)
        item['section'] = section if section in scripts else ''
        english = item.get('english', '')
        if item['section'] not in texts:
            try:
                texts[item['section']] = (SCRIPTS / scripts[item['section']]).read_text() if item['section'] else ''
            except OSError:
                texts[item['section']] = ''
        # Where the menu lists the option: a line of its table of options, or
        # a row of its dialog, a key and then the text.
        text = texts[item['section']]
        position = text.find(f'"{english}|') if english else -1
        if english and position < 0:
            row = re.search(r'^\s*"?[0-9a-z]+"?\s+"\$\([^\n]*?["\']' + re.escape(english) + r'["\']', text, re.M)
            position = row.start() if row else -1
        item['order'] = position if position >= 0 else 1 << 30
        # The menu lists it below its heading of external scripts.
        heading = re.search(r'translate ["\']External Scripts["\']', text)
        item['apart'] = bool(heading) and position > heading.start()
        item['browse'] = position >= 0 and menu == section and english != section and item.get('via') != 'community-scripts'
    # A section whose menu is a single script lists that script.
    for section in scripts:
        members = [item for item in entries if item['section'] == section]
        if members and not any(item['browse'] for item in members):
            for item in members:
                item['browse'] = item.get('english') == section
    return entries


def linux_releases(family):
    """The official ISOs the Linux selector offers of one distribution."""
    try:
        text = (SCRIPTS / 'vm/select_linux_iso.sh').read_text()
    except OSError:
        return []
    return [f"{name} · {kind}" for name, kind in
            re.findall(r'^\s*"([^"|]+)\|([^"|]+)\|[^"|]*\|https://', text, re.M) if name.startswith(family)]


def own_entries():
    try:
        index = json.loads(INDEX.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    entries = []
    for item in index:
        script = SCRIPTS / item['script']
        if not script.is_file():
            continue
        title = tidy(translate(item['title']))
        # An option that lives inside a menu is given to that menu, which
        # opens it first.
        # A list names the system as well, which then opens without its menu.
        argument = item.get('argument') or []
        option = [str(value) for value in (argument if isinstance(argument, list) else [argument])]
        entries.append(dict(title=title, english=item['title'], source='ProxMenux', kind=tidy(translate(item['menu'])), menu=item['menu'],
                            terms=f"{title} {tidy(item['title'])} {item.get('keywords', '')}", related='',
                            action=['bash', str(script), *option], handoff=returns_to_a_menu(script),
                            id=f"menu:{item['script']}:{' '.join(option)}:{item['title']}", docs=item.get('docs', ''),
                            description=translate(item['summary']) if item.get('summary') else '',
                            about=translate(item['about']) if item.get('about') else '',
                            notes=[translate(note) for note in item.get('notes') or []],
                            releases=linux_releases(item['title']) if option[:1] == ['3'] and len(option) > 1 else [],
                            includes=post_install_includes(item.get('docs', '')),
                            third_party=(third_party([item['third_party']]) or [None])[0] if item.get('third_party') else None,
                            uses=third_party(item.get('uses') or []), cs=item.get('cs', ''),
                            **{key: item.get(key, '') for key in CATALOG_FIELDS}))
    return entries


def utility_entries():
    source = SCRIPTS / 'global/utils-install-functions.sh'
    installer = SCRIPTS / 'utilities/system_utils.sh'
    try:
        block = re.search(r'^PROXMENUX_UTILS=\(\s*\n(.*?)^\)', source.read_text(), re.M | re.S)
    except OSError:
        return []
    if not block or not installer.is_file():
        return []
    kind = tidy(translate('System Utilities Installer'))
    return [dict(title=package, source='ProxMenux', kind=kind, menu='System Utilities Installer', terms=f'{package} {command}',
                 related=f'{description} {translate(description)}',
                 action=['bash', str(installer), package], handoff=False,
                 id=f'utility:{package}', docs='utils/system-utils', description=translate(description))
            for package, command, description in
            re.findall(r'^\s*"([^":]+):([^":]+):([^"\n]+)"', block.group(1), re.M)]


def post_install_settings():
    """The settings of the customizable post-installation script, in its order:
    (category, title, token)."""
    try:
        block = re.search(r'^\s*local options=\(\s*\n(.*?)^\s*\)', (SCRIPTS / 'post_install/customizable_post_install.sh').read_text(),
                          re.M | re.S)
    except OSError:
        return []
    return re.findall(r'^\s*"([^"|]+)\|([^"|]+)\|([A-Za-z0-9_]+)"', block.group(1), re.M) if block else []


def automated_post_install_tokens():
    """The settings the automated post-installation script applies, in its
    order, named by the token of the same setting in the customizable one."""
    try:
        custom = (SCRIPTS / 'post_install/customizable_post_install.sh').read_text()
        auto = (SCRIPTS / 'post_install/auto_post_install.sh').read_text()
    except OSError:
        return []
    token_of = {function: token for token, function in re.findall(r'^\s*([A-Z0-9_]+)\)\s*([a-z0-9_]+)\s*;;', custom, re.M)}
    token_of.update(AUTO_POST_INSTALL_ALIASES)
    body = re.search(r'^run_complete_optimization\(\)\s*\{\n(.*?)^\}', auto, re.M | re.S)
    calls = re.findall(r'^\s*([a-z0-9_]+)\s*$', body.group(1), re.M) if body else []
    return [token_of[call] for call in calls if call in token_of]


def post_install_includes(docs):
    """What the automated or the customizable script does, setting by setting:
    a list of groups, each with the names of its settings."""
    settings = post_install_settings()
    if docs == 'post-install/automated':
        title_of = {token: title for _, title, token in settings}
        return [dict(group='', items=[tidy(translate(title_of[token])) for token in automated_post_install_tokens()
                                      if token in title_of])]
    if docs == 'post-install/customizable':
        # In the order of the categories of its checklist.
        try:
            order = {name: int(rank) for name, rank in re.findall(
                r'\["([^"]+)"\]=(\d+)', (SCRIPTS / 'post_install/customizable_post_install.sh').read_text())}
        except OSError:
            order = {}
        groups = []
        for category, title, _ in sorted(settings, key=lambda s: order.get(s[0], 999)):
            if not groups or groups[-1]['category'] != category:
                groups.append(dict(category=category, group=tidy(translate(category)), items=[]))
            groups[-1]['items'].append(tidy(translate(title)))
        return [dict(group=g['group'], items=g['items']) for g in groups]
    return []


def post_install_entries():
    script = SCRIPTS / 'post_install/customizable_post_install.sh'
    kind = tidy(translate('Customizable post-installation script'))
    return [dict(title=tidy(translate(title)), source='ProxMenux', kind=kind, menu='Customizable post-installation script',
                 terms=f'{translate(title)} {title} {token}', related=f'{category} post postinstall',
                 action=['bash', str(script), token], handoff=False,
                 id=f'post:{token}', docs=POST_INSTALL_DOCS.get(category, 'post-install/customizable'),
                 explains=POST_INSTALL_SECTIONS.get(token, ''), description='',
                 uses=third_party(POST_INSTALL_USES.get(token, [])))
            for category, title, token in post_install_settings()]


def oci_entries():
    launcher = SCRIPTS / 'oci/oci_manager_apps.sh'
    try:
        applications = json.loads(OCI_INDEX.read_text(encoding='utf-8')).get('applications', [])
    except (OSError, ValueError):
        return []
    if not launcher.is_file():
        return []
    kind = translate('OCI application')
    return [dict(title=item.get('title') or item['id'], source='OCI Manager', kind=kind,
                 terms=f"{item.get('title') or item['id']} {item['id']} {OCI_KEYWORDS.get(item['id'], '')}",
                 related=str(item.get('category_label') or ''),
                 action=['bash', str(launcher), 'open', item['id']], handoff=False)
            for item in applications
            if not item.get('hidden') and item.get('automatic_install_candidate')]


def helpers_catalog(refresh=True):
    """The Helper-Scripts catalog. It is kept on the host and downloaded again
    once a day; without a connection the one already here is used."""
    try:
        fresh = time.time() - HELPERS_CACHE.stat().st_mtime < HELPERS_MAX_AGE
    except OSError:
        fresh = False
    if refresh and not fresh:
        try:
            with urllib.request.urlopen(HELPERS_URL, timeout=15) as response:
                data = response.read()
            if isinstance(json.loads(data), list):
                temporary = HELPERS_CACHE.with_name(HELPERS_CACHE.name + '.new')
                temporary.write_bytes(data)
                os.replace(temporary, HELPERS_CACHE)
        except (OSError, ValueError):
            pass
    try:
        loaded = json.loads(HELPERS_CACHE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    return loaded if isinstance(loaded, list) else []


def helper_entries(refresh=True):
    launcher = SCRIPTS / 'menus/menu_Helper_Scripts.sh'
    if not launcher.is_file():
        return []
    entries, seen = [], set()
    for item in helpers_catalog(refresh):
        slug = item.get('slug')
        if not slug or slug in seen or not item.get('name'):
            continue
        seen.add(slug)
        entries.append(dict(title=item['name'], source='Community Scripts', kind=str(item.get('type', '')).upper(),
                            terms=f"{item['name']} {slug}",
                            related=' '.join(item.get('category_names', [])),
                            action=['bash', str(launcher), slug], handoff=False))
    return entries


def catalog(refresh=True):
    return own_entries() + utility_entries() + post_install_entries() + oci_entries() + helper_entries(refresh)


def search(items, query):
    """What matches every word of the query: by its name first, then by its
    category. The long description of an application is not searched, as it
    names other applications and would bring them all."""
    query = fold(query.strip())
    wanted = re.findall(r'[a-z0-9]+', query)
    if not wanted:
        return []

    def has_all(text):
        words = re.findall(r'[a-z0-9]+', text)
        return all(any(word.startswith(term) for word in words) for term in wanted)

    ranked = []
    for item in items:
        name = fold(item['title'])
        terms = fold(item['terms'])
        if has_all(terms):
            depth = 0
        elif has_all(f"{terms} {fold(item['related'])}"):
            depth = 1
        else:
            continue
        score = 0 if name == query else 1 if name.startswith(query) else 2 if query in name else 3
        source = SOURCES.index(item['source']) if item['source'] in SOURCES else len(SOURCES)
        ranked.append((depth, source, score, name, item))
    return [row[4] for row in sorted(ranked, key=lambda row: row[:4])]


def result_rows(matches, width):
    """One line per result in three columns. Only what is shown is cut."""
    labels = (translate('Name'), translate('Source'), translate('Type'))
    source_width = max(len(labels[1]), max(len(item['source']) for item in matches))
    kind_width = min(29, max(len(labels[2]), max(len(item['kind']) for item in matches)))
    name_width = max(12, width - source_width - kind_width - 6)

    def cell(value, size):
        value = re.sub(r'[\x00-\x1f\x7f]', ' ', value)
        return (value if len(value) <= size else value[:size - 1] + '…').ljust(size)

    def line(name, source, kind):
        return f'{cell(name, name_width)}  {cell(source, source_width)}  {cell(kind, kind_width)}'

    return line(*labels), [(str(number), line(item['title'], item['source'], item['kind']))
                           for number, item in enumerate(matches)]


def dialog(kind, title, text, rows=(), initial='', width=100, height=23):
    terminal = shutil.get_terminal_size((100, 30))
    width = max(40, min(width, terminal.columns))
    height = max(8, min(height, terminal.lines - 2))
    # The heading of the results is lined up with spaces, which are kept.
    args = ['dialog', '--clear', '--no-collapse', '--backtitle', 'ProxMenux', '--title', title]
    if kind == 'menu':
        args += ['--menu', text, str(height), str(width), str(max(3, min(len(rows), height - 6)))]
        for tag, label in rows:
            args += [tag, label]
    elif kind == 'inputbox':
        args += ['--inputbox', text, '10', str(min(width, 90)), initial]
    elif kind == 'infobox':
        args += ['--infobox', text, '5', str(min(width, 60))]
    else:
        args += ['--msgbox', text, '8', str(min(width, 70))]
    with open('/dev/tty', 'w') as tty:
        result = subprocess.run(args + ['--stdout'], stdout=subprocess.PIPE, stderr=tty, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def show_results(matches, query, handoff):
    """The results, until one that opens a menu is chosen or the list is left."""
    while True:
        columns = min(100, shutil.get_terminal_size((100, 24)).columns)
        heading, rows = result_rows(matches, max(60, columns - 16))
        tag_width = max(len(tag) for tag, _ in rows)
        row_width = max(len(label) for _, label in rows)
        # The list is centred in its window; the heading starts where its rows do.
        heading = ' ' * (max(0, (columns - 8 - row_width - tag_width - 2) // 2) + tag_width + 4) + heading
        selected = dialog('menu', f"{translate('Results:')} {query} ({len(matches)})", heading, rows)
        if selected is None:
            return False
        item = matches[int(selected)]
        if item['handoff'] and handoff:
            # A sub-menu goes back to the main menu on its own: the main menu opens it.
            handoff.write_text('\n'.join(item['action'][1:]) + '\n')
            return True
        subprocess.run(item['action'], check=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--search', metavar='QUERY', help='print the matches as JSON and exit')
    parser.add_argument('--handoff', type=Path, help='file that receives the sub-menu the main menu has to open')
    parser.add_argument('--list', action='store_true', help="print the menu's own options as JSON and exit")
    parser.add_argument('--run', metavar='ID', help='open one of the options --list prints')
    parser.add_argument('--language', help='language of the texts --list prints')
    parser.add_argument('--sections', action='store_true', help='print the sections of the main menu the Catalog tab shows')
    args = parser.parse_args()
    global _language
    if args.language and re.fullmatch(r'[a-z]{2}', args.language):
        _language = args.language
    if args.sections:
        placed = catalog_placement(own_entries() + utility_entries() + post_install_entries())
        print(json.dumps(catalog_sections(placed), ensure_ascii=False))
        return
    if args.list or args.run:
        own = own_entries() + utility_entries() + post_install_entries()
        if args.list:
            catalog_placement(own)
            print(json.dumps([{**{key: item[key] for key in ('id', 'title', 'kind', 'terms', 'description', 'docs', 'handoff',
                                                              'section', 'browse', 'order')},
                               'apart': item.get('apart', False), 'third_party': item.get('third_party'),
                               'uses': item.get('uses') or [],
                               **{key: item.get(key, '') for key in CATALOG_FIELDS},
                               **{key: item.get(key) or [] if key not in ('about', 'explains') else item.get(key, '')
                                  for key in ('about', 'notes', 'releases', 'includes', 'explains')},
                               'menu': item.get('menu', ''),
                               'key': option_key(item['id'])} for item in own], ensure_ascii=False))
            return
        # Only an option of the list itself is opened, never a command from outside.
        item = next((entry for entry in own if args.run in (entry['id'], option_key(entry['id']))), None)
        if item is None:
            raise SystemExit(f"{translate('No matches for:')} {args.run}")
        # The Catalog tab lets this script, and no other menu, be drawn.
        os.environ['PROXMENUX_CATALOG_TARGET'] = item['action'][1]
        os.execvp(item['action'][0], item['action'])
    if args.search is not None:
        print(json.dumps(search(catalog(), args.search), ensure_ascii=False, indent=2))
        return
    try:
        outdated = time.time() - HELPERS_CACHE.stat().st_mtime >= HELPERS_MAX_AGE
    except OSError:
        outdated = True
    if outdated:
        dialog('infobox', translate('Search'), '\n' + translate('Loading the Community Scripts catalog...'))
    items = catalog()
    query = ''
    while True:
        query = dialog('inputbox', translate('Search'),
                       translate('Name or part of the option or of the application'), initial=query)
        if query is None:
            return
        matches = search(items, query)
        if not matches:
            dialog('msgbox', translate('No results'), f"\n{translate('No matches for:')} {query}")
            continue
        if show_results(matches, query, args.handoff):
            return


if __name__ == '__main__':
    main()
