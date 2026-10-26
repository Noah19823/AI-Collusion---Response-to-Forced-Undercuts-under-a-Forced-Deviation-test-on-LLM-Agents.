# offline checks (oct 25, before any live runs)

ran everything on mock / scripted agents first. no api calls.

- benchmarks: nash 1.4729, one-product monopoly 1.8020, joint monopoly 1.9250, BR(1.92) = 1.6599
- scripted grid with noise: 24 cells x 50 reps, all classified right (inside the scripted family, so this only shows the measure works when its assumption holds)
- mock pipeline: 12 base runs x 150 periods, 48 cut/no-cut fork pairs + extra no-cut copies. branch checks all pass
- tests for output parsing, market math, branch hashes, tamper detection

## stuff we caught

- rho has to be fit on the 2-decimal prices the agent actually sees. fitting on hidden full-precision prices gave a fake rho (~0.004). on mock data the visible prices barely move so rho isn't identifiable there -> abstain
- pretest target was wrong in the first protocol (1.92 is two-product monopoly, should be 1.80)
- old P3 compared a 15-period number to a 1-period number, which a non-punisher can satisfy. rewritten in amendment 1
- negative PI_dyn = below the sticky best-response baseline, not proof of punishment. a forecasting agent can also score negative
- G_H holds the cutter's later prices fixed, so it's the direct effect only

all of this went into amendment 1 in PROTOCOL.md before live data.
