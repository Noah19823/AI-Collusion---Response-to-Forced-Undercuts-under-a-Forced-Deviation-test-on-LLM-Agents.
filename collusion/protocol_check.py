"""Which PROTOCOL.md versions a live run may have been recorded under.

Every run stores the sha256 of PROTOCOL.md in its meta.json. Forks and the rho
estimate used to require that hash to equal the current file, so logging any
amendment or deviations-log row (including the pooled-rho row the protocol asks
for before forks) rejected every base run already made. A recorded hash is now
accepted if it is the current file's or one of the approved versions below.

Hashes are taken over LF line endings, so a Windows checkout (core.autocrlf=true)
and a Linux or macOS checkout of the same commit agree. Runs recorded before this
change hashed the raw bytes, so each approved version lists its LF and CRLF digest.
"""
from __future__ import annotations
import hashlib
from pathlib import Path

PROTOCOL_PATH = Path(__file__).resolve().parents[1]/"PROTOCOL.md"

# PROTOCOL.md versions from A8 (live call shape fixed, before any live output) on.
# They differ only by amendment A10 and deviations-log rows, all logged before any
# fork data; A10 says which base runs are kept. Add a version only if it changes
# nothing about how runs are made. Otherwise runs under it have to be redone.
APPROVED_PROTOCOL_VERSIONS = {
    # commit: (LF sha256, CRLF sha256)
    "f9b9abf": ("b140dbf101eadaa015d717957caf5fc5ff05c810af9acd02cfbb1a5d9c5fb720",
                "bc2bced328ef1d9083edd25a521a02e02789badc3578288064cc574ad269571e"),  # A8 logged
    "6540f2f": ("88218f559ab83a3219ae55240a131b655d71b3f4a5ffa57598b3ebb4c7e34d75",
                "b9925ecc7e596c796ea05b7ac03a6c6c1193d82e2f3d582d3f943da43cb8858e"),  # pretest pass logged
    "8de1b46": ("2252dd902980b8d3f1c8cf5cdc1bc9940e5fbc28355ca1056af8342551f18d68",
                "f9df4733ed5e44362a595a52011c1af174a94748c2a58ac18ca97ee5b8b9ea32"),  # A10 output cap
    "3d93081": ("9b2861490161fe57657721c167e8b68aa254b11b983ba41960d0beff1370967c",
                "df1b8fddad0b34ab05be4edfdb66db6b119197d2a18c782556a8b72e16a39253"),  # rate-limit row
}

def protocol_digest(raw: bytes) -> str:
    """sha256 of PROTOCOL.md content with line endings normalized to LF."""
    return hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()

def current_protocol_digest() -> str:
    return protocol_digest(PROTOCOL_PATH.read_bytes())

def _current_digests() -> set[str]:
    # Raw too, for runs recorded before hashes were normalized.
    raw = PROTOCOL_PATH.read_bytes()
    return {hashlib.sha256(raw).hexdigest(), protocol_digest(raw)}

def is_current(recorded: str) -> bool:
    return recorded in _current_digests()

def check_recorded_protocol(recorded: str, where: str) -> None:
    accepted = _current_digests()
    for lf, crlf in APPROVED_PROTOCOL_VERSIONS.values():
        accepted.update((lf, crlf))
    if recorded not in accepted:
        raise ValueError(
            f"Protocol mismatch in {where}: recorded PROTOCOL.md hash {recorded[:12]} is "
            "neither the current file nor an approved version. If PROTOCOL.md changed only "
            "by a logged amendment, add that version to APPROVED_PROTOCOL_VERSIONS in "
            "collusion/protocol_check.py; otherwise redo the run.")
