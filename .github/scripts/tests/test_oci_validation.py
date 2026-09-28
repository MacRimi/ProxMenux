"""OCI validation record: generated list, record checks, credited authors and the report bot."""
import datetime
import importlib.util
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("oci_validation", ROOT / ".github/scripts/oci_validation.py")
validation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validation)

TODAY = datetime.date(2026, 9, 28)
REPORT = "https://github.com/MacRimi/ProxMenux/issues/400"
INDEX = {"applications": [
    {"id": "glances", "title": "Glances", "category_label": "Monitoring", "automatic_install_candidate": True},
    {"id": "2fauth", "title": "2FAuth", "category_label": "Security", "automatic_install_candidate": True},
    {"id": "legacy", "title": "Legacy | App", "category_label": "Other", "automatic_install_candidate": False},
    {"id": "hidden", "title": "Hidden", "hidden": True},
]}


def form(**answers):
    fields = {"Application": "Glances", "Image version": "4.3", "Image digest": "2026-09-06 · B1F339CF",
              "Proxmox VE version": "9.1", "Install mode": "Default configuration",
              "Data storage": "Volume on Proxmox storage", "Network": "DHCP", "GPU": "No GPU",
              "Result": "Works", "Notes": "_No response_"}
    fields.update(answers)
    return "\n\n".join(f"### {label}\n\n{value}" for label, value in fields.items())


def event(body=None, labels=("oci-validation", "validated"), user="Tester-1"):
    return {"issue": {"number": 400, "html_url": REPORT, "user": {"login": user}, "body": form() if body is None else body,
                      "labels": [{"name": name} for name in labels]}}


class Render(unittest.TestCase):
    def test_lists_community_and_installable_lab_entries(self):
        record = {"applications": {
            "glances": {"community_tested": {"by": "Vaso73", "date": "2026-09-27", "report": REPORT}},
            "2fauth": {"status": "laboratory-validated"},
            "legacy": {"status": "laboratory-validated"}}}
        text = validation.render(record, INDEX)
        self.assertIn("2 of 3 applications", text)
        self.assertIn("| Glances | [@Vaso73](https://github.com/Vaso73) | 2026-09-27 | — | — | [Report](" + REPORT + ") |", text)
        self.assertIn("| 2FAuth | Security |", text)
        # An application that cannot be installed is not listed as verified.
        self.assertNotIn("Legacy", text)

    def test_empty_record_and_escaped_titles(self):
        text = validation.render({"applications": {}}, INDEX)
        self.assertIn("No application has been tested by the community yet.", text)
        record = {"applications": {"legacy": {"community_tested": {"by": "a", "date": "2026-09-27"}}}}
        self.assertIn("| Legacy \\| App |", validation.render(record, INDEX))

    def test_repository_record_is_valid_and_current(self):
        record = validation.load(validation.VERIFICATION)
        index = validation.load(validation.INDEX)
        self.assertEqual(validation.problems(record, index, validation.OUTPUT.read_text(encoding="utf-8")), [])


class Problems(unittest.TestCase):
    def check(self, entry):
        return validation.problems({"applications": {"glances": entry}}, INDEX, today=TODAY)

    def test_valid_entries(self):
        self.assertEqual(self.check({"status": "laboratory-validated"}), [])
        self.assertEqual(self.check({"community_tested": {"by": "Vaso73", "date": "2026-09-27", "report": REPORT}}), [])
        self.assertEqual(self.check({"community_tested": {"by": "Vaso73", "date": "2026-09-27",
            "report": "https://github.com/MacRimi/ProxMenux/discussions/392#discussioncomment-18623868"}}), [])

    def test_rejected_entries(self):
        cases = [
            ({"status": "works"}, "status can only be"),
            ({"community_tested": {"by": "bad user", "date": "2026-09-27"}}, "GitHub user name"),
            ({"community_tested": {"by": "a", "date": "27/09/2026"}}, "YYYY-MM-DD"),
            ({"community_tested": {"by": "a", "date": "2027-01-01"}}, "in the future"),
            ({"community_tested": {"by": "a", "date": "2026-09-27", "report": "https://example.com/x"}}, "must link"),
            ({"community_tested": {"by": "a", "date": "2026-09-27", "extra": 1}}, "unknown community_tested keys"),
            ({"verified": True}, "unknown keys"),
            ({}, "non-empty object"),
        ]
        for entry, message in cases:
            with self.subTest(entry=entry):
                self.assertTrue(any(message in problem for problem in self.check(entry)), self.check(entry))
        self.assertTrue(validation.problems({"applications": {"nope": {"status": "laboratory-validated"}}}, INDEX))

    def test_stale_list_is_reported(self):
        record = {"applications": {"2fauth": {"status": "laboratory-validated"}}}
        self.assertTrue(any("out of date" in p for p in validation.problems(record, INDEX, "old", TODAY)))


