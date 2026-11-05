"""Render the real ZRAM CLI paths in isolated files with host effects stubbed."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
DETAILS = {
    "version": ("Cannot determine installed systemd-zram-generator version", "Nepodarilo sa zistiť verziu nainštalovaného balíka systemd-zram-generator"),
    "mismatch": ("Existing ZRAM profile is active but does not match its configuration", "Existujúci profil ZRAM je aktívny, ale nezodpovedá svojej konfigurácii"),
    "stop": ("Could not stop existing dev-zram0.swap", "Nepodarilo sa zastaviť existujúcu jednotku dev-zram0.swap"),
    "directory": ("Could not create ZRAM generator directory", "Nepodarilo sa vytvoriť adresár pre konfiguráciu generátora ZRAM"),
    "config": ("Could not write ZRAM generator configuration", "Nepodarilo sa zapísať konfiguráciu generátora ZRAM"),
    "marker": ("Could not write ZRAM package ownership state", "Nepodarilo sa zapísať údaj o tom, či balík ZRAM nainštaloval ProxMenux"),
    "start": ("Could not activate dev-zram0.swap", "Nepodarilo sa aktivovať jednotku dev-zram0.swap"),
    "verify": ("Active ZRAM algorithm, capacity or swap sources did not match the profile", "Algoritmus kompresie, veľkosť alebo zdroje swapu aktívnej ZRAM nezodpovedajú profilu"),
}
REFUSAL = "Another ZRAM generator configuration exists; refusing to overwrite it:"
REFUSAL_SK = "Existuje iná konfigurácia generátora ZRAM; neprepíše sa:"


def function(path, name):
    text = path.read_text()
    start = text.index(name + "() {")
    return text[start:text.index("\n}\n", start) + 3]


HARNESS = r'''
set -u
BASE_DIR="$FIXTURE/state"
LANG_DIR="$REPO/lang"
mkdir -p "$BASE_DIR" "$FIXTURE/etc/systemd/zram-generator.conf.d" "$FIXTURE/proc"
CONFIG="$FIXTURE/etc/systemd/zram-generator.conf.d/90-proxmenux.conf"
MARKER="$BASE_DIR/zram-swap.state"
printf 'Filename\tType\tSize\tUsed\tPriority\n' > "$FIXTURE/proc/swaps"
printf '/swapfile none swap sw 0 0\n' > "$FIXTURE/etc/fstab"
: > "$FIXTURE/calls"
record() { printf '%s\n' "$*" >> "$FIXTURE/calls"; }
pmx_journal_context() { :; }
msg_error() { printf '%s\n' "$*"; }
msg_success() { printf '%s\n' "$*"; }
register_tool() { record register "$@"; }
pmx_install_pkg() { record package-install; return 1; }
apt-get() { record apt "$@"; return 1; }
dpkg-query() {
    record dpkg-query
    case "$*" in
        *'${Status}'*) printf 'install ok installed\n';;
        *'${Version}'*) [[ "$CASE" == version ]] || printf '1.2.0-1\n';;
    esac
}
dpkg() { return 0; }
install() { record directory; [[ "$CASE" != directory ]]; }
pmx_write_file() {
    record write "$1"
    if [[ "$CASE" == config && "$1" == "$CONFIG" ]] ||
       [[ "$CASE" == marker && "$1" == "$MARKER" ]]; then
        cat >/dev/null
        return 1
    fi
    cat > "$1"
}
pmx_remove_file() { record remove "$1"; rm -f -- "$1"; }
pmx_record_uninstall() { record record-uninstall; }
swapoff() { record swapoff; return 0; }
systemctl() {
    record systemctl "$@"
    [[ "$CASE" != start || "$1" != start ]] &&
    [[ "$CASE" != stop || "$1" != stop ]]
}
source "$REPO/scripts/post_install/zram_profile_helpers.sh"
zram_profile_verify_active() { [[ "$CASE" != verify && "$CASE" != mismatch ]]; }
if [[ "$CASE" == mismatch || "$CASE" == stop ]]; then
    printf '# ProxMenux ZRAM profile\n[zram0]\nzram-size = ram / 10\n' > "$CONFIG"
    [[ "$CASE" != mismatch ]] || zram_render_generator_config true > "$CONFIG"
    printf 'installed_by_proxmenux=false\n' > "$MARKER"
    printf '/dev/zram0\tpartition\t3355443\t8\t32767\n' >> "$FIXTURE/proc/swaps"
fi
if [[ "$CASE" == foreign ]]; then
    printf '[zram1]\nzram-size = ram / 5\n' > "$FIXTURE/etc/systemd/zram-generator.conf"
fi
if [[ "$CASE" == unreadable ]]; then
    zram_foreign_generator_config() { return 2; }
fi
'''


class ZramLocalizationTests(unittest.TestCase):
    def test_missing_optional_translation_uses_original_english(self):
        with tempfile.TemporaryDirectory(prefix="zram-fallback-") as folder:
            (Path(folder) / 'xx.json').write_text('{}')
            script = function(ROOT / "scripts/utils.sh", "translate") + '\ntranslate "$1"\n'
            result = subprocess.run(["bash", "-c", script, "bash", DETAILS['version'][0]],
                                    text=True, capture_output=True, timeout=15,
                                    env={**os.environ, 'LANGUAGE': 'xx', 'LANG_DIR': folder})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), DETAILS['version'][0])

    def run_case(self, case, language="sk"):
        with tempfile.TemporaryDirectory(prefix="zram-i18n-") as folder:
            directory = Path(folder)
            installer = function(ROOT / "scripts/post_install/customizable_post_install.sh", "configure_zram_swap")
            installer = installer.replace("/etc/systemd/zram-generator.conf.d/90-proxmenux.conf", folder + "/etc/systemd/zram-generator.conf.d/90-proxmenux.conf")
            installer = installer.replace("/proc/swaps", folder + "/proc/swaps").replace("/etc/fstab", folder + "/etc/fstab")
            installer = installer.replace('zram_foreign_generator_config "$config"', 'zram_foreign_generator_config "$config" "$FIXTURE"')
            installer = installer.replace('zram_list_foreign_systemd_zram_units)', 'zram_list_foreign_systemd_zram_units "$FIXTURE")')
            script = HARNESS + function(ROOT / "scripts/utils.sh", "translate") + installer + "\nconfigure_zram_swap\n"
            result = subprocess.run(["bash", "-c", script], text=True, capture_output=True,
                                    env={**os.environ, "REPO": str(ROOT), "FIXTURE": folder, "CASE": case, "LANGUAGE": language}, timeout=15)
            calls = (directory / "calls").read_text().splitlines()
            files = {str(p.relative_to(directory)): p.read_text() for p in directory.rglob("*") if p.is_file()}
            return result, calls, files

    def test_all_activation_details_are_localized_and_english_is_preserved(self):
        for case, (english, slovak) in DETAILS.items():
            for language, expected in (("sk", slovak), ("en", english)):
                with self.subTest(case=case, language=language):
                    result, calls, files = self.run_case(case, language)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn(expected, result.stdout)
                    self.assertEqual(files["etc/fstab"], "/swapfile none swap sw 0 0\n")
                    if case in ("version", "mismatch"):
                        self.assertTrue(all(call == "dpkg-query" for call in calls), calls)
                    elif case == "stop":
                        self.assertEqual(files["state/zram-swap.state"], "installed_by_proxmenux=false\n")
                        self.assertIn("# ProxMenux ZRAM profile", files["etc/systemd/zram-generator.conf.d/90-proxmenux.conf"])
                    else:
                        self.assertNotIn("state/zram-swap.state", files)
                        self.assertNotIn("etc/systemd/zram-generator.conf.d/90-proxmenux.conf", files)
                    self.assertFalse(any(call.startswith(("apt ", "package-install", "register ")) for call in calls), calls)

    def test_foreign_generator_is_refused_in_both_languages_without_any_effect(self):
        for language, expected in (("sk", REFUSAL_SK), ("en", REFUSAL)):
            result, calls, files = self.run_case("foreign", language)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn(expected, result.stdout)
            self.assertIn("/etc/systemd/zram-generator.conf", result.stdout)
            self.assertEqual(calls, [])
            self.assertEqual(files["etc/systemd/zram-generator.conf"], "[zram1]\nzram-size = ram / 5\n")
            self.assertNotIn("state/zram-swap.state", files)
            self.assertNotIn("etc/systemd/zram-generator.conf.d/90-proxmenux.conf", files)
            self.assertEqual(files["etc/fstab"], "/swapfile none swap sw 0 0\n")
            self.assertEqual(files["proc/swaps"], "Filename\tType\tSize\tUsed\tPriority\n")

    def test_failed_inspection_is_not_mistaken_for_no_conflict(self):
        result, calls, files = self.run_case("unreadable")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Nie je možné skontrolovať existujúcu konfiguráciu generátora ZRAM", result.stdout)
        self.assertEqual(calls, [])
        self.assertNotIn("state/zram-swap.state", files)
        self.assertNotIn("etc/systemd/zram-generator.conf.d/90-proxmenux.conf", files)

    def test_uninstall_label_and_cancel_do_not_call_uninstall(self):
        for language, label in (("sk", "Profil swapu ZRAM"), ("en", "ZRAM swap profile")):
            with tempfile.TemporaryDirectory(prefix="zram-menu-") as folder:
                tools = Path(folder) / "tools.json"
                tools.write_text('{"zram_swap":true}')
                script = function(ROOT / "scripts/utils.sh", "translate")
                script += function(ROOT / "scripts/post_install/uninstall-tools.sh", "show_uninstall_menu")
                script += '\nensure_tools_json() { :; }; migrate_installed_tools() { :; }\nuninstall_zram_swap() { printf forbidden; return 1; }\ndialog() { printf "%s\\n" "$@" > "$MENU_CAPTURE"; return 1; }\nshow_uninstall_menu\n'
                result = subprocess.run(["bash", "-c", script], text=True, capture_output=True,
                                        env={**os.environ, "LANGUAGE": language, "LANG_DIR": str(ROOT / "lang"), "TOOLS_JSON": str(tools), "MENU_CAPTURE": folder + "/dialog.txt"}, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(label, (Path(folder) / "dialog.txt").read_text())
                self.assertNotIn("forbidden", result.stdout + result.stderr)
                self.assertEqual(json.loads(tools.read_text()), {"zram_swap": True})
