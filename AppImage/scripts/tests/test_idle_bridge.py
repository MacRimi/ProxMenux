"""A bridge with no port attached has no carrier and is not a failure: the
private network of an application whose containers are stopped."""
import sys
import tempfile
from pathlib import Path
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
from health_monitor import HealthMonitor


class IdleBridgeTests(unittest.TestCase):
    def bridge(self, flags, ports=()):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name) / 'vmbr10'
        (folder / 'brif').mkdir(parents=True)
        (folder / 'flags').write_text(flags + '\n')
        for port in ports:
            (folder / 'brif' / port).mkdir()
        return HealthMonitor._bridge_is_idle('vmbr10', tmp.name)

    def test_an_up_bridge_with_no_port_is_idle(self):
        self.assertTrue(self.bridge('0x1003'))

    def test_a_bridge_with_ports_and_no_carrier_is_not_idle(self):
        self.assertFalse(self.bridge('0x1003', ['enp3s0']))
        self.assertFalse(self.bridge('0x1003', ['veth115i1']))

    def test_a_bridge_set_down_is_not_idle(self):
        self.assertFalse(self.bridge('0x1002'))

    def test_an_interface_that_is_not_a_bridge_is_not_idle(self):
        self.assertFalse(HealthMonitor._bridge_is_idle('vmbr10', '/nonexistent'))


if __name__ == '__main__':
    unittest.main()
