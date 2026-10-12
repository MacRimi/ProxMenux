"""An image that is not in the catalog can also be installed from an
oci-compose: one written by hand with what its author decides, a file of the
catalog, or the record of an installed application, of which only the template
is read."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxmenux_oci import custom
from proxmenux_oci.catalog import Catalog
from proxmenux_oci.converter import ConversionError

CATALOG = Catalog(ROOT)
EXAMPLES = ("jellyfin-official", "duplicati-official")
# Fields that describe where a template came from and are not read to install it.
ORIGIN = {"id", "compose_source_example", "source", "pull_policy"}


def catalog_file(app):
    return (ROOT / "catalog/apps" / f"{app}.json").read_text(encoding="utf-8")


def example(app):
    return (ROOT / "examples" / f"{app}.oci-compose.json").read_text(encoding="utf-8")


def installed(value):
    """A block without the fields that only say where it came from."""
    if isinstance(value, dict):
        return {key: installed(item) for key, item in value.items() if key not in ORIGIN}
    if isinstance(value, list):
        return [installed(item) for item in value]
    return value


class FakeUI:
    def __init__(self, choices, answers=()):
        self.choices, self.answers = list(choices), list(answers)
        self.offered, self.reviews, self.asked = [], [], []

    def choose(self, prompt, options, default=None, **kwargs):
        self.offered.append([key for key, _ in options])
        return self.choices.pop(0)

    def ask(self, prompt, default="", **kwargs):
        self.asked.append(prompt)
        return self.answers.pop(0)

    def review(self, text, title, **kwargs):
        self.reviews.append(text)
        return True

    def message(self, text, title=None):
        self.reviews.append(text)


class CompleteFileTests(unittest.TestCase):
    def test_a_file_of_the_catalog_is_read_as_it_is(self):
        template = custom.template_from_oci_compose(catalog_file("mariadb"))
        self.assertEqual(template["kind"], "proxmenux.oci-template")
        self.assertEqual(template["container_contract"]["image"]["reference"], "lscr.io/linuxserver/mariadb:latest")

    def test_of_an_installation_record_only_the_template_is_taken(self):
        record = {"vmid": 114, "status": "installed", "template": json.loads(catalog_file("mariadb")),
                  "deployment": {"environment": [{"name": "MYSQL_ROOT_PASSWORD", "value": "the-secret-of-someone"}]}}
        template = custom.template_from_oci_compose(json.dumps(record))
        self.assertEqual(template["container_contract"]["image"]["reference"], "lscr.io/linuxserver/mariadb:latest")
        self.assertNotIn("the-secret-of-someone", json.dumps(template))
        self.assertNotIn("deployment", template)

    def test_a_template_taken_from_an_installation_installs_the_same(self):
        # The record of an installation holds the template as the catalog
        # composed it; reading it again must not change it.
        index = json.loads((ROOT / "catalog/index.json").read_text(encoding="utf-8"))["applications"]
        checked = 0
        for item in index:
            if item.get("hidden") or not item.get("automatic_install_candidate"):
                continue
            composed = CATALOG.compose(item["id"])
            again = custom.template_from_oci_compose(json.dumps(composed))
            for template in (composed, again):
                template.pop("status", None)
                template.pop("community_tested", None)
            self.assertEqual(again, composed, item["id"])
            checked += 1
        self.assertGreater(checked, 300)

    def test_it_is_not_verified_because_it_says_so(self):
        document = json.loads(catalog_file("mariadb"))
        document["status"] = "laboratory-validated"
        document["community_tested"] = {"by": "someone"}
        template = custom.template_from_oci_compose(json.dumps(document))
        self.assertNotEqual(template["status"], "laboratory-validated")
        self.assertNotIn("community_tested", template)


class HandWrittenTests(unittest.TestCase):
    """An oci-compose written by hand says what its author decides; ProxMenux
    completes it with what it writes for any image."""

    def test_the_examples_install_what_the_catalog_installs(self):
        for app in EXAMPLES:
            with self.subTest(app=app):
                written = json.loads(example(app))
                self.assertNotIn("compose_stack", written)
                self.assertNotIn("source", written)
                template = custom.template_from_oci_compose(example(app))
                catalog = CATALOG.compose(app)
                for field in ("image", "ports", "environment", "restart", "service_name", "container_name"):
                    self.assertEqual(installed(template["container_contract"][field]),
                                     installed(catalog["container_contract"][field]), field)
                self.assertEqual(installed(template["container_contract"]["volumes"]),
                                 installed(catalog["container_contract"]["volumes"]))
                self.assertEqual(template["proxmox"]["defaults"], catalog["proxmox"]["defaults"])
                for name in sorted(set(template["proxmox"]["installer_profile"]) | set(catalog["proxmox"]["installer_profile"])):
                    if name == "network":
                        # Says how Docker connected it; nothing reads it here.
                        continue
                    self.assertEqual(template["proxmox"]["installer_profile"].get(name),
                                     catalog["proxmox"]["installer_profile"].get(name), name)
                self.assertEqual(template["first_run"], catalog["first_run"])
                self.assertEqual(template["catalog_ui"]["category_label"], catalog["catalog_ui"]["category_label"])
                self.assertTrue(template["compatibility"]["automatic_install_candidate"])
                self.assertEqual(CATALOG.schema_errors(template), [])

    def test_the_least_an_oci_compose_says_is_its_image(self):
        template = custom.template_from_oci_compose(json.dumps(
            {"kind": "proxmenux.oci-template", "container_contract": {"image": {"reference": "traefik/whoami:latest"}}}))
        self.assertEqual(template["container_contract"]["image"]["repository"], "traefik/whoami")
        self.assertEqual(template["catalog_ui"]["title"], {"en_US": "whoami"})
        self.assertEqual(template["container_contract"]["volumes"], [])
        self.assertEqual(CATALOG.schema_errors(template), [])

    def test_what_the_author_writes_is_kept(self):
        document = json.loads(example("duplicati-official"))
        document["container_contract"]["ports"] = [{"container_port": 5514, "protocol": "udp", "required": False}]
        document["container_contract"]["volumes"][0].update(read_only=True, managed_volume={"default_size_gb": 40})
        document["container_contract"]["volumes"].append(
            {"container_path": "/exports", "installation_choice": ["managed-volume", "host-bind"]})
        document["container_contract"]["volumes"].append({"container_path": "/state"})
        document["catalog_ui"]["launch"] = {"scheme": "http", "port": None, "path": "/"}
        document["first_run"] = {"endpoints": [], "credentials": []}
        document["proxmox"]["defaults"] = {"memory_mb": 512}
        template = custom.template_from_oci_compose(json.dumps(document))
        port = template["container_contract"]["ports"][0]
        self.assertEqual((port["container_port"], port["protocol"], port["required"]), (5514, "udp", False))
        data, _, _, exports, state = template["container_contract"]["volumes"]
        self.assertTrue(data["read_only"])
        self.assertEqual(data["managed_volume"], {"backup": True, "default_size_gb": 40})
        # A path its author gives as a host directory is offered as one; the
        # others follow the rule of the catalog and stay in a container volume.
        self.assertEqual(exports["installation_choice"], ["managed-volume", "host-bind"])
        self.assertEqual(state["installation_choice"], ["managed-volume"])
        self.assertEqual(data["installation_choice"], ["managed-volume"])
        self.assertEqual(template["first_run"]["endpoints"], [])
        self.assertIsNone(template["catalog_ui"]["launch"]["port"])
        self.assertEqual(template["proxmox"]["defaults"]["memory_mb"], 512)
        self.assertEqual(template["proxmox"]["defaults"]["cores"], 2)

    def test_a_secret_left_empty_is_not_given_a_value(self):
        template = custom.template_from_oci_compose(example("duplicati-official"))
        self.assertEqual([item["example"] for item in template["container_contract"]["environment"]], ["", ""])


class FaultTests(unittest.TestCase):
    def test_what_is_not_an_oci_compose_is_refused(self):
        for text in ("services:\n  app:\n    image: x", "[1, 2]", json.dumps({"kind": "something-else"}),
                     json.dumps({"kind": "proxmenux.oci-template", "container_contract": {"image": {}}}),
                     json.dumps({"kind": "proxmenux.oci-template", "container_contract": "jellyfin"})):
            with self.subTest(text=text[:30]):
                with self.assertRaises(ConversionError):
                    custom.template_from_oci_compose(text)

    def test_a_fault_says_where_it_is(self):
        for edit, where in ((lambda d: d["container_contract"].update(ports="8200"), "ports"),
                            (lambda d: d["container_contract"]["volumes"].append({"path": "/x"}),
                             "container_contract/volumes/3/container_path: required"),
                            (lambda d: d["first_run"].update(endpoints=[{"port": 8200}]), "first_run/endpoints/0"),
                            (lambda d: d["catalog_ui"].update(launch={"port": "8200"}), "catalog_ui/launch"),
                            (lambda d: d["container_contract"]["image"].update(reference="not an image"), "not an image")):
            with self.subTest(where=where):
                document = json.loads(example("duplicati-official"))
                edit(document)
                with self.assertRaises(ConversionError) as raised:
                    custom.template_from_oci_compose(json.dumps(document))
                self.assertIn(where, str(raised.exception))

    def test_a_fault_is_reported_on_a_node_that_cannot_check_the_schema(self):
        document = json.loads(example("duplicati-official"))
        document["first_run"]["endpoints"] = [{"port": 8200}]
        with patch.object(Catalog, "schema_errors", return_value=None):
            custom.template_from_oci_compose(example("duplicati-official"))
            with self.assertRaises(ConversionError) as raised:
                custom.template_from_oci_compose(json.dumps(document))
        self.assertIn("The oci-compose has errors:", str(raised.exception))
        self.assertIn("first_run/endpoints/0/label: required", str(raised.exception))

    def test_the_check_without_the_schema_library_accepts_every_file_of_the_catalog(self):
        index = json.loads((ROOT / "catalog/index.json").read_text(encoding="utf-8"))["applications"]
        for item in index:
            if item.get("hidden") or not item.get("automatic_install_candidate"):
                continue
            self.assertEqual(CATALOG.shape_errors(CATALOG.compose(item["id"])), [], item["id"])
        document = json.loads(catalog_file("mariadb"))
        document["container_contract"]["ports"] = "3306"
        document["container_contract"]["volumes"][0]["container_path"] = 7
        self.assertEqual(CATALOG.shape_errors(document),
                         ["container_contract/volumes/0/container_path: string", "container_contract/ports: array"])


class MenuTests(unittest.TestCase):
    def test_the_review_says_what_an_oci_compose_adds(self):
        text = custom.describe_oci_compose(CATALOG.compose("filebrowser-quantum"))
        self.assertIn("/home/filebrowser/data/config.yaml", text)
        self.assertIn("Install it only if it comes from a source you trust.", text)
        self.assertTrue(text.startswith("\n\n"))

    def test_the_menu_offers_an_oci_compose_from_a_file_or_an_address(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "oci-compose.json"
            path.write_text(example("jellyfin-official"), encoding="utf-8")
            ui = FakeUI(["oci-compose"], [str(path)])
            text, origin = custom.read_definition(ui)
        self.assertEqual(ui.offered[0][-2:], ["oci-compose", "oci-compose-url"])
        self.assertEqual(origin, custom.OCI_COMPOSE)
        self.assertEqual(json.loads(text)["catalog_ui"]["title"], {"en_US": "Jellyfin Official"})

    def test_an_oci_compose_keeps_its_name_and_its_own_questions(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "oci-compose.json"
            path.write_text(example("duplicati-official"), encoding="utf-8")
            ui = FakeUI(["oci-compose", custom.DEFAULT_MODE], [str(path)])
            with patch.object(custom, "registry_report", return_value=(True, "image found")), \
                    patch.object(custom, "install_template") as install, \
                    patch.object(custom, "_ask_secrets", side_effect=AssertionError("not for an oci-compose")), \
                    patch.object(custom, "_name", side_effect=AssertionError("not for an oci-compose")):
                custom.explore(ui)
        _, template, name, mode = install.call_args.args
        self.assertEqual(name, "duplicati-official")
        self.assertEqual(mode, custom.DEFAULT_MODE)
        self.assertEqual(len(ui.asked), 1)
        self.assertTrue(ui.reviews[0].startswith("This is what the oci-compose installs:"))
        self.assertIn("Install it only if it comes from a source you trust.", ui.reviews[0])

    def test_a_compose_file_is_read_as_before(self):
        compose = "services:\n  whoami:\n    image: traefik/whoami:latest\n    ports:\n      - 8080:80\n"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "docker-compose.yml"
            path.write_text(compose, encoding="utf-8")
            ui = FakeUI(["file", None], [str(path), "whoami"])
            with patch.object(custom, "registry_report", return_value=(True, "image found")), \
                    patch.object(custom, "install_template") as install:
                custom.explore(ui)
        install.assert_not_called()
        self.assertNotIn("Install it only if it comes from a source you trust.", ui.reviews[0])
        self.assertNotIn("oci-compose", ui.reviews[0])


if __name__ == "__main__":
    unittest.main()
