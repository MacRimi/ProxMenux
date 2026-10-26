"""Regression tests for Fastfetch config generation.

Run: python3 -m unittest discover -s tests -p test_fastfetch_config_generation.py -v
"""
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts/post_install/customizable_post_install.sh"
)


def extract_function(name: str) -> str:
    text = SCRIPT.read_text()
    match = re.search(rf"^{re.escape(name)}\(\) \{{\n.*?^\}}", text, re.M | re.S)
    if match is None:
        raise AssertionError(f"function {name} not found")
    return match.group(0)


class FastfetchConfigGeneration(unittest.TestCase):
    def test_script_does_not_use_retired_force_option(self):
        self.assertNotIn("--gen-config-force", SCRIPT.read_text())

    def run_case(self, fastfetch_exit: int = 0):
        function = extract_function("_generate_fastfetch_config")
        with tempfile.TemporaryDirectory(prefix="fastfetch-config-test-") as td:
            root = Path(td)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            target = root / "config.jsonc"
            target.write_text('{"modules":["preserved"]}\n')
            calls = root / "calls"
            fake = fake_bin / "fastfetch"
            fake.write_text(
                "#!/bin/bash\n"
                "printf '%s\\n' \"$*\" >> \"$CALLS\"\n"
                f"if (( {fastfetch_exit} != 0 )); then exit {fastfetch_exit}; fi\n"
                "[[ \"$1\" == --gen-config && -n \"$2\" ]] || exit 90\n"
                "[[ ! -e \"$2\" ]] || exit 91\n"
                "printf '%s\\n' '{\"modules\":[\"os\",\"kernel\"]}' > \"$2\"\n"
            )
            fake.chmod(0o755)
            q = shlex.quote
            harness = function + f"""
pmx_write_file() {{ cat > "$1"; }}
_generate_fastfetch_config {q(str(target))}
printf 'status=%s\n' "$?"
printf 'target=%s\n' "$(cat {q(str(target))})"
"""
            result = subprocess.run(
                ["/bin/bash", "--noprofile", "--norc"],
                input=harness,
                text=True,
                capture_output=True,
                timeout=10,
                env={
                    "PATH": f"{fake_bin}:/usr/bin:/bin",
                    "CALLS": str(calls),
                    "LC_ALL": "C",
                },
            )
            return result, target.read_text(), calls.read_text() if calls.exists() else ""

    def test_generates_to_temporary_path_before_replacing_target(self):
        result, target, calls = self.run_case()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("status=0\n", result.stdout)
        self.assertEqual(target, '{"modules":["os","kernel"]}\n')
        self.assertRegex(calls, r"^--gen-config /tmp/.+/config\.jsonc\n$")
        self.assertNotIn("--gen-config-force", calls)
        generated_config = Path(calls.removeprefix("--gen-config ").strip())
        self.assertFalse(generated_config.parent.exists())

    def test_generation_failure_preserves_existing_config(self):
        result, target, calls = self.run_case(fastfetch_exit=17)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("status=1\n", result.stdout)
        self.assertEqual(target, '{"modules":["preserved"]}\n')
        generated_config = Path(calls.removeprefix("--gen-config ").strip())
        self.assertFalse(generated_config.parent.exists())


if __name__ == "__main__":
    unittest.main()
