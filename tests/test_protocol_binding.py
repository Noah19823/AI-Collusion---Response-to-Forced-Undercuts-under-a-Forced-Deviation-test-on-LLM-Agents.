"""Regression tests for cryptographic compatibility across results-log-only edits."""
from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from collusion.protocol_binding import (
    immutable_protocol_bytes,
    protocol_compatible,
    require_compatible_protocol,
)

BEFORE = (
    "# Scientific protocol\n"
    "Method: scripted controls and 10% cuts.\n"
    "## Deviations log\n"
    "| Date | Change | Reason | Seen fork data? |\n"
    "| --- | --- | --- | --- |\n"
    "| Oct 25 | A8: thinking off | API support | No |\n"
    "| | Pooled rho = ___ | Estimated before forks | No |\n"
    "| | Model used: ___ | Pretest completed | No |\n"
)

AFTER = BEFORE.replace(
    "| | Model used: ___ | Pretest completed | No |",
    "| Oct 25 | Model used: claude-haiku-5-5, 50 rounds, pass. | Pretest completed | No |"
)

WITH_RHO = AFTER.replace(
    "| | Pooled rho = ___ | Estimated before forks | No |",
    "| Oct 25 | Pooled rho = 0.84 (CI pending) | Estimated before forks | No |"
)


class ProtocolHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(
            ["git", "init", "-q", str(self.root)], check=True
        )
        self.p = self.root / "PROTOCOL.md"
        self.p.write_text(BEFORE)
        self.original_hash = hashlib.sha256(BEFORE.encode()).hexdigest()
        self._commit()

    def _commit(self):
        subprocess.run(["git", "add", "PROTOCOL.md"],
                       cwd=self.root, check=True)
        subprocess.run([
            "git", "-c", "user.name=Fixture",
            "-c", "user.email=fixture@example.invalid",
            "commit", "--quiet", "-m", "fixture"
        ], cwd=self.root, check=True)

    def test_result_row_update_is_compatible(self):
        self.p.write_text(AFTER)
        self._commit()
        self.assertNotEqual(
            self.original_hash, hashlib.sha256(self.p.read_bytes()).hexdigest()
        )
        self.assertTrue(protocol_compatible(self.original_hash, self.root))
        require_compatible_protocol(
            self.original_hash, self.root, source="pretest fixture")
        self.p.write_text(WITH_RHO)
        self._commit()
        self.assertTrue(protocol_compatible(self.original_hash, self.root))

    def test_methodology_change_is_rejected(self):
        self.p.write_text(AFTER.replace(
            "10% cuts", "5% cuts"
        ))
        self._commit()
        self.assertFalse(protocol_compatible(self.original_hash, self.root))
        with self.assertRaisesRegex(ValueError, "scientific content changed"):
            require_compatible_protocol(
                self.original_hash, self.root, source="test fixture"
            )

    def test_methodology_hidden_inside_result_row_is_rejected(self):
        self.p.write_text(AFTER.replace('claude-haiku-5-5, 50 rounds, pass.',
                                       'methodology now uses 20% cuts; claude-haiku-5-5'))
        self._commit()
        self.assertFalse(protocol_compatible(self.original_hash,self.root))

    def test_actual_pretest_result_edit_passes_but_a10_and_retry_changes_do_not(self):
        root=Path(__file__).resolve().parents[1]
        before=subprocess.check_output(['git','show','f9b9abf:PROTOCOL.md'],cwd=root)
        after=subprocess.check_output(['git','show','6540f2f:PROTOCOL.md'],cwd=root)
        self.assertEqual(immutable_protocol_bytes(before),immutable_protocol_bytes(after))
        self.assertNotEqual(immutable_protocol_bytes(before),immutable_protocol_bytes((root/'PROTOCOL.md').read_bytes()))

    def test_undeclared_log_amendment_is_rejected(self):
        altered = AFTER.replace(
            "| Oct 25 | A8: thinking off | API support | No |",
            "| Oct 25 | A8: thinking off | API support | No |\n"
            "| Oct 25 | A9: change cut size | New hypothesis | No |"
        )
        self.p.write_text(altered)
        self._commit()
        self.assertFalse(protocol_compatible(self.original_hash, self.root))

    def test_untracked_protocol_version_cannot_be_authenticated(self):
        fake_hash = "0" * 64
        self.p.write_text(AFTER)
        self._commit()
        self.assertFalse(protocol_compatible(fake_hash, self.root))
        self.assertFalse(protocol_compatible("not-a-sha256", self.root))
        self.assertFalse(protocol_compatible(None, self.root))

    def test_same_file_hash_accepted_without_repository(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root / "PROTOCOL.md").write_text(BEFORE)
            self.assertTrue(protocol_compatible(self.original_hash, root))

    def test_nonresult_row_in_middle_of_protocol_is_preserved(self):
        disallowed = BEFORE.replace(
            "## Deviations log\n", "## Deviations log\n"
            "| Oct 25 | Model used: malicious early entry | skip | No |\n"
        )
        with self.assertRaisesRegex(ValueError, "Duplicate mutable|Unrecognized result-row"):
            immutable_protocol_bytes(disallowed.encode())

    def test_only_designated_four_cell_result_rows_are_skipped(self):
        self.assertEqual(
            immutable_protocol_bytes(BEFORE.encode()),
            immutable_protocol_bytes(WITH_RHO.encode())
        )
        bad = AFTER.replace(
            "Pooled rho = ___", "Pooled rho = ___ | Fifth cell"
        )
        with self.assertRaisesRegex(ValueError, "Expected exactly one"):
            immutable_protocol_bytes(bad.encode())


if __name__=="__main__":
    unittest.main()