class Authors(unittest.TestCase):
    base = {"applications": {"glances": {"community_tested": {"by": "Vaso73", "date": "2026-09-27"}},
                             "2fauth": {"status": "laboratory-validated"}}}

    def head(self, **changes):
        data = json.loads(json.dumps(self.base))
        data["applications"].update(changes)
        return data

    def test_author_adds_own_test(self):
        head = self.head(pocketbase={"community_tested": {"by": "f3rs3n", "date": "2026-09-28"}})
        self.assertEqual(validation.author_problems(self.base, head, "F3rs3n"), [])

    def test_crediting_someone_else_is_refused(self):
        head = self.head(pocketbase={"community_tested": {"by": "Vaso73", "date": "2026-09-28"}})
        self.assertEqual(validation.author_problems(self.base, head, "f3rs3n"),
                         ["pocketbase: credits @Vaso73, but the pull request is from @f3rs3n"])

    def test_lab_status_and_removals_are_for_the_maintainer(self):
        head = self.head(glances={}, pocketbase={"status": "laboratory-validated"})
        found = validation.author_problems(self.base, head, "f3rs3n")
        self.assertIn("glances: a community test is removed by the maintainer only", found)
        self.assertIn("pocketbase: the ProxMenux lab status is changed by the maintainer only", found)
        self.assertEqual(validation.author_problems(self.base, head, "MacRimi"), [])

    def test_missing_base_file(self):
        head = self.head(pocketbase={"community_tested": {"by": "f3rs3n", "date": "2026-09-28"}})
        self.assertEqual(validation.author_problems({}, {"applications": {"pocketbase": head["applications"]["pocketbase"]}},
                                                    "f3rs3n"), [])


class Record(unittest.TestCase):
    def test_parse_form_reads_github_issue_form_body(self):
        fields = validation.parse_form(form(Notes="Line one\r\nLine two"))
        self.assertEqual(fields["Application"], "Glances")
        self.assertEqual(fields["Notes"], "Line one\nLine two")
        self.assertEqual(validation.parse_form(form())["Notes"], "")

    def test_records_the_report_author(self):
        data, app, message = validation.record(event(), {"applications": {"glances": {"status": "laboratory-validated"}}},
                                               INDEX, TODAY)
        self.assertEqual(app, "glances")
        self.assertEqual(data["applications"]["glances"], {"status": "laboratory-validated", "community_tested": {
            "by": "Tester-1", "date": "2026-09-28", "report": REPORT, "digest": "b1f339cf",
            "scenario": "Default configuration · Volume on Proxmox storage · DHCP · No GPU · Proxmox VE 9.1 · image 4.3"}})
        self.assertIn("@Tester-1", message)
        self.assertEqual(validation.problems(data, INDEX, today=TODAY), [])

    def test_matches_id_or_title_and_replaces_older_test(self):
        record = {"applications": {"glances": {"community_tested": {"by": "Vaso73", "date": "2026-09-27"}}}}
        data, app, message = validation.record(event(form(Application="  glances ")), record, INDEX, TODAY)
        self.assertEqual(data["applications"]["glances"]["community_tested"]["by"], "Tester-1")
        self.assertIn("replaces the previous one from @Vaso73", message)
        self.assertEqual(record["applications"]["glances"]["community_tested"]["by"], "Vaso73")

    def test_refusals(self):
        for case, message in [
            (event(form(Application="Unknown")), "does not match"),
            (event(form(Result="Does not work")), "does not work"),
            (event(labels=("validated",)), "not an OCI validation report"),
            (event(user="bad user"), "could not be read"),
            (event(form(**{"Image digest": "latest"})), "does not hold an image digest"),
        ]:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    validation.record(case, {"applications": {}}, INDEX, TODAY)


