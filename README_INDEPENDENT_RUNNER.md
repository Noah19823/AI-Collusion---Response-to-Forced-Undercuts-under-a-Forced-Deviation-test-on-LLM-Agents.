# Independent runner — execution instructions

This local development branch adds a standalone Python runner, 12-run campaign driver, offline scripted controls, and inference/tests under collusion/ and tests/. Original team PROTOCOL.md, PREDICTIONS.md, BRIEF.md and part1/scripted_sim.py are unchanged.

All commands run inside the working-copy directory.

## Offline, zero cost

    python3 -m unittest discover -s tests -v
    python3 -m collusion.runner benchmark
    python3 -m collusion.runner scripted
    python3 -m collusion.runner base --provider mock --rounds 8 --runs 1

To rehearse a paired fork, use the printed base directory:

    python3 -m collusion.runner fork --provider mock --base-dir logs/base_ID --period 4 --horizon 3 --kind sham
    python3 -m collusion.runner fork --provider mock --base-dir logs/base_ID --period 4 --horizon 3 --kind cut

To validate and recompute the paired prices and profits:

    python3 -m collusion.analysis --base-dir logs/base_ID --sham-dir logs/fork_sham_ID --cut-dir logs/fork_cut_ID --rho 0.85

A complete 12x150 mock census exists in logs/full_mock_census.txt. Its 48-point synthetic fork campaign and extra controls are stored under logs/campaign_8eca4197de97/. Use the corrected descriptive summary, not the preserved earlier invalid regression.

## Amendment A7: Haiku 5.5 compatibility and budget check

Before paid model execution, estimate the full campaign against the available credits:

    python3 -m collusion.preflight_budget --credits-usd 3 --strict-budget

This zero-network estimator assumes 3,500 input and 600 output tokens per decision. It reports 6,890 model decisions and an estimated $4.48 spend before a 15% reserve, so $3 is not projected to cover the full campaign. It is not a hard provider spending cap; a bounded live pilot is required to measure actual token usage, thinking cost and growing history prompts.

The official Haiku 5.5 API omits temperature, top_p and top_k. The harness freezes its documented medium effort, accepts text following thinking blocks, and records the served model and token usage. The current max_tokens=1200 may be exhausted by adaptive thinking before a valid JSON price; an exhausted response fails without an identical automatic retry.

## Live model — NOT YET EXECUTED

Prerequisites: sign off the scientific corrections in INDEPENDENT_EXECUTION_HANDOFF_20261025.md; establish a monetary ceiling and API permission; configure the ANTHROPIC_API_KEY environment variable locally on the workstation without sharing it in chat. Every real model command explicitly requires --execute-paid.

Step 1: a correct 50-period one-product solo pretest:

    python3 -m collusion.runner pretest --provider anthropic --model claude-haiku-5-5 --rounds 50 --execute-paid

Read its completion.json. It must have pretest_near_one_product_monopoly=true.

Step 2: twelve independent 150-period duopoly baselines (qualified pretest path is mandatory):

    python3 -m collusion.runner base --provider anthropic --model claude-haiku-5-5 --rounds 150 --runs 12 --pretest-dir logs/pretest_ID --execute-paid | tee logs/live_base_census.txt

Step 3: freeze and execute the matched interventions. Provider/model/pretest must agree and live baselines must end above Nash.

    python3 -m collusion.campaign --base-list logs/live_base_census.txt --provider anthropic --model claude-haiku-5-5 --execute-paid

Step 4: primitive log recomputation, cluster-bootstrap rho re-estimation, and abstention checks.

    python3 -m collusion.inference --campaign logs/campaign_ID --resamples 10000

The agent's original simultaneous period-t choices are reused in both branches; only the specified executed price and subsequent market history are modified. All generated logs reside in ignored logs/ and include explicit provider/synthetic labels.

Scientific scope: negative PI_dyn identifies a deviation from a particular sticky-myopic best-response null. It is not proof of intentional punishment. The forecasting-based out-of-model test illustrates this limitation.

## Running on DeepSeek

The harness has a `deepseek` provider that calls DeepSeek's OpenAI-compatible API. Whoever has the key sets it only in their own terminal:

    export DEEPSEEK_API_KEY=<key>

Then use the same commands with `--provider deepseek --model deepseek-flash`, pretest first:

    python3 -m collusion.runner pretest --provider deepseek --model deepseek-flash --rounds 50 --execute-paid

`deepseek-flash` points at DeepSeek-V4.1-Flash (currently 1017) and the legacy deepseek-chat alias is retired, so every call logs `served_model` with the version the server reports. Put that version in the report. DeepSeek isn't assumed to honour seeds, so the two copies of a fork can drift apart like any hosted API, and the second no-cut copy measures how much. Garra (2026) found DeepSeek-V3 failed the monopoly pretest and DeepSeek-V3.1 passed, so post the pretest result before going further.
