# amendment 1 vs the code

quick check that the code matches A1-A6.

| amendment | where |
| --- | --- |
| A1 pretest target 1.802 | market.py, runner.py |
| A2 P3 compares conclusions not numbers | amendment_analysis.py |
| A3 rho from 2dp shown prices, fixed grid if not identified | rho.py, amendment_analysis.py (grid 0, .25, .5, .75, .9, .95) |
| A4 negative score != proof of intent | wording in analysis output |
| A5 G_H^enforced holds cutter prices fixed | analysis.py |
| A6 drop upward copy + 2x2 | campaign.py skips upward unless --include-up. 108 branches not 120 |

run it:

    python3 -m collusion.amendment_analysis --campaign logs/campaign_ID --resamples 10000 --output results/amendment_analysis.json

- each base run = one bootstrap cluster, rho re-fit in every resample
- if rho isn't identified it reports the fixed grid only, no main conclusion
- noise floor (95th pct of no-cut vs second no-cut) is descriptive, not a significance test
