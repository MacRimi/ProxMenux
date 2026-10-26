"""The installer must not need to rewrite files supplied by its caller."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "remote" / "install_oci.sh"


class CanonicalInstallerInputTests(unittest.TestCase):
    def test_persisted_contract_uses_private_copies_not_caller_files(self):
        installer = INSTALLER.read_text(encoding="utf-8")

        self.assertIn('mktemp -d "/var/tmp/proxmenux-oci-inputs-${VMID}.XXXXXX"', installer)
        self.assertIn('TEMPLATE_FILE="${CANONICAL_INPUT_DIR}/template.json"', installer)
        self.assertIn('DEPLOYMENT_FILE="${CANONICAL_INPUT_DIR}/deployment.json"', installer)
        self.assertIn('cleanup_canonical_inputs || true', installer)
        self.assertNotIn('jq \'.template\' "$INSTANCE_CONTRACT" >"$TEMPLATE_FILE"', installer)
        self.assertNotIn('jq \'.deployment\' "$INSTANCE_CONTRACT" >"$DEPLOYMENT_FILE"', installer)
