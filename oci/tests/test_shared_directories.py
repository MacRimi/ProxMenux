"""An application that exists to share directories asks for them in every
installation, and its privileged profile is offered by the advanced one only."""

from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from proxmenux_oci import host
from proxmenux_oci.catalog import Catalog
from proxmenux_oci.installer import ADVANCED_MODE, DEFAULT_MODE, InstallError, build_deployment
from proxmenux_oci.recreation import edit_recreation
from test_advanced_flow_order import storages

NAME = "Name of the directory to share (lowercase letters, digits, - or _)"
MORE = "Add another directory to share?"
NFSV4 = "Prepare this container for NFSv4?"


class ScriptedUI:
    """Answers a question with the next scripted answer for it, then with its default."""

    def __init__(self, answers=None):
        self.answers = {key: list(value) for key, value in (answers or {}).items()}
        self.asked = []

    def _answer(self, text, default):
        self.asked.append(text)
        for key, values in self.answers.items():
            if (text == key or text.endswith(key)) and values:
                return values.pop(0)
        return default

    def ask(self, text, default=None, required=True):
        return self._answer(text, default if default is not None else "")

    def password(self, text, required=True):
        return self._answer(text, "")

    def choose(self, text, options, default=None):
        return self._answer(text, default)

    def confirm(self, text, default=False):
        return self._answer(text, default)

    def message(self, text):
        pass


