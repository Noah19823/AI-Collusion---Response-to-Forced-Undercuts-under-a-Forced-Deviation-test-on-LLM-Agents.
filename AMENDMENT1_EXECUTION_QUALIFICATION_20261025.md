# Amendment 1 — Implementation Qualification (October 25, 2026)

This is an independent implementation-to-protocol cross-check for the Apart Research sprint. It does not change the team's frozen original protocol or preregistered predictions. No real LLM scientific results are claimed.

Reviewed against upstream commit 1ef554595f7e61d594f014957a3af8fedd37ff7c (Amendment 1, A1–A6).

## Implementation trace

| Amendment | Software disposition |
| --- | --- |
| A1: Solo monopoly target is 1.802, not 1.925 | Already implemented in collusion/market.py and collusion/runner.py; checked |
| A2: P3 compares conclusions, not unlike index magnitudes | Implemented in collusion/amendment_analysis.py with run-level intervals and distinct test decisions |
| A3: Estimate rho from 2dp agent-visible prices or use fixed sensitivity grid | Implemented predefined grid: 0, 0.25, 0.5, 0.75, 0.9, 0.95, with abstention |
| A4: Negative dynamic residual does not prove intent | Analysis reports deviation from restricted sticky-myopic best-response null, not motive |
| A5: Direct profit contrast holds cutter's own future prices fixed | Existing controlled contrast retained; no new causal claim |
| A6: Drop upward and two-coder checks to save time | Campaign already omits them; fixed its seal's branch count to 108, not 120, without upward copies |

## Use the amended analysis

    python3 -m collusion.amendment_analysis --campaign logs/campaign_ID --resamples 10000 --output logs/report_ID.json

The reader verifies raw evidence and the saved experiment plan, rejects duplicate plan rows and incorrect branch counts, checks simultaneous decisions and exact second-sham starting states, and computes both one-period and dynamic statistics from the primitive pricing histories.

Each of 12 independent base runs is treated as one bootstrap cluster. Rho is re-estimated inside each bootstrap draw. The dynamic conclusion is compared against the one-period conclusion, not against the raw one-period index magnitude.

If rho cannot be identified, no primary fitted-rho conclusion is issued. All six fixed-rho sensitivity results remain visible (with confidence intervals, descriptive sham-noise floor and sign-disagreement counts). Mock results can never qualify as real-model conclusions.

For identifiable rho, a numerical 11-point sensitivity scan over the estimated 95% rho range accompanies the primary test. A negative result is scoped to the specific restricted baseline. The 12-sham 95th-percentile noise floor is a descriptive heuristic, not a calibrated family-wise significance test. The discrete rho scan does not guarantee a claim for every point in a continuum.

## What passed offline

- End-to-end integration on the amended code: 12 simulated 135-period two-agent base histories, 48 matched fork points, and exactly 108 branches (48 cut, 48 sham, 12 second sham).
- Mathematical tests of cumulative dynamic index equivalence with its recursive definition.
- Negative and positive classification decision fixtures, including an adversarial fixture explicitly labelled synthetic.
- Local Anthropic request and response contract tests using an HTTP mock transport. This never contacted a provider.
- All automated tests pass; no API credits used.

## Next scientific gates

1. The current BRIEF.md still describes the upward and two-coder controls that Amendment A6 dropped. The paper owner should reconcile the final manuscript without silently rewriting preregistration.
2. Obtain permission for a bounded actual model API budget and validate model access with a tiny paid smoke test before larger execution. The updated reduced full plan is approximately 6,890 model decisions before retries: 50 solo pretest, 3,600 baseline, 2,880 matched cut/sham continuations, and 360 extra second-sham continuations. This is not a cost or duration estimate.
3. Qualify the solo pretest against the correct 1.802 optimum. Then inspect the twelve genuine high-price baseline histories and variation actually visible in the prompts.
4. Freeze and execute the matched fork plan, recompute all measures independently, assess sensitivity/noise, and label results as supported, unsupported or inconclusive.
5. Write figures and the final abstract using actual experiment results. Synthetic tests alone establish properties of scripted families, not real-world LLM punishment.

No real LLM experiment was conducted in this change, no API credentials were copied, and no unrelated projects were added to the repository.
