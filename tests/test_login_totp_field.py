"""Bitwarden skips a 2FA field whose siblings mention a backup code (issue #570)."""
from pathlib import Path
import unittest

SOURCE = (Path(__file__).resolve().parents[1] / "AppImage/components/login.tsx").read_text()


class LoginTotpFieldTests(unittest.TestCase):
    def test_the_backup_code_hint_is_not_a_sibling_of_the_field(self):
        field = SOURCE.index('id="totp-code"')
        hint = SOURCE.index('t("login.backupCodeHint")')
        self.assertIn("</div>", SOURCE[field:hint])


if __name__ == "__main__":
    unittest.main()