@patch("proxmenux_oci.i18n.language", return_value="en")
@patch("proxmenux_oci.installer.host.storages", side_effect=storages)
@patch("proxmenux_oci.installer.host.default_storage", side_effect=lambda content, default: default)
@patch("proxmenux_oci.installer.host.default_bridge", side_effect=lambda default: default)
@patch("proxmenux_oci.installer.host.bridges", return_value=[{"iface": "vmbr0", "cidr": "192.0.2.10/24"}])
@patch("proxmenux_oci.installer.host.timezone", return_value="Europe/Madrid")
@patch("proxmenux_oci.installer.host.gpus", return_value={"intel": [], "amd": [], "nvidia": False})
@patch("proxmenux_oci.installer.access.ask_ipv4", return_value=("dhcp", None))
class SharedDirectoriesTests(unittest.TestCase):
    catalog = Catalog(ROOT)

    def build(self, answers, mode=DEFAULT_MODE):
        template = self.catalog.compose("sharecovex")
        ui = ScriptedUI(answers)
        return ui, template, build_deployment(template, ui, mode)

    def test_a_default_installation_asks_for_directories_until_the_answer_is_no(self, *_):
        ui, template, plan = self.build({
            NAME: ["media", "backups"],
            "Where to store /shares/media": ["host-bind"],
            "Host path for /shares/media": ["/tank/media"],
            "Size in GB of /shares/backups": ["200"],
            MORE: [True, False],
        })
        mounts = {m["container_path"]: m for m in plan["mounts"]}
        self.assertEqual(list(mounts), ["/config", "/shares/media", "/shares/backups"])
        self.assertEqual((mounts["/shares/media"]["type"], mounts["/shares/media"]["source"],
                          mounts["/shares/media"]["backup"], mounts["/shares/media"]["create_if_missing"]),
                         ("host-bind", "/tank/media", False, True))
        self.assertEqual((mounts["/shares/backups"]["type"], mounts["/shares/backups"]["size_gb"],
                          mounts["/shares/backups"]["backup"], mounts["/shares/backups"]["custom"]),
                         ("managed-volume", 200, True, True))
        self.assertEqual(mounts["/shares/backups"]["source"], mounts["/config"]["source"])
        self.assertEqual(ui.asked.count(NAME), 2)
        self.assertEqual(ui.asked.count(MORE), 2)
        # The volume is prepared for the identity the application writes with; /config stays with root.
        prepared = {item["container_path"]: item["owner_strategy"]
                    for item in template["proxmox"]["installer_profile"]["volume_preparations"]}
        self.assertEqual(prepared, {"/config": "mapped-root", "/shares/backups": "mapped-application-user"})

    def test_a_default_installation_stays_unprivileged_and_generates_the_panel_password(self, *_):
        ui, _template, plan = self.build({NAME: ["media"]})
        self.assertFalse(any(NFSV4 in text for text in ui.asked))
        self.assertFalse(any("Add an extra custom path" in text for text in ui.asked))
        self.assertEqual(plan["security"]["unprivileged"], True)
        self.assertEqual(plan["security"]["options"], {})
        password = next(item for item in plan["environment"] if item["name"] == "SHARECOVEX_ADMIN_PASSWORD")
        self.assertRegex(password["value"], r"^[0-9a-f]{16}$")
        self.assertFalse(any("ShareCoveX panel administrator" in text for text in ui.asked))
        self.assertEqual([m["container_path"] for m in plan["mounts"]], ["/config", "/shares/media"])
        self.assertEqual(plan["mounts"][1]["size_gb"], 32)
        # The settings stay small: their volume is created at the size the policy states.
        self.assertEqual(plan["mounts"][0]["size_gb"], 1)
        other = self.catalog.compose("seerr")["container_contract"]["volumes"][0]["managed_volume"]
        self.assertGreaterEqual(other["default_size_gb"], 16)

    def test_only_the_advanced_installation_offers_nfsv4_and_it_makes_the_container_privileged(self, *_):
        ui, _template, plan = self.build({NAME: ["media"]}, ADVANCED_MODE)
        self.assertTrue(any(NFSV4 in text for text in ui.asked))
        self.assertEqual((plan["security"]["unprivileged"], plan["security"]["privileged_acknowledged"]), (True, False))
        question = next(text for text in ui.asked if NFSV4 in text)
        ui, _template, plan = self.build({NAME: ["media"], question: [True]}, ADVANCED_MODE)
        security = plan["security"]
        self.assertEqual((security["unprivileged"], security["privileged_acknowledged"],
                          security["relaxation_acknowledged"]), (False, True, True))
        self.assertEqual(security["options"], {"apparmor_profile": "unconfined", "seccomp_profile": "unconfined"})

    def test_an_advanced_installation_places_each_directory_and_takes_the_password(self, *_):
        ui, _template, plan = self.build({
            NAME: ["media"],
            "Storage for /shares/media": ["Public"],
            "(empty = generate)": ["a-long-panel-password"],
        }, ADVANCED_MODE)
        mounts = {m["container_path"]: m["source"] for m in plan["mounts"]}
        self.assertEqual(mounts["/shares/media"], "Public")
        self.assertEqual(next(item["value"] for item in plan["environment"]), "a-long-panel-password")
        with self.assertRaisesRegex(InstallError, "minimum number of characters is 8"):
            self.build({NAME: ["media"], "(empty = generate)": ["short"]}, ADVANCED_MODE)

    def test_an_existing_directory_the_application_cannot_write_to_offers_access(self, *_):
        with tempfile.TemporaryDirectory() as directory:
            answers = {NAME: ["media"], "Where to store /shares/media": ["host-bind"],
                       "Host path for /shares/media": [directory]}
            with patch("proxmenux_oci.installer.host.can_write", return_value=False) as check:
                ui, _template, plan = self.build(answers)
                question = next(text for text in ui.asked if "Grant ShareCoveX access" in text)
                # The identity is the one of the volumes, in the range of an unprivileged container.
                check.assert_called_once_with(directory, 101000, 101000)
                self.assertIn("UID 101000", question)
                self.assertIn("changes owner or permissions", question)
                self.assertIs(plan["mounts"][1]["grant_access"], True)
                _ui, _template, declined = self.build({**answers, question: [False]})
                self.assertNotIn("grant_access", declined["mounts"][1])
            with patch("proxmenux_oci.installer.host.can_write", return_value=True):
                ui, _template, plan = self.build(answers)
                self.assertFalse(any("Grant ShareCoveX access" in text for text in ui.asked))
                self.assertNotIn("grant_access", plan["mounts"][1])
            # A privileged container writes with the identity as it is.
            nfsv4 = "NFSv4 needs a privileged container"
            with patch("proxmenux_oci.installer.host.can_write", return_value=False) as check:
                ui = ScriptedUI(answers)
                template = self.catalog.compose("sharecovex")
                first = build_deployment(template, ui, ADVANCED_MODE)
                prompt = next(text for text in ui.asked if nfsv4 in text)
                check.reset_mock()
                build_deployment(self.catalog.compose("sharecovex"), ScriptedUI({**answers, prompt: [True]}),
                                 ADVANCED_MODE)
                check.assert_called_once_with(directory, 1000, 1000)
                self.assertIsNotNone(first)

    def test_a_directory_that_does_not_exist_yet_is_created_for_the_application(self, *_):
        with patch("proxmenux_oci.installer.host.can_write") as check:
            ui, _template, plan = self.build({NAME: ["media"], "Where to store /shares/media": ["host-bind"],
                                              "Host path for /shares/media": ["/nonexistent/proxmenux-test/media"]})
        check.assert_not_called()
        self.assertNotIn("grant_access", plan["mounts"][1])
        self.assertIs(plan["mounts"][1]["create_if_missing"], True)

    def test_write_access_is_read_from_the_mode_bits(self, *_):
        with tempfile.TemporaryDirectory() as directory:
            status = os.stat(directory)
            os.chmod(directory, 0o750)
            self.assertTrue(host.can_write(directory, status.st_uid, 99999))
            self.assertFalse(host.can_write(directory, 99998, status.st_gid))
            self.assertFalse(host.can_write(directory, 99998, 99999))
            os.chmod(directory, 0o770)
            self.assertTrue(host.can_write(directory, 99998, status.st_gid))
            os.chmod(directory, 0o757)
            self.assertTrue(host.can_write(directory, 99998, 99999))
            os.chmod(directory, 0o700)
        self.assertFalse(host.can_write("/nonexistent/proxmenux-test", 0, 0))

    def test_the_installer_script_grants_access_only_when_asked(self, *_):
        script = (ROOT / "remote/install_oci.sh").read_text()
        self.assertIn("(.grant_access // false)] | @tsv", script)
        self.assertIn('if [[ -d $SOURCE && $GRANT_ACCESS == true ]]; then', script)
        # The owner is never changed, and the rule is not applied twice.
        grant = script[script.index("grant_shared_access() {"):script.index("MOUNT_ENTRIES=")]
        self.assertNotIn("chown", grant)
        self.assertNotIn("chmod", grant)
        self.assertIn('grep -q "^default:user:${HOST_BIND_UID}:rwx"', grant)
        self.assertIn('setfacl -R -P -m "u:${HOST_BIND_UID}:rwX,g:${HOST_BIND_GID}:rwX"', grant)

    def test_a_name_that_cannot_identify_a_share_is_refused(self, *_):
        for name in ("Media", "my files", "9lives", "config", "", "a" * 33):
            with self.assertRaisesRegex(ValueError, "lowercase"):
                self.build({NAME: [name]})
        with self.assertRaisesRegex(ValueError, "already shared"):
            self.build({NAME: ["media", "media"], MORE: [True, False]})

    def test_modify_can_add_another_directory_and_may_add_none(self, *_):
        _ui, template, plan = self.build({NAME: ["media"]})
        record = {"template": template, "deployment": plan}
        with patch("proxmenux_oci.recreation.refresh_template"), \
             patch("proxmenux_oci.recreation.edit_acceleration"), \
             patch("proxmenux_oci.recreation.edit_environment"):
            ui = ScriptedUI({"Add a directory to share": [True], NAME: ["photos"],
                             "Where to store /shares/photos": ["host-bind"],
                             "Host path for /shares/photos": ["/tank/photos"]})
            proposal = edit_recreation(record, ui)
            mounts = [m["container_path"] for m in proposal["candidate"]["deployment"]["mounts"]]
            self.assertEqual(mounts, ["/config", "/shares/media", "/shares/photos"])
            untouched = edit_recreation(record, ScriptedUI())
            self.assertEqual([m["container_path"] for m in untouched["candidate"]["deployment"]["mounts"]],
                             ["/config", "/shares/media"])
        self.assertEqual([m["container_path"] for m in plan["mounts"]], ["/config", "/shares/media"])


if __name__ == "__main__":
    unittest.main()
