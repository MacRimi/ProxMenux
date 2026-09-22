"""Offline message seams: no full administrative script is sourced or run.

Run: python3 -m unittest discover -s tests -p test_tui_count_messages.py -v
Requires Bash and jq. Only extracted translation functions and bounded message
consumers execute. PATH contains jq only; VM/disk/backup commands are unavailable.
"""
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
VM = "scripts/storage/add_controller_nvme_vm.sh"
BACKUP = "scripts/backup_restore/backup_host.sh"


def between(path, start, end):
    text = (ROOT / path).read_text()
    assert text.count(start) == 1, (path, start)
    tail = text.split(start, 1)[1]
    assert end in tail, (path, end)
    return start + tail.split(end, 1)[0]


def function(path, name):
    # These two small functions have no unindented nested closing braces.
    text = (ROOT / path).read_text()
    match = re.search(r"^" + re.escape(name) + r"\(\) \{\n.*?^\}", text, re.M | re.S)
    assert match, (path, name)
    return match[0]


def lookup(catalog, text):
    return (catalog or {}).get(text) or text


class CountMessages(unittest.TestCase):
    def locales(self, key, translated):
        return (("en", None), ("it", {}), ("zz", None),
                ("it", json.loads((ROOT / "lang/it.json").read_text())),
                ("xx", {key: translated}),
                # Presence is the bounded contract: repeated tokens are replaced
                # everywhere; unrelated braces remain literal, not a format DSL.
                ("repeat", {key: translated + " / again " + key}),
                ("extra", {key: translated + " / {unknown} $(literal) %s"})
                ) + self.malformed_locales(key)

    def malformed_locales(self, key):
        required = ("{count}", "{vmid}") if "{vmid}" in key else ("{count}",)
        # These cached values must fall back as a whole, not lose a value.
        malformed = ["Translated without values."]
        for token in required:
            malformed.extend((key.replace(token, ""),
                              key.replace(token, "{renamed}"),
                              key.replace(token, token.upper())))
        return tuple(("bad", {key: text}) for text in malformed)

    def test_new_messages_are_discovered_by_cache_builder(self):
        spec = importlib.util.spec_from_file_location(
            "translation_cache", ROOT / ".github/scripts/build_translation_cache.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        keys = module.extract_translate_texts(ROOT / "scripts")
        for key in ("Completed. Devices added to VM {vmid}: {count}.",
                    "Custom paths currently saved: {count}.", "Packages installed: {count}."):
            self.assertIn(key, keys)

    def render(self, seam, setup, language="en", catalog=None):
        jq = shutil.which("jq")
        self.assertIsNotNone(jq, "jq is required for actual translation lookup")
        with tempfile.TemporaryDirectory(prefix="pmx-count-messages-") as tmp:
            tmp = Path(tmp)
            (tmp / "bin").mkdir()
            (tmp / "bin" / "jq").symlink_to(jq)
            (tmp / "lang").mkdir()
            if catalog is not None:
                (tmp / "lang" / f"{language}.json").write_text(json.dumps(catalog))
            shell = function("scripts/utils.sh", "translate") + "\n"
            shell += function("scripts/backup_restore/lib_host_backup_common.sh", "hb_translate")
            shell += '''
msg_ok() { printf 'OK:%s\\n' "$1"; }
msg_warn() { printf 'WARN:%s\\n' "$1"; }
consumer() {
'''
            shell += setup + "\n" + seam + "\n}\nconsumer\n"
            env = {"PATH": str(tmp / "bin"), "LANGUAGE": language,
                   "LANG_DIR": str(tmp / "lang"), "LC_ALL": "C"}
            result = subprocess.run(["/bin/bash", "--noprofile", "--norc", "-c", shell],
                                    env=env, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, "")
            return result.stdout.rstrip("\n")

    def test_vm_devices_zero_one_many_and_translation(self):
        seam = between(VM, '  if [[ "$assigned_count" -gt 0 ]]; then',
                       '  if [[ "${IOMMU_ALREADY_ACTIVE:-0}" == "1" ]]; then')
        key = "Completed. Devices added to VM {vmid}: {count}."
        translated = "Devices: {count} / VM {vmid} / done 100%."
        for count in (0, 1, 3):
            for vmid in (101, 987654):
                for language, catalog in self.locales(key, translated):
                    with self.subTest(count=count, vmid=vmid, language=language):
                        actual = self.render(seam, f"assigned_count={count}; SELECTED_VMID={vmid}",
                                             language, catalog)
                        if count == 0:
                            expected = "WARN:" + lookup(catalog, "No new Controller/NVMe entries were added.")
                        elif language == "xx":
                            expected = f"OK:Devices: {count} / VM {vmid} / done 100%."
                        elif language == "bad":
                            expected = f"OK:Completed. Devices added to VM {vmid}: {count}."
                        else:
                            expected = "OK:" + lookup(catalog, key).replace("{vmid}", str(vmid)).replace("{count}", str(count))
                        self.assertEqual(actual, expected)

    def test_vm_summary_counts_successful_new_assignments_only(self):
        seam = between(VM, '  local pci bdf assigned_count=0',
                       '  if [[ "${IOMMU_ALREADY_ACTIVE:-0}" == "1" ]]; then')
        for devices, expected_count in (([], 0), (["ok1"], 1),
                                        (["ok1", "ok2", "ok3"], 3),
                                        (["existing", "failed"], 0),
                                        (["existing", "ok1", "failed", "ok2"], 2)):
            with self.subTest(devices=devices):
                setup = 'SELECTED_CONTROLLER_PCIS=(' + ' '.join(devices) + ')\n'
                setup += '''SELECTED_VMID=101; hostpci_idx=0; LOG_FILE="$LANG_DIR/vm.log"
msg_info() { :; }
msg_error() { printf 'ERROR:%s\\n' "$1"; }
_pci_function_assigned_to_vm() { [[ "$1" == existing ]]; }
_pci_storage_display_name() { printf '%s' "$1"; }
qm() {
    [[ "$1 $2" == 'set 101' && "$3" == "--hostpci${hostpci_idx}" ]] || return 99
    [[ "$4" != 'failed,pcie=1' ]]
}
'''
                actual = self.render(seam, setup).splitlines()[-1]
                expected = (f"OK:Completed. Devices added to VM 101: {expected_count}." if expected_count
                            else "WARN:No new Controller/NVMe entries were added.")
                self.assertEqual(actual, expected)

    def test_custom_paths_zero_one_many_and_translation(self):
        seam = between(BACKUP, '        local -a paths=()', '        local choice')
        seam += '\n        printf "%s" "$preview"\n'
        key = "Custom paths currently saved: {count}."
        translated = "Saved 100%: {count} custom paths."
        suffix = "Custom paths are included in BOTH default and custom backup profiles."
        for count in (0, 1, 3):
            setup = 'hb_load_extra_paths() {\n'
            setup += ''.join(f"printf '%s\\n' '/fixture/path {i}'\n" for i in range(count))
            setup += ':;\n}\n'
            for language, catalog in self.locales(key, translated):
                with self.subTest(count=count, language=language):
                    actual = self.render(seam, setup, language, catalog)
                    colored_count = rf"\Zb\Z4{count}\Zn"
                    if count == 0:
                        expected = lookup(catalog, "You haven't added any custom paths yet.")
                    elif language == "xx":
                        expected = f"Saved 100%: {colored_count} custom paths."
                    elif language == "bad":
                        expected = f"Custom paths currently saved: {colored_count}."
                    else:
                        expected = lookup(catalog, key).replace("{count}", colored_count)
                    self.assertEqual(actual, expected + "\n\n" + lookup(catalog, suffix))

    def test_installed_packages_zero_one_many_success_and_failure(self):
        # Keep the actual nonempty guard and apt return-code consumer; omit
        # unrelated preview/cache/log setup. apt-get is a function stub only.
        guard = '            if (( ${#installable[@]} > 0 )); then\n'
        self.assertEqual((ROOT / BACKUP).read_text().count(guard), 1)
        seam = guard + between(BACKUP, '                DEBIAN_FRONTEND=noninteractive \\\n',
                               '            if (( ${#unknown[@]} > 0 )); then')
        key = "Packages installed: {count}."
        translated = "Done 100% / {count} installed packages."
        for count in (0, 1, 3):
            for status in (0, 100):
                for language, catalog in self.locales(key, translated):
                    with self.subTest(count=count, status=status, language=language):
                        setup = f'installable=({" ".join("pkg" + str(i) for i in range(count))}); apt_status={status}\n'
                        setup += '''apt_log="$LANG_DIR/apt.log"
apt-get() {
    [[ "$DEBIAN_FRONTEND" == noninteractive ]] || return 99
    [[ "$1 $2 $3 $4 $5 $6" == 'install -y -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold' ]] || return 99
    shift 6
    [[ "$*" == "${installable[*]}" ]] || return 99
    printf 'CALLED\\n' > "$LANG_DIR/calls"
    return "$apt_status"
}
'''
                        check_call = '\nif [[ -f "$LANG_DIR/calls" ]]; then printf "CALLED\\n"; fi\n'
                        actual = self.render(seam + check_call, setup, language, catalog)
                        if count == 0:
                            self.assertEqual(actual, "")
                        elif status:
                            prefix = "WARN:" + lookup(catalog, "apt-get exited") + " 100 — " + lookup(catalog, "see log:")
                            self.assertRegex(actual, "^" + re.escape(prefix) + r" .*/lang/apt.log\nCALLED$")
                        else:
                            message = (f"Done 100% / {count} installed packages." if language == "xx"
                                       else f"Packages installed: {count}." if language == "bad"
                                       else lookup(catalog, key).replace("{count}", str(count)))
                            self.assertEqual(actual, f"OK:{message}\nCALLED")


if __name__ == "__main__":
    unittest.main()
