"""An addon of the Helper-Scripts runs where its catalog says it belongs: on
the Proxmox host, inside a container, or wherever the user chooses when it
can be both. Until this, every addon ran on the host."""

from pathlib import Path
import subprocess
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[3]
MENU = ROOT / "scripts/menus/menu_Helper_Scripts.sh"
PLAIN = ROOT / "scripts/menus/helper_plain_text.py"

# Only the functions under test are loaded, not the menu or its catalog.
PRELUDE = textwrap.dedent(f"""
    set -uo pipefail
    eval "$(sed -n '/^download_script() {{/,/^RETURN_TO_MAIN=false/p' '{MENU}' | sed '$d')"
    translate() {{ printf '%s' "$1"; }}
    clear() {{ :; }}
    dialog() {{ :; }}
    pmx_lxc_is_oci() {{ [[ "$1" == 100 ]]; }}
    MENU_HEIGHT=22; MENU_ROWS=14
""")


def bash(script):
    return subprocess.run(["bash", "-c", PRELUDE + textwrap.dedent(script)], capture_output=True, text=True)


class TargetChoiceTests(unittest.TestCase):
    def choice(self, kind, places):
        return bash(f'helper_target_choice {kind} "{places}"').stdout.strip()

    def test_an_addon_for_the_host_runs_on_the_host(self):
        self.assertEqual(self.choice("addon", "pve"), "host")

    def test_an_addon_for_containers_runs_in_one(self):
        self.assertEqual(self.choice("addon", "lxc vm"), "lxc")
        self.assertEqual(self.choice("addon", "lxc"), "lxc")

    def test_an_addon_for_both_asks_where(self):
        self.assertEqual(self.choice("addon", "pve vm lxc"), "ask")
        self.assertEqual(self.choice("addon", ""), "ask")

    def test_what_is_not_an_addon_runs_on_the_host(self):
        # A script that creates a container or a VM belongs on the host,
        # whatever the catalog lists for the application it installs.
        self.assertEqual(self.choice("lxc", "lxc"), "host")
        self.assertEqual(self.choice("vm", "vm"), "host")
        self.assertEqual(self.choice("pve", "pve"), "host")


class ContainerListTests(unittest.TestCase):
    def test_oci_containers_are_left_out_and_a_lock_is_shown(self):
        result = bash(r"""
            pct() { printf 'VMID Status Lock Name\n100 running chromium\n109 running ordinary\n110 stopped stopped-one\n112 stopped backup locked-one\n'; }
            helper_lxc_rows
        """)
        self.assertEqual(result.stdout,
                         "109\tordinary · running\n110\tstopped-one · stopped\n112\tlocked-one · stopped · backup\n")


class RunTests(unittest.TestCase):
    def test_the_script_runs_on_the_host_or_inside_the_container_chosen(self):
        result = bash(r"""
            curl() { printf 'printf on-host'; }
            pct() { [[ "$1" == exec && "$2" == 109 && "$3" == --keep-env && "$4" == 0 && "$5" == -- ]] && printf 'in-lxc:%s' "${*: -1}"; }
            HELPER_LXC_TARGET=''; download_script https://example.invalid/a; echo
            HELPER_LXC_TARGET=109; download_script https://example.invalid/a; echo
        """)
        self.assertEqual(result.stdout, "on-host\nin-lxc:printf on-host\n")

    def test_a_failed_or_empty_download_runs_nothing(self):
        result = bash(r"""
            bash() { echo RAN; }
            pct() { echo RAN; }
            HELPER_LXC_TARGET=109
            curl() { return 22; }; download_script https://example.invalid/a && echo UNEXPECTED
            curl() { printf '  \n'; }; download_script https://example.invalid/a && echo UNEXPECTED
            echo done
        """)
        self.assertEqual(result.stdout, "done\n")

    def test_cancelling_the_choice_leaves_no_target(self):
        result = bash(r"""
            dialog() { return 1; }
            select_helper_target Test ask && echo UNEXPECTED
            printf '[%s]\n' "$HELPER_LXC_TARGET"
        """)
        self.assertEqual(result.stdout, "[]\n")

    def test_the_host_needs_no_question(self):
        result = bash(r"""
            dialog() { echo ASKED; return 1; }
            select_helper_target Test host && printf 'ok[%s]\n' "$HELPER_LXC_TARGET"
        """)
        self.assertEqual(result.stdout, "ok[]\n")


class PlainTextTests(unittest.TestCase):
    def test_html_becomes_text_and_commands_are_kept(self):
        result = subprocess.run(["python3", str(PLAIN)], capture_output=True, text=True,
                                input="<p>Run <code>ls -la &amp;&amp; pwd</code></p><ul><li>one</li><li>two</li></ul>")
        self.assertEqual(result.stdout, "Run ls -la && pwd\n\n• one\n\n• two")


if __name__ == "__main__":
    unittest.main()
