"""Assertion-free inert actual consumers; no operational host imports."""
import ast
import re
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / 'AppImage/scripts'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import notification_templates as templates
# Display-name resolution is an infrastructure boundary, never load manager.
templates._get_hostname = lambda: 'node-a'
from notification_channels import EmailChannel
LANGUAGES = ('en', 'de', 'es', 'fr', 'it', 'pt', 'sk', 'sv')

def extract(path, name, owner, ns):
    tree = ast.parse(path.read_text())
    nodes = tree.body if owner is None else next(n.body for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner)
    node = next(n for n in nodes if isinstance(n, ast.FunctionDef) and n.name == name)
    node.decorator_list = []
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), ns)
    return ns[name]

def receive(message, severity='info', title='Backup', kind='vzdump'):
    ns = {'re': re, 'capture_journal_context': lambda **kw: ''}
    class Event:
        def __init__(self, **kw): self.__dict__.update(kw); self.event_id = 'inert'
    ns['NotificationEvent'] = Event
    methods = {name: extract(SCRIPTS / 'notification_events.py', name, 'ProxmoxHookWatcher', ns)
               for name in ('_classify_pve', '_map_severity', '_backup_outcome', 'process_webhook')}
    class Queue:
        def __init__(self): self.items = []
        def put(self, event): self.items.append(event)
    class Receiver:
        _hostname = 'node-a'
        _classify_pve = methods['_classify_pve']
        _map_severity = staticmethod(methods['_map_severity'])
        _backup_outcome = staticmethod(methods['_backup_outcome'])
        process_webhook = methods['process_webhook']
        def __init__(self): self._queue = Queue()
    target = Receiver()
    result = target.process_webhook({'fields': {'type': kind}, 'severity': severity, 'title': title, 'message': message})
    assert result['accepted'] and len(target._queue.items) == 1
    return target._queue.items[0]

def email(event_type, data, severity='INFO', language='en'):
    result = templates.render_template(event_type, data, language)
    channel = object.__new__(EmailChannel)
    channel.subject_prefix = '[ProxMenux]'
    context = {**data, 'severity': severity, '_event_type': event_type, '_group': result['group'], '_notification_language': language}
    return result, channel._format_html(result['title'], result['body'], severity, context)
