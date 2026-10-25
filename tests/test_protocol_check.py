"""Base runs stay usable after amendments are logged. Run: python3 -m unittest discover -s tests -v"""
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from collusion import protocol_check as pc
from collusion.campaign import FORKS, load_base_list


def committed_protocol(commit):
    try:
        out = subprocess.run(["git", "show", f"{commit}:PROTOCOL.md"],
                             cwd=pc.PROTOCOL_PATH.parent, capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout


def write_census(folder: Path, protocol_sha256: str) -> Path:
    base = folder/"base"
    base.mkdir(parents=True)
    (base/"meta.json").write_text(json.dumps(
        {"kind": "base", "n_agents": 2, "protocol_sha256": protocol_sha256}))
    (base/"completion.json").write_text(json.dumps({"completed_rounds": max(FORKS)+15}))
    census = folder/"census.txt"
    census.write_text(f"COMPLETED: {base}\n")
    return census


class ProtocolCheckTests(unittest.TestCase):
    def test_windows_and_linux_checkouts_hash_the_same(self):
        lf = b"# PROTOCOL\n\nA10. Output cap raised.\n"
        self.assertEqual(pc.protocol_digest(lf), pc.protocol_digest(lf.replace(b"\n", b"\r\n")))

    def test_approved_digests_match_their_commits(self):
        for commit, (lf, crlf) in pc.APPROVED_PROTOCOL_VERSIONS.items():
            blob = committed_protocol(commit)
            if blob is None:
                self.skipTest("git history not available")
            normalized = blob.replace(b"\r\n", b"\n")
            self.assertEqual(lf, hashlib.sha256(normalized).hexdigest(), commit)
            self.assertEqual(crlf, hashlib.sha256(normalized.replace(b"\n", b"\r\n")).hexdigest(), commit)

    def test_current_file_accepted_raw_or_normalized(self):
        raw = pc.PROTOCOL_PATH.read_bytes()
        pc.check_recorded_protocol(hashlib.sha256(raw).hexdigest(), "test")
        pc.check_recorded_protocol(pc.current_protocol_digest(), "test")

    def test_approved_versions_survive_a_newly_logged_row(self):
        with tempfile.TemporaryDirectory() as folder:
            edited = Path(folder)/"PROTOCOL.md"
            edited.write_bytes(pc.PROTOCOL_PATH.read_bytes()+b"| Oct 25 | Pooled rho = 0.71 | | No |\n")
            with patch.object(pc, "PROTOCOL_PATH", edited):
                for lf, crlf in pc.APPROVED_PROTOCOL_VERSIONS.values():
                    pc.check_recorded_protocol(lf, "test")
                    pc.check_recorded_protocol(crlf, "test")

    def test_unknown_version_rejected_with_guidance(self):
        with self.assertRaisesRegex(ValueError, "APPROVED_PROTOCOL_VERSIONS"):
            pc.check_recorded_protocol("0"*64, "test")

    def test_base_list_accepts_older_approved_version_and_rejects_unknown(self):
        older_lf, older_crlf = pc.APPROVED_PROTOCOL_VERSIONS["6540f2f"]
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(len(load_base_list(write_census(Path(folder)/"lf", older_lf))), 1)
            self.assertEqual(len(load_base_list(write_census(Path(folder)/"crlf", older_crlf))), 1)
            with self.assertRaisesRegex(ValueError, "Protocol mismatch"):
                load_base_list(write_census(Path(folder)/"unknown", "0"*64))


if __name__ == "__main__":
    unittest.main()
