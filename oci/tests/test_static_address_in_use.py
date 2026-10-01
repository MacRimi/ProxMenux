"""A static address another device of the network already uses is not accepted."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxmenux_oci import network

BRIDGES = [{"iface": "vmbr0", "cidr": "192.168.0.50/24", "gateway": "192.168.0.1"}]


class SequenceUI:
    def __init__(self, answers):
        self.answers = iter(answers)
        self.messages = []

    def choose(self, *_args, **_kwargs):
        return next(self.answers)

    def ask(self, *_args, **_kwargs):
        return next(self.answers)

    def message(self, text):
        self.messages.append(text)


@patch("proxmenux_oci.i18n.language", return_value="en")
@patch.object(network.host, "bridges", return_value=BRIDGES)
@patch.object(network, "addresses_in_use", return_value=set())
class StaticAddressInUseTests(unittest.TestCase):
    def test_an_address_that_answers_is_asked_again(self, *_):
        ui = SequenceUI([network.STATIC, "192.168.0.99/24", "192.168.0.170/24", "192.168.0.1"])
        with patch.object(network.host, "address_answers", side_effect=lambda ip, bridge: ip == "192.168.0.99") as probe:
            addresses, gateway = network.ask_addresses(ui, "vmbr0", [""])
        self.assertEqual((addresses[""], gateway), ("192.168.0.170/24", "192.168.0.1"))
        self.assertEqual([call.args for call in probe.call_args_list],
                         [("192.168.0.99", "vmbr0"), ("192.168.0.170", "vmbr0")])
        self.assertEqual(len(ui.messages), 1)
        self.assertIn("192.168.0.99", ui.messages[0])

    def test_the_address_the_container_already_has_is_not_probed(self, *_):
        ui = SequenceUI([network.STATIC, "192.168.0.169/24", "192.168.0.1"])
        with patch.object(network.host, "address_answers", return_value=True) as probe:
            addresses, _gateway = network.ask_addresses(ui, "vmbr0", [""], {"": "192.168.0.169/24"}, "192.168.0.1")
        self.assertEqual(addresses[""], "192.168.0.169/24")
        probe.assert_not_called()
        self.assertEqual(ui.messages, [])


if __name__ == "__main__":
    unittest.main()
