# running it

everything from the repo root. real model calls need `--execute-paid`, nothing paid runs without it.

## offline (free)

    python3 -m pytest -q
    python3 -m collusion.runner benchmark
    python3 -m collusion.runner scripted
    python3 -m collusion.runner base --provider mock --rounds 8 --runs 1

## live (haiku 5.5)

set the key in your own terminal only (never paste it anywhere):

    export ANTHROPIC_API_KEY="$(pbpaste)"

1. pretest, one agent alone. completion.json should say `pretest_near_one_product_monopoly: true`

        python -m collusion.runner pretest --provider anthropic --model claude-haiku-5-5 --rounds 50 --execute-paid

2. 12 base runs (can split across terminals with --runs / --seed)

        python -m collusion.runner base --provider anthropic --model claude-haiku-5-5 --rounds 150 --runs 12 --pretest-dir logs/pretest_ID --execute-paid | tee -a logs/live_base_census.txt

3. rho from the base runs (log it in PROTOCOL.md before forking)

        python -m collusion.rho --base-list logs/live_base_census.txt

4. forks (48 fork points, cut + no-cut, 12 second no-cut). `--resume logs/campaign_ID` if it crashes

        python -m collusion.campaign --base-list logs/live_base_census.txt --provider anthropic --model claude-haiku-5-5 --concurrency 3 --execute-paid

5. analysis

        python -m collusion.amendment_analysis --campaign logs/campaign_ID --resamples 10000 --output results/amendment_analysis.json
        python -m collusion.inference --campaign logs/campaign_ID --resamples 10000 > results/inference.json

6. exploratory controls (added after main results)

        python -m collusion.upward_control run --campaign logs/campaign_ID --provider anthropic --model claude-haiku-5-5 --execute-paid
        python -m collusion.positive_control run --provider anthropic --model claude-haiku-5-5 --execute-paid

notes:
- haiku 5.5 doesn't take temperature. thinking off, effort medium, max_tokens 4096
- 429s retry with backoff. if a run still dies, resume it
- budget estimate: `python3 -m collusion.preflight_budget --credits-usd 10`

## deepseek (backup, not used for results)

    export DEEPSEEK_API_KEY=...
    python3 -m collusion.runner pretest --provider deepseek --model deepseek-flash --rounds 50 --execute-paid

deepseek-chat is retired, deepseek-flash logs the served version. no seed support so fork copies can drift.
