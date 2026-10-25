"""Verify provenance across *result-log-only* edits to the protocol file.

Original run metadata contains SHA-256 of the exact whole PROTOCOL.md file.
Adding a result to the two designated mutable rows in the deviations log
changes that whole-file hash without changing any scientific instruction.

This validator requires:
  1. the recorded whole-file hash is either current or reconstructible from
     a committed historical PROTOCOL.md Git blob; and
  2. old and current protocol bytes are identical after discarding ONLY
     the designated 'Model used:' and 'Pooled rho =' result rows.

It never accepts untracked protocol edits, changed amendments, changed
methodology, or a digest with no authenticated historical file. It NEVER
rewrites any stored metadata or forgives a mismatched saved experiment.

Run on the same Git checkout lineage used for the original pretest.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
from functools import lru_cache
from pathlib import Path

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MARKER = b"## Deviations log"
_ALLOWED_RESULT_PREFIXES = (b"Model used:", b"Pooled rho =")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def immutable_protocol_bytes(content: bytes) -> bytes:
    """Strip ONLY results lines from the deviations log, not scientific text."""
    lines = content.splitlines(keepends=True)
    positions = [
        i for i, line in enumerate(lines)
        if line.rstrip(b"\r\n") == _MARKER
    ]
    if len(positions) != 1:
        raise ValueError("Protocol lacks unique deviations-log marker")
    log_start = positions[0]
    retained = []
    result_row_counts = {prefix: 0 for prefix in _ALLOWED_RESULT_PREFIXES}
    for i, line in enumerate(lines):
        if i <= log_start:
            retained.append(line)
            continue
        text = line.strip()
        # Four-cell Markdown deviation table. Only the *second cell* identifies
        # the two permitted mutable rows. These are outcome records, not rules.
        if text.startswith(b"|") and text.endswith(b"|"):
            cells = [field.strip() for field in text.split(b"|")[1:-1]]
            if len(cells) == 4:
                for prefix in _ALLOWED_RESULT_PREFIXES:
                    if cells[1].startswith(prefix):
                        result_row_counts[prefix] += 1
                        if result_row_counts[prefix] > 1:
                            raise ValueError("Duplicate mutable protocol result row")
                        break
                else:
                    retained.append(line)
                    continue
                continue
        retained.append(line)
    if any(count != 1 for count in result_row_counts.values()):
        raise ValueError("Expected exactly one of each designated result row")
    return b"".join(retained)


@lru_cache(maxsize=256)
def _historical_immutable_digest(
    recorded_sha256: str, root_path: str
) -> str | None:
    root = Path(root_path)
    try:
        history = subprocess.run(
            ["git", "log", "--format=%H", "--", "PROTOCOL.md"],
            cwd=root, capture_output=True, check=True, timeout=10,
        ).stdout.decode("ascii", "strict").splitlines()
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None

    # Read and authenticate only a bounded number of actual committed blobs.
    for commit in history[:512]:
        try:
            historical = subprocess.run(
                ["git", "show", f"{commit}:PROTOCOL.md"],
                cwd=root, capture_output=True, check=True, timeout=10,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        if _sha256(historical) == recorded_sha256:
            try:
                return _sha256(immutable_protocol_bytes(historical))
            except ValueError:
                return None
    return None


def protocol_compatible(
    recorded_sha256: str, root: Path | str
) -> bool:
    """Preserve old SHA and prove only two designated result-log rows changed."""
    if not isinstance(recorded_sha256, str) or not _SHA256_RE.fullmatch(recorded_sha256):
        return False
    root = Path(root)
    try:
        current = (root / "PROTOCOL.md").read_bytes()
    except OSError:
        return False
    if _sha256(current) == recorded_sha256:
        return True
    try:
        current_immutable = _sha256(immutable_protocol_bytes(current))
    except ValueError:
        return False
    source_immutable = _historical_immutable_digest(
        recorded_sha256, str(root.resolve())
    )
    return source_immutable is not None and source_immutable == current_immutable


def require_compatible_protocol(
    recorded_sha256: str, root: Path | str, *, source: str
) -> None:
    if not protocol_compatible(recorded_sha256, root):
        raise ValueError(
            f"{source}: protocol hash not authenticated or scientific "
            "content changed. Original whole-file hash must appear in "
            "committed Git history; only the two specific outcome rows "
            "('Model used:', 'Pooled rho =') may have changed."
        )
