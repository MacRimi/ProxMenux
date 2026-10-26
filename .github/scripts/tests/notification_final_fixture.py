"""Inert infrastructure for actual endpoint/manual/queued/SQLite release seams."""
import datetime
import sqlite3
import tempfile
import threading
import time
import types
import typing
from html.parser import HTMLParser
from pathlib import Path
from notification_fixture import templates, SCRIPTS, EmailChannel, extract


def visible(markup):
    class Text(HTMLParser):
        def __init__(self): super().__init__(); self.parts = []; self.tags = []
        def handle_data(self, data): self.parts.append(data)
        def handle_starttag(self, tag, attrs): self.tags.append(tag)
    parser = Text(); parser.feed(markup)
    return '\n'.join(p.strip() for p in parser.parts if p.strip()), parser.tags


def restore_event(warnings):
    events = []
    ns = {'request': types.SimpleNamespace(remote_addr='127.0.0.1', get_json=lambda **kw: {
        'hostname':'node-a', 'guests':'3', 'stubs':'1', 'stale_nodes':'0',
        'components':'2', 'duration':'2m', 'warnings':warnings}),
        'notification_manager':types.SimpleNamespace(emit_event=lambda **kw:events.append(kw)),
        'jsonify':lambda value:value}
    handler = extract(SCRIPTS/'flask_notification_routes.py', 'internal_restore_event', None, ns)
    response, status = handler()
    assert status == 200 and len(events) == 1
    return events[0]


def deliver(event_type, data, severity='INFO', language='en', manual=False, quiet=False, quiet_before=()):
    """Execute real dispatch/manual and optional real SQLite buffer+flush."""
    captured = []
    channel = object.__new__(EmailChannel); channel.subject_prefix = '[ProxMenux]'
    def sink(title, body, severity, data):
        markup = channel._format_html(title, body, severity, data)
        text, tags = visible(markup)
        captured.append(dict(title=title, body=body, severity=severity, data=dict(data), html=markup, text=text, tags=tags))
        return {'success':True}
    manager = types.SimpleNamespace(_config={'email.rich_format':'true'}, _lock=threading.RLock(),
        _channels={'email':types.SimpleNamespace(send=sink)},
        _group_limiter=types.SimpleNamespace(allow=lambda group:True),
        _claim_delivery=lambda event:'inert', _finish_delivery_claim=lambda *a,**kw:None,
        _notification_language=lambda:language, _build_ai_config=lambda:{'ai_enabled':'false'},
        _in_quiet_hours=lambda channel:quiet, _should_buffer_for_digest=lambda *a:False,
        _record_history=lambda *a:None, _stats={'total_sent':0,'total_errors':0},
        is_event_enabled=lambda event:True)
    ns = dict(vars(typing), NotificationEvent=types.SimpleNamespace, TEMPLATES=templates.TEMPLATES, render_template=templates.render_template,
        resolve_notification_hostname=lambda host, config:host or 'node-a',
        enrich_with_emojis=templates.enrich_with_emojis, datetime=datetime.datetime,
        _should_bypass_ai=lambda event:True, _AI_BYPASS_EVENTS=frozenset({'backup_complete','backup_fail'}))
    for name in ('_dispatch_to_channels', '_dispatch_event', 'send_notification'):
        setattr(manager, name, types.MethodType(extract(SCRIPTS/'notification_manager.py', name, 'NotificationManager', ns), manager))
    with tempfile.TemporaryDirectory(prefix='notification-final-') as scratch:
        db = Path(scratch)/'pending.sqlite'
        rows = []
        if quiet:
            conn = sqlite3.connect(db)
            conn.execute('CREATE TABLE quiet_pending (id INTEGER PRIMARY KEY, channel TEXT, event_type TEXT, event_group TEXT, severity TEXT, ts INTEGER, title TEXT, body TEXT)')
            conn.commit(); conn.close()
            qns = dict(vars(typing), sqlite3=sqlite3, DB_PATH=db, time=time, datetime=datetime.datetime,
                _resolve_display_hostname=lambda config:'node-a', runtime_message=templates.runtime_message,
                EVENT_EMOJI=templates.EVENT_EMOJI, CATEGORY_EMOJI=templates.CATEGORY_EMOJI)
            for name in ('_buffer_quiet_event', '_flush_quiet_for_channel', '_compose_digest_body'):
                setattr(manager,name,types.MethodType(extract(SCRIPTS/'notification_manager.py',name,'NotificationManager',qns),manager))
            for earlier in quiet_before:
                manager._dispatch_event(types.SimpleNamespace(**earlier,source='inert',entity_type='node',entity_id='',event_id='inert',fingerprint='inert'))
        if manual:
            assert not quiet
            result = manager.send_notification(event_type, severity, '', '', dict(data))
            assert result['success']
        else:
            event = types.SimpleNamespace(event_type=event_type, severity=severity, data=dict(data), source='inert', entity_type='node', entity_id='', event_id='inert', fingerprint='inert')
            manager._dispatch_event(event)
        if quiet:
            conn = sqlite3.connect(db); rows = conn.execute('SELECT event_type,severity,title,body FROM quiet_pending').fetchall(); conn.close()
            assert len(rows)==1+len(quiet_before) and not captured
            manager._flush_quiet_for_channel('email', manager._channels['email'])
            conn=sqlite3.connect(db); remaining=conn.execute('SELECT count(*) FROM quiet_pending').fetchone()[0]; conn.close()
            assert remaining==0
        assert len(captured)==1
        if quiet: captured[0]['buffered']=rows
        return captured[0]
