"""A corosync restart is not a node failure: departures are held for a grace,
a quick return is one rejoin notice, and only membership lines name a node.
The journal lines below were captured from a lab cluster during
`systemctl restart corosync` on one of its nodes."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import notification_events as ne  # noqa: E402
import notification_templates as nt  # noqa: E402

NAMES = {'1': 'pmxlab1', '2': 'pmxlab2', '3': 'pmxlab3'}


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


class FakeTimer:
    started = []

    def __init__(self, interval, function, args=()):
        self.interval, self.function, self.args = interval, function, args
        self.cancelled = False
        self.daemon = False

    def start(self):
        FakeTimer.started.append(self)

    def cancel(self):
        self.cancelled = True


class MembershipGraceTests(unittest.TestCase):
    def watcher(self, hostname):
        sub = type('Watcher', (ne.JournalWatcher,), {'_hostname': hostname})
        watcher = object.__new__(sub)
        watcher._recent_events = {}
        watcher._dedup_window = 30
        watcher.events = []

        class Queue:
            def put(self, event):
                watcher.events.append((event.event_type, event.severity, dict(event.data)))
        watcher._queue = Queue()
        watcher._corosync_node_names = lambda: NAMES
        return watcher

    def setUp(self):
        FakeTimer.started = []
        self.clock = Clock()
        for target, value in ((ne.threading, 'Timer'),):
            patcher = patch.object(target, value, FakeTimer)
            patcher.start()
            self.addCleanup(patcher.stop)
        for patcher in (patch.object(ne.time, 'time', self.clock),
                        patch.object(ne.startup_grace, 'is_real_system_boot', return_value=False)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def feed(self, watcher, host, lines):
        with patch.object(ne.socket, 'gethostname', return_value=host):
            for delay, ident, msg in lines:
                self.clock.now += delay
                watcher._check_cluster_events(msg, ident)

    def expire_timers(self):
        self.clock.now += ne.JournalWatcher.CLUSTER_LEAVE_GRACE_SECONDS
        for timer in list(FakeTimer.started):
            if not timer.cancelled:
                timer.function(*timer.args)

    def test_a_peer_corosync_restart_is_one_rejoin_notice(self):
        watcher = self.watcher('pmxlab1')
        self.feed(watcher, 'pmxlab1', [
            (0, 'corosync', '  [CFG   ] Node 2 was shut down by sysadmin'),
            (0, 'corosync', '  [QUORUM] Sync left[1]: 2'),
            (0, 'corosync', '  [TOTEM ] A new membership (1.59) was formed. Members left: 2'),
            (0, 'corosync', '  [QUORUM] This node is within the non-primary component and will NOT provide any services.'),
            (0, 'pmxcfs', '[status] notice: node lost quorum'),
            (3, 'corosync', '  [TOTEM ] A new membership (1.5e) was formed. Members joined: 2'),
            (0, 'pmxcfs', '[status] notice: node has quorum'),
        ])
        self.expire_timers()
        self.assertEqual(watcher.events, [('node_reconnect', 'INFO', {
            'node_name': 'pmxlab2', 'downtime_seconds': 3, 'hostname': 'pmxlab1',
            'clean_stop': True})])

    def test_a_short_absence_without_a_clean_stop_does_not_name_a_cause(self):
        watcher = self.watcher('pmxlab1')
        self.feed(watcher, 'pmxlab1', [
            (0, 'corosync', '  [TOTEM ] A new membership (1.59) was formed. Members left: 2'),
            (5, 'corosync', '  [TOTEM ] A new membership (1.5e) was formed. Members joined: 2'),
        ])
        self.expire_timers()
        self.assertEqual(watcher.events, [('node_reconnect', 'INFO', {
            'node_name': 'pmxlab2', 'downtime_seconds': 5, 'hostname': 'pmxlab1'})])

    def test_a_node_that_stays_away_is_reported_after_the_grace(self):
        watcher = self.watcher('pmxlab1')
        self.feed(watcher, 'pmxlab1', [
            (0, 'corosync', '  [TOTEM ] A new membership (1.59) was formed. Members left: 2'),
        ])
        self.assertEqual(watcher.events, [])
        self.expire_timers()
        self.assertEqual(watcher.events, [('node_disconnect', 'CRITICAL',
                                           {'node_name': 'pmxlab2', 'hostname': 'pmxlab1'})])
        self.feed(watcher, 'pmxlab1', [
            (600, 'corosync', '  [TOTEM ] A new membership (1.5e) was formed. Members joined: 2'),
        ])
        self.assertEqual(watcher.events[-1], ('node_reconnect', 'INFO',
                                              {'node_name': 'pmxlab2', 'hostname': 'pmxlab1'}))

    def test_our_own_restart_does_not_report_the_peers_as_reconnected(self):
        watcher = self.watcher('pmxlab2')
        self.feed(watcher, 'pmxlab2', [
            (0, 'corosync', '  [CFG   ] Node 2 was shut down by sysadmin'),
            (0, 'corosync', '  [MAIN  ] Node was shut down by a signal'),
            (0, 'pmxcfs', '[status] notice: node lost quorum'),
            (1, 'corosync', '  [TOTEM ] A new membership (2.5a) was formed. Members joined: 2'),
            (2, 'corosync', '  [TOTEM ] A new membership (1.5e) was formed. Members joined: 1'),
            (4, 'pmxcfs', '[status] notice: node has quorum'),
        ])
        self.expire_timers()
        self.assertEqual(watcher.events, [])

    def test_lines_that_only_mention_a_node_name_nothing(self):
        watcher = self.watcher('pmxlab1')
        self.feed(watcher, 'pmxlab1', [
            (0, 'pmxcfs', '[status] notice: node lost quorum'),
            (0, 'node_exporter', 'level=warn msg="node offline, lost connection"'),
            (0, 'app', 'worker node left the pool'),
            (0, '', 'quorum lost by votequorum'),
            (0, 'corosync', '  [QUORUM] Sync left[1]: 2'),
        ])
        self.expire_timers()
        self.assertEqual(watcher.events, [])

    def test_the_rejoin_notice_says_how_long_the_node_was_away(self):
        rendered = nt.render_template('node_reconnect', {
            'node_name': 'pve', 'downtime_seconds': 3, 'hostname': 'pve1'}, language='es')
        self.assertIn('pve', rendered['body'])
        self.assertIn('3 s', rendered['body'])
        self.assertNotIn('{', rendered['body'])
        self.assertNotIn('Corosync', rendered['body'])
        restarted = nt.render_template('node_reconnect', {
            'node_name': 'pve', 'downtime_seconds': 3, 'hostname': 'pve1', 'clean_stop': True}, language='en')
        self.assertEqual(restarted['body'], 'Corosync, the cluster communication service, was stopped on node pve '
                                            'and started again. The node rejoined the cluster after 3 s.')
        plain = nt.render_template('node_reconnect', {'node_name': 'pve', 'hostname': 'pve1'}, language='en')
        self.assertIn('rejoined the cluster successfully', plain['body'])


if __name__ == '__main__':
    unittest.main()