class ReviewerComment(unittest.TestCase):
    allowed = frozenset({"macrimi", "vaso73", "f3rs3n"})

    def comment(self, reviewer, author="Tester-1"):
        data = event(labels=("oci-validation",), user=author)
        data["comment"] = {"user": {"login": reviewer}, "body": "/validated"}
        return data

    def test_listed_reviewer_validates_and_is_named(self):
        data, app, message = validation.record(self.comment("Vaso73"), {"applications": {}}, INDEX, TODAY, self.allowed)
        self.assertEqual(data["applications"]["glances"]["community_tested"]["by"], "Tester-1")
        self.assertIn("Validated by @Vaso73.", message)

    def test_unlisted_reviewer_and_own_report_are_refused(self):
        with self.assertRaisesRegex(ValueError, "not in the list of OCI validation reviewers"):
            validation.record(self.comment("someone"), {"applications": {}}, INDEX, TODAY, self.allowed)
        with self.assertRaisesRegex(ValueError, "other than its author"):
            validation.record(self.comment("f3rs3n", author="f3rs3n"), {"applications": {}}, INDEX, TODAY, self.allowed)

    def test_maintainer_may_validate_own_report_and_label_needs_no_list(self):
        validation.record(self.comment("MacRimi", author="MacRimi"), {"applications": {}}, INDEX, TODAY, self.allowed)
        validation.record(event(), {"applications": {}}, INDEX, TODAY)

    def test_reviewer_list_file(self):
        self.assertEqual(validation.reviewers("# comment\nMacRimi\n  Vaso73  # tester\nbad name\n"),
                         {"macrimi", "vaso73"})
        listed = validation.reviewers(validation.REVIEWERS.read_text(encoding="utf-8"))
        self.assertEqual(listed, self.allowed)


class ImageAndScenario(unittest.TestCase):
    def test_digest_as_the_monitor_shows_it_or_in_full(self):
        full = "sha256:" + "ab" * 32
        self.assertEqual(validation.image_digest("2026-09-06 · b1f339cf"), "b1f339cf")
        self.assertEqual(validation.image_digest(full.upper()), "ab" * 32)
        for value in ("", "b1f3", "latest", "sha256:xyz12345"):
            self.assertIsNone(validation.image_digest(value))

    def test_scenario_names_problems_and_skips_empty_fields(self):
        fields = validation.parse_form(form(Result="Works with problems", GPU="_No response_"))
        self.assertEqual(validation.scenario(fields), "Works with problems: Default configuration · "
                         "Volume on Proxmox storage · DHCP · Proxmox VE 9.1 · image 4.3")

    def test_list_shows_image_and_scenario(self):
        record = {"applications": {"glances": {"community_tested": {
            "by": "Vaso73", "date": "2026-09-27", "digest": "b1f339cf08ae", "scenario": "Default | DHCP"}}}}
        self.assertIn("| `b1f339cf08ae` | Default \\| DHCP |", validation.render(record, INDEX))

    def test_bad_digest_and_long_scenario_are_rejected(self):
        found = validation.problems({"applications": {"glances": {"community_tested": {
            "by": "a", "date": "2026-09-27", "digest": "XYZ", "scenario": "x" * 301}}}}, INDEX, today=TODAY)
        self.assertTrue(any("digest" in f for f in found) and any("scenario" in f for f in found), found)


class IssueForm(unittest.TestCase):
    def test_form_labels_match_the_bot(self):
        text = (ROOT / ".github/ISSUE_TEMPLATE/oci-validation.yml").read_text(encoding="utf-8")
        labels = re.findall(r"^\s+label: (.+)$", text, re.M)
        self.assertIn("Application", labels)
        self.assertIn("Result", labels)
        self.assertIn("Image digest", labels)
        for name in validation.SCENARIO_FIELDS:
            self.assertIn(name, labels)
        self.assertIn("- Does not work", text)
        self.assertIn('labels: ["oci-validation"]', text)
        self.assertIn("template=oci-validation.yml", validation.FORM)


if __name__ == "__main__":
    unittest.main()
