# Pretest-to-baseline protocol hash repair — October 25, 2026

**Purpose:** Preserve original scientific commitments and the original run
hashes when an append-only *results ledger* in PROTOCOL.md is filled in
after a completed run.

## Evidence

The successful pretest was logged on main as commit 6540f2f after running.
That commit edits one existing deviations-log row to state that the selected
model passed the monopoly pretest.

The exact PROTOCOL.md hashes across that single documented event are:

- Before the result was logged (commit f9b9abf):
  b140dbf101eadaa015d717957caf5fc5ff05c810af9acd02cfbb1a5d9c5fb720
- After the result was logged (commit 6540f2f):
  88218f559ab83a3219ae55240a131b655d71b3f4a5ffa57598b3ebb4c7e34d75

The runner formerly refused *any* pretest whose recorded full-document
protocol hash differed from the then-current PROTOCOL.md, which would
reject a legitimate pretest solely because its **result** had been logged.
The same issue would recur after the pooled rho result was written before
running forks.

## Repair

Added collusion/protocol_binding.py and used it at all three gates:

- Qualified solo pretest -> live duopoly baselines.
- Complete duopoly bases -> matched 48-fork campaign.
- Complete duopoly base -> individual fork continuation.

The validator **keeps** the original SHA-256 binding. It accepts a historical
SHA-256 only if the exact source PROTOCOL.md bytes can be recovered from a
committed Git object in the same repository. It then compares the former and
current protocol **byte-for-byte**, except for exactly one of each of the
two designated results-ledger rows in the deviations-log table:
"Model used:" and "Pooled rho =".

Changes to the scientific protocol, amendment text, experiment parameters,
other deviations-log entries, headers, or any other byte remain fatal.
Missing historical Git objects or unverifiable/uncommitted documents also
fail closed. No original run artifacts, receipt SHA-256 strings, frozen
metadata or source logs are rewritten.

**For Basel:** verify pretest_<ID>/meta.json contains the expected model
and the original recorded protocol hash, and verify
sha256sum/shasum of rounds.jsonl equals completion.json.rounds_sha256.
A legacy source SHA can be admitted only after the above Git-history and
immutable-content checks pass. If the source SHA is not in Git history,
do not invent or overwrite it: investigate and, if needed, rerun the pretest.

## Regression evidence

- All existing tests pass.
- New tests cover result-log-only compatibility, pooled rho logging,
  legitimate exact-file match, unknown/forged digest rejection,
  rejection of any amended method or additional results-ledger rows,
  and malformed table structure.
- The pretest-era committed PROTOCOL.md hash above is demonstrably
  compatible with the currently committed protocol when the validator
  is executed in the original Git checkout.
- The entire suite of 54 tests passes offline.

**Not an empirical finding:** This change makes no external model calls,
does not increase spending, does not validate the reported pretest's raw
tokens/outputs, and does not change P1-P4 or the experimental design.
