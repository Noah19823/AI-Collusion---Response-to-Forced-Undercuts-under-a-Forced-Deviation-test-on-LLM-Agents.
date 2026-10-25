"""Fail-closed comparison with authenticated, result-only protocol history.

Keep every original whole-file digest. Only the two declared result rows may
vary, and only in the bounded result syntax below. New prose/amendment rows,
including A10 and retry changes, are scientific changes, not result updates.
Exact byte identity needs no Git history; historical compatibility does.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

_HASH = re.compile(r"[0-9a-f]{64}")
_NUMBER = r"(?:0(?:\.\d+)?|1(?:\.0+)?)"
_MODEL = r"[A-Za-z0-9][A-Za-z0-9._/:-]*"
_DATE = re.compile(r"(?:|[A-Z][a-z]{2} \d{1,2}|\d{4}-\d{2}-\d{2})")
_MODEL_RESULT = re.compile(
    rf"Model used: (?:___|{_MODEL}, \d+ rounds, (?:pass|fail)\.|"
    rf"{_MODEL} \(thinking off, effort medium\)\. Pretest (?:passed|failed): "
    r"\d+ rounds, last-10 mean price \d+(?:\.\d+)? against the one-product "
    r"monopoly price \d+(?:\.\d+)? \(run pretest_[0-9a-f]+, "
    r"rounds sha256 [0-9a-f]+(?:…|\.\.\.)?\)\.)"
)
_RHO_RESULT = re.compile(
    rf"Pooled rho = (?:___|{_NUMBER}(?: \(CI pending\)| "
    rf"\(95% CI \[{_NUMBER}, {_NUMBER}\]\))?|ABSTAIN_RHO_NOT_IDENTIFIABLE)"
)


def immutable_protocol_bytes(content: bytes) -> bytes:
    lines=content.decode('utf-8').splitlines(keepends=True)
    markers=[i for i,line in enumerate(lines) if line.rstrip('\r\n')=='## Deviations log']
    if len(markers)!=1:
        raise ValueError('Protocol lacks unique deviations-log marker')
    counts={'Model used:':0,'Pooled rho =':0}
    retained=[]
    for i,line in enumerate(lines):
        cells=[v.strip() for v in line.strip().split('|')[1:-1]]
        prefix=next((p for p in counts if len(cells)==4 and cells[1].startswith(p)),None)
        if i<=markers[0] or prefix is None:
            retained.append(line)
            continue
        counts[prefix]+=1
        if counts[prefix]>1:
            raise ValueError('Duplicate mutable protocol result row')
        valid_date=_DATE.fullmatch(cells[0]) is not None
        if prefix=='Model used:':
            valid=(_MODEL_RESULT.fullmatch(cells[1]) is not None and
                   cells[2] in ('Pretest completed','After API key and pretest',
                                'Passed monopoly pretest','Failed monopoly pretest') and
                   cells[3] in ('No','No fork data. Pretest output only.'))
        else:
            valid=(_RHO_RESULT.fullmatch(cells[1]) is not None and
                   cells[2] in ('Estimated before forks','Estimated from base runs before forks') and
                   cells[3]=='No')
        if not valid_date or not valid:
            raise ValueError('Unrecognized result-row prose; methodology cannot be hidden in a result row')
        retained.append(f'| RESULT ONLY: {prefix} |\n')
    if any(count!=1 for count in counts.values()):
        raise ValueError('Expected exactly one of each designated result row')
    return ''.join(retained).encode('utf-8')


def protocol_compatible(recorded_sha256: str, root: Path | str) -> bool:
    if not isinstance(recorded_sha256,str) or not _HASH.fullmatch(recorded_sha256):
        return False
    root=Path(root)
    try:
        current=(root/'PROTOCOL.md').read_bytes()
        if hashlib.sha256(current).hexdigest()==recorded_sha256:
            return True
        expected=immutable_protocol_bytes(current)
        history=subprocess.run(['git','log','--format=%H','--','PROTOCOL.md'],
            cwd=root,capture_output=True,check=True,timeout=10).stdout.decode('ascii').splitlines()
        for commit in history[:512]:
            old=subprocess.run(['git','show',f'{commit}:PROTOCOL.md'],cwd=root,
                capture_output=True,check=True,timeout=10).stdout
            if hashlib.sha256(old).hexdigest()==recorded_sha256:
                return immutable_protocol_bytes(old)==expected
    except (OSError,ValueError,UnicodeError,subprocess.SubprocessError):
        return False
    return False


def require_compatible_protocol(recorded_sha256: str, root: Path | str, *, source: str) -> None:
    if not protocol_compatible(recorded_sha256,root):
        raise ValueError(f'{source}: protocol hash not authenticated or scientific content changed; '
                         'no transition is authorized by a result-only update')
