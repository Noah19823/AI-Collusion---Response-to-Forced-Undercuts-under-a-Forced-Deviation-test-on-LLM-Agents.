# Independent runner — execution instructions

This local development branch adds a standalone Python runner, 12-run campaign driver, offline scripted controls, and inference/tests under collusion/ and tests/. Original team PROTOCOL.md, PREDICTIONS.md, BRIEF.md and part1/scripted_sim.py are unchanged.

All commands run inside the working-copy directory.

The implementation audit corrections and unaccepted methodology proposals are in [IMPLEMENTATION_BLOCKERS_AND_PROPOSALS_20261025.md](IMPLEMENTATION_BLOCKERS_AND_PROPOSALS_20261025.md). They do not authorize live execution. Unknown historical configurations and unapproved protocol transitions fail admission; do not overwrite old metadata or repeat completed work to bypass that gate.

## Offline, zero cost

    python3 tests/run_offline.py
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

The Haiku 5.5 request omits temperature, top_p and top_k, disables thinking and uses medium effort. A10 set max_tokens=4096. Truncated and mismatched-model responses fail fast and remain in the attempt journal. That cap change does not automatically qualify earlier 1200-cap evidence.

## Live model — separate authorization and evidence admission required

Prerequisites: sign off the scientific corrections in INDEPENDENT_EXECUTION_HANDOFF_20261025.md; establish a monetary ceiling and API permission; configure the ANTHROPIC_API_KEY environment variable locally on the workstation without sharing it in chat. Every real model command explicitly requires --execute-paid.

The command templates below also require caller-approved values for `REQUEST_LIMIT` and `SECONDS`. These bound total HTTP attempts (including retries) and elapsed time across one invocation; they do not set a dollar ceiling or authorize a new campaign. The raw-pretest correction in PR #5 and the separate methodology decisions must be resolved before use.

Step 1: a correct 50-period one-product solo pretest:

    python3 -m collusion.runner pretest --provider anthropic --model claude-haiku-5-5 --rounds 50 --execute-paid --max-http-attempts REQUEST_LIMIT --deadline-seconds SECONDS

The pass marker alone is insufficient: validate the primitive rounds, monopoly criterion, raw attempt/outcome seals, actual source/configuration identity and compatible protocol. Missing historical records remain unavailable.

Step 2: twelve independent 150-period duopoly baselines (qualified pretest path is mandatory):

    python3 -m collusion.runner base --provider anthropic --model claude-haiku-5-5 --rounds 150 --runs 12 --pretest-dir logs/pretest_ID --execute-paid --max-http-attempts REQUEST_LIMIT --deadline-seconds SECONDS | tee logs/live_base_census.txt

Step 3: freeze and execute the matched interventions. Provider/model/pretest must agree and live baselines must end above Nash.

    python3 -m collusion.campaign --base-list logs/live_base_census.txt --provider anthropic --model claude-haiku-5-5 --execute-paid --max-http-attempts REQUEST_LIMIT --deadline-seconds SECONDS

Step 4: primitive log recomputation, cluster-bootstrap rho re-estimation, and abstention checks.

    python3 -m collusion.amendment_analysis --campaign logs/campaign_ID --resamples 10000

The agent's original simultaneous period-t choices are reused in both branches; only the specified executed price and subsequent market history are modified. All generated logs reside in ignored logs/ and include explicit provider/synthetic labels.

Scientific scope: negative PI_dyn identifies a deviation from a particular sticky-myopic best-response null. It is not proof of intentional punishment. The forecasting-based out-of-model test illustrates this limitation.

## Running on DeepSeek

The harness has a `deepseek` provider that calls DeepSeek's OpenAI-compatible API. Whoever has the key sets it only in their own terminal:

    export DEEPSEEK_API_KEY=<key>

Then use the same commands with `--provider deepseek --model deepseek-flash`, pretest first:

    python3 -m collusion.runner pretest --provider deepseek --model deepseek-flash --resolved-model EXACT_SERVER_MODEL_ID --rounds 50 --execute-paid --max-http-attempts REQUEST_LIMIT --deadline-seconds SECONDS

Declare and record the exact server identity behind any provider alias. The adapter rejects an unexpected version rather than mixing model populations. DeepSeek is not assumed to honor seeds. Its evidence and qualification remain separate from Haiku, including the pretest and sham-noise interpretation.
