# Calling the Bluff — Independent Execution Handoff (25 October 2026)

**Scope:** Independent offline-first implementation of the team's preregistered protocol. Scientific amendments are documented here; historical PROTOCOL.md and PREDICTIONS.md are not silently rewritten.

- Upstream baseline commit: b210bfb0f8499de9d9710424d7570808e23a885a
- Workstation: /home/x3klr007/projects/AI_Collusion_Sprint_20261025/Calling_the_Bluff
- Local branch: independent-execution-20261025
- Upstream repository unchanged. No real Anthropic, OpenAI or other paid model calls. No model credentials copied or read.
- All run outputs explicitly identify their provider; mock outputs are synthetic integration evidence, not LLM collusion data.

## Actually executed

1. Independently recomputed seven economic benchmarks. Nash 1.47292666003, one-product monopoly 1.80198500789, two-product joint monopoly 1.92498091902, BR(1.92) 1.65990850258.
2. Reproduced seven previously reported deterministic scripted tests.
3. Ran 24 noisy scripted-agent cells with 50 replicates each (1,200 total). 24/24 classification cells pass *within the constructed policy family*.
4. Ran 12 synthetic 150-period two-agent baselines using a local mock provider, no paid API.
5. Ran 48 synthetic cut/sham fork pairs plus 12 additional no-cut and 12 upward controls; 120 branches. All 48 paired branch checks pass.
6. Added primitive-log recomputation for PI_one, PI_static, PI_dynamic, G_H, and the direct price contribution to cutter profit.
7. Added 10,000-replicate-capable run-cluster bootstrap logic that re-estimates rho in each resample, with explicit abstention when rho cannot be identified.
8. Added an out-of-model nonpunitive predictive-memory policy: 27/27 constructed downward interventions score negative PI_dyn while 27/27 upward interventions score positive PI_dyn. This is a known mechanism-identification counterexample, not a result on Claude.
9. Built and ran tests for output validation, market scale, branch hashes, provenance, and tamper detection.

## Forensic evidence on workstation

- logs/offline_scripted_65b11065c9ff/grid.csv and completion.json
- logs/full_mock_census.txt (twelve mock baseline paths)
- logs/campaign_8eca4197de97/plan.json
- logs/campaign_8eca4197de97/manifest.jsonl
- logs/campaign_8eca4197de97/completion.json
- logs/campaign_8eca4197de97/descriptive_summary_CORRECTED.json — authoritative corrected summary
- logs/campaign_8eca4197de97/descriptive_summary.json — superseded earlier invalid descriptive computation; deliberately preserved

## Important correction and abstention

The original mock output rounding exposes a crucial issue: the Fish-style prompt shows past prices to only two decimals. In stable mock histories, all visible prices remain almost constant. A prior regression using hidden full-precision prices yielded rho approximately 0.0041 and suggested PI_dyn approximately +0.1174. That was inappropriate: the agent never observed the sub-cent variations.

The corrected estimator uses only prices actually visible in prompts and finds rho unidentifiable. Result: ABSTAIN_RHO_NOT_IDENTIFIABLE. A corrected analysis file was emitted without overwriting earlier evidence. No punishment or nonpunishment claim can follow from this mock campaign.

## Scientific gates for the real sprint

P0 — Protocol Section 6 incorrectly treats 1.92 (two-product joint monopoly) as the solo-agent target. Real one-product monopoly benchmark is about 1.802.

P0 — P3 compares a 15-period index numerically with a one-period index. A nonpunisher (rho=.92, delta=0) gives PI_one=+0.094 and PI_dyn=0, hence satisfies the purported missed-punishment inequality. This comparison alone cannot validate the hypothesis.

P0 — The dynamic null requires identifiable persistence from agent-visible data. If the estimate is near-singular or sensitive, abstain or report sensitivity; never silently substitute a favorite coefficient.

P1 — Negative PI_dyn means pricing below the specified sticky-myopic best-response null, not proof of intent or cartel enforcement. Forecasting nonpunishers can pass the proposed upward perturbation control and still score negative.

P1 — G_H includes the immediate gain. Substituting nonpunitive B prices while holding the cutter's actual future price path fixed measures a controlled direct profit contrast, not all behavioral counterfactual effects.

P1 — The Anthropic adapter has not been tested against a live provider. Actual stochastic drift, rate limits, prompt adherence, and price parsing remain unqualified. The source simultaneous actions and notes are preserved at t before any price intervention.

P1 — Record all resulting protocol changes as independently timed amendments before live data. Do not silently rewrite preregistration history.

## Gate ledger

- Economics: PASS (offline)
- Known-family scripted controls: PASS (24/24, offline)
- Alternative nonpunitive mechanism: COUNTEREXAMPLE (27 cases, synthetic)
- Baseline runner and 48 matched-fork pipeline: PASS (mock integration)
- Primitive-log integrity/tamper detection: PASS
- Persistence estimation on mock histories: ABSTAIN, unidentifiable
- Actual Haiku results: NOT RUN (API key absent from environment)
- Model-level punishment conclusion: NOT QUALIFIED

**Adjudication: Conditional GO for bounded live adapter smoke and subsequent pretest once the scientific corrections and budget are approved; no valid empirical LLM collusion claim yet.**

This contribution is confined to the sprint experiment; generated raw output remains local, and the upstream branch was not modified.
