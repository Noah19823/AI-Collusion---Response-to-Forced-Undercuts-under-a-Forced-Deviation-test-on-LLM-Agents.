# PREDICTIONS: Calling the Bluff

Updated October 24, before any fork data. The full definitions are in PROTOCOL.md. Predictions that fail get reported as failed. Anything added after seeing data is labeled that way.

## Confirmatory

**P1 (scripted agents).** The one-period test classifies scripted punishers with rho of 0.5 or more as non-punishers. The dynamic baseline classifies every scripted agent correctly, punishers below zero and non-punishers within their interval of zero, for both a one-period cut and a persisting cut. The static sum fails when the cut persists.

**P2.** The LLM's estimated rho is at least 0.5. If it is lower, the one-period test should work fine for this model, and we say that.

**P3.** On the LLM forks, the dynamic measure is more negative than the one-period test, meaning the one-period test understates punishment. We do not predict whether the LLM punishes.

**P4.** If the dynamic measure shows punishment, the part of the cutter's loss caused by the rival (G_H^enforced) is below zero. If it does not, G_H^enforced is about zero.

## Amendment 1 (October 25, before any live model data)

P3 above is replaced, because a sticky agent that doesn't punish already scores higher on the one-period test (+0.094) than on the dynamic measure (0), so the old P3 could come out true with no punishment.

**P3 (amended).** If rho is identified and is at least 0.5, P3 holds if the dynamic measure says the LLM punishes (Section 7 decision rule) and the one-period test does not (its 95% interval is not below zero). If both reach the same conclusion, P3 fails. We also report how often the two disagree fork by fork.

If rho can't be identified from the prices the agent was shown, P2 and P3 aren't tested. We report the dynamic measure at rho = 0, 0.25, 0.5, 0.75, 0.9 and 0.95 instead. P1 and P4 are unchanged. A negative dynamic score is reported as pricing below the sticky, myopic non-punishing baseline, not as proof of punishment. See Amendment 1 in PROTOCOL.md.

Under A6 (scope reduced for time), the upward-copy check below and the exploratory 2 × 2 prediction are not tested.

## Validity checks

The second sham sets the noise floor that the cut-versus-sham gap is judged against. The upward copy shows no cut below the non-punishing baseline after a forced raise.

## Exploratory

In the threat-by-punishment 2 × 2, rivals that wrote a threat before the cut punish more often than rivals that did not.
