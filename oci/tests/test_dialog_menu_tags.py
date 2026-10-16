"""A menu shows numbers, not internal values: the code still receives the
value of the option chosen. A tag the user reads, such as a storage, stays."""

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxmenux_oci.ui import DialogUI, ReadableTags

SOURCES = [("paste", "Paste its Compose file in the terminal"),
           ("file", "Read its Compose file from a file of this host"),
           ("oci-compose-paste", "Paste an oci-compose in the terminal")]


class DialogMenuTagsTests(unittest.TestCase):
    def run_menu(self, options, answer, **kwargs):
        seen = {}

        def run(widget, title):
            seen["widget"] = widget
            return SimpleNamespace(returncode=0, stderr=answer)

        ui = DialogUI()
        with patch.object(ui, "_run", side_effect=run):
            selected = ui.choose("How is the image described?", options, **kwargs)
        menu = seen["widget"][seen["widget"].index("--menu") + 5:]
        return selected, menu[0::2], seen["widget"]

    def test_word_tags_are_shown_as_numbers_and_the_value_comes_back(self):
        selected, tags, _ = self.run_menu(SOURCES, "3", default="file", size=(20, 80, 10))
        self.assertEqual(tags, ["1", "2", "3"])
        self.assertEqual(selected, "oci-compose-paste")

    def test_the_default_follows_its_number(self):
        _, _, widget = self.run_menu(SOURCES, "2", default="file")
        self.assertEqual(widget[widget.index("--default-item") + 1], "2")

    def test_a_tag_the_user_reads_is_kept(self):
        storages = [("local-lvm", "lvmthin  669 GB free"), ("local2-lvm", "lvmthin  269 GB free")]
        selected, tags, _ = self.run_menu(ReadableTags(storages), "local2-lvm")
        self.assertEqual((tags, selected), (["local-lvm", "local2-lvm"], "local2-lvm"))

    def test_number_tags_and_separators_are_left_as_they_are(self):
        options = [("101", "Jellyfin"), ("", ""), ("205", "Immich")]
        selected, tags, _ = self.run_menu(options, "205")
        self.assertEqual((tags, selected), (["101", "", "205"], "205"))

    def test_cancelling_returns_nothing(self):
        ui = DialogUI()
        with patch.object(ui, "_run", return_value=SimpleNamespace(returncode=1, stderr="")):
            self.assertIsNone(ui.choose("How is the image described?", SOURCES))


if __name__ == "__main__":
    unittest.main()
