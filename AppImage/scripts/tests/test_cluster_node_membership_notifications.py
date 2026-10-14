"""Corosync reports a node that leaves or comes back with its number, in a
membership line that never says "node". The surviving nodes notify it by the
name the node has in corosync.conf."""
import sys
import tempfile
import unittest
from pathlib import Path
from queue import Empty, Queue
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import notification_events  # noqa: E402

CONF = """totem {
  cluster_name: lab
}
nodelist {
  node {
    name: pve1
    nodeid: 1
    ring0_addr: 10.0.0.1
  }
  node {
    name: pve2
    nodeid: 2
    ring0_addr: 10.0.0.2
  }
  node {
    name: pve3
    nodeid: 3
    ring0_addr: 10.0.0.3
  }
}
"""


class ClusterMembershipTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        conf = Path(folder.name) / "corosync.conf"
        conf.write_text(CONF)
        real_open = open

        def corosync_conf(path, *args, **kwargs):
            if str(path) in ("/etc/pve/corosync.conf", "/etc/corosync/corosync.conf"):
                path = conf
            return real_open(path, *args, **kwargs)

        self.booting = False
        for item in (patch("builtins.open", corosync_conf),
                     patch.object(notification_events.socket, "gethostname", return_value="pve1"),
                     patch.object(notification_events.startup_grace, "is_real_system_boot",
                                  side_effect=lambda: self.booting),
                     patch.object(notification_events._shared_state, "is_startup_health_grace",
                                  side_effect=lambda: self.booting)):
            item.start()
            self.addCleanup(item.stop)
        self.queue = Queue()
        self.watcher = notification_events.JournalWatcher(self.queue)

    def notified(self, line):
        self.watcher._check_cluster_events(line, "corosync")
        events = []
        while True:
            try:
                event = self.queue.get_nowait()
            except Empty:
                return events
            events.append((event.event_type, event.data.get("node_name")))

    def test_a_node_that_leaves_is_named(self):
        self.assertEqual(self.notified("[TOTEM ] A new membership (1.55) was formed. Members left: 2"),
                         [("node_disconnect", "pve2")])

    def test_a_node_that_comes_back_is_named(self):
        self.assertEqual(self.notified("[TOTEM ] A new membership (1.5a) was formed. Members joined: 2"),
                         [("node_reconnect", "pve2")])

    def test_every_node_of_the_line_is_notified(self):
        self.assertEqual(self.notified("[TOTEM ] A new membership (1.60) was formed. Members left: 2 3"),
                         [("node_disconnect", "pve2"), ("node_disconnect", "pve3")])

    def test_this_node_is_not_notified(self):
        self.assertEqual(self.notified("[TOTEM ] A new membership (1.61) was formed. Members joined: 1"), [])

    def test_while_this_host_boots_only_the_joins_are_left_out(self):
        self.booting = True
        self.assertEqual(self.notified("[TOTEM ] A new membership (1.62) was formed. Members joined: 2"), [])
        self.assertEqual(self.notified("[TOTEM ] A new membership (1.63) was formed. Members left: 3"),
                         [("node_disconnect", "pve3")])

    def test_a_node_missing_from_the_configuration_keeps_its_number(self):
        self.assertEqual(self.notified("[TOTEM ] A new membership (1.64) was formed. Members left: 7"),
                         [("node_disconnect", "7")])

    def test_other_corosync_lines_notify_nothing(self):
        for line in ("[CFG   ] Node 2 was shut down by sysadmin", "[QUORUM] Members[2]: 1 3",
                     "[KNET  ] link: host: 2 link: 0 is down"):
            with self.subTest(line=line):
                self.assertEqual(self.notified(line), [])


if __name__ == "__main__":
    unittest.main()
