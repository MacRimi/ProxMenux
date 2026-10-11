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
SOURCES = ('ProxMenux', 'OCI Manager', 'Helper-Scripts')
# Words an OCI application is also found by, when its name does not say them.
OCI_KEYWORDS = {'sharecovex': 'samba smb cifs nfs share compartir archivos time machine'}

_translations = None


def translate(text):
    """The text in the language of the menu; the text itself when it has none."""
    global _translations
    if _translations is None:
        _translations = {}
        try:
            language = json.loads((BASE / 'config.json').read_text()).get('language', 'en')
            if isinstance(language, str) and re.fullmatch(r'[a-z]{2}', language) and language != 'en':
                loaded = json.loads((BASE / 'lang' / f'{language}.json').read_text(encoding='utf-8'))
                if isinstance(loaded, dict):
                    _translations = loaded
        except (OSError, ValueError):
            pass
    value = _translations.get(text)
    return value if isinstance(value, str) and value else text


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
        option = [item['argument']] if item.get('argument') else []
        entries.append(dict(title=title, source='ProxMenux', kind=tidy(translate(item['menu'])),
                            terms=f"{title} {tidy(item['title'])} {item.get('keywords', '')}", related='',
                            action=['bash', str(script), *option], handoff=returns_to_a_menu(script)))
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
    return [dict(title=package, source='ProxMenux', kind=kind, terms=f'{package} {command}',
                 related=f'{description} {translate(description)}',
                 action=['bash', str(installer), package], handoff=False)
            for package, command, description in
            re.findall(r'^\s*"([^":]+):([^":]+):([^"\n]+)"', block.group(1), re.M)]


def post_install_entries():
    script = SCRIPTS / 'post_install/customizable_post_install.sh'
    try:
        block = re.search(r'^\s*local options=\(\s*\n(.*?)^\s*\)', script.read_text(), re.M | re.S)
    except OSError:
        return []
    if not block:
        return []
    kind = tidy(translate('Customizable post-installation script'))
    return [dict(title=tidy(translate(title)), source='ProxMenux', kind=kind,
                 terms=f'{translate(title)} {title} {token}', related=f'{category} post postinstall',
                 action=['bash', str(script), token], handoff=False)
            for category, title, token in
            re.findall(r'^\s*"([^"|]+)\|([^"|]+)\|([A-Za-z0-9_]+)"', block.group(1), re.M)]


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
        entries.append(dict(title=item['name'], source='Helper-Scripts', kind=str(item.get('type', '')).upper(),
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
    args = parser.parse_args()
    if args.search is not None:
        print(json.dumps(search(catalog(), args.search), ensure_ascii=False, indent=2))
        return
    try:
        outdated = time.time() - HELPERS_CACHE.stat().st_mtime >= HELPERS_MAX_AGE
    except OSError:
        outdated = True
    if outdated:
        dialog('infobox', translate('Search'), '\n' + translate('Loading the Helper-Scripts catalog...'))
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
