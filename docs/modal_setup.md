# Running the study on Modal (free with sprint credits)

Every sprint participant gets $50 of Modal credits. Modal credits pay for GPU time, not for Claude, so this path runs an open-weight model (Qwen3-32B by default) on a Modal GPU with vLLM. The harness talks to it the same way it talks to an API, with `--provider vllm`.

vLLM honours a seed on each request. The harness sets that seed from the run, the agent and the period, so the cut copy and the no-cut copy of a fork get the same samples up to the cut. Tran and Yu found copies served this way agree on 94 to 98% of calls, compared with 23 to 45% through an API, so the noise floor should be much smaller than on Claude.

Backup if there's no Claude credit. Switching models has to be logged in PROTOCOL.md before any run.

## One-time setup (about 10 minutes, plus the model download)

1. Claim your $50 Modal credit from the sprint page and make a Modal account with it.
2. On your machine, from the repo folder:

   ```
   pip install modal httpx
   modal setup
   ```

   `modal setup` opens a browser to log you in.
3. Make up a password for the server and store it in Modal. Pick any long random string and keep it out of the repo.

   ```
   modal secret create collusion-vllm-key VLLM_API_KEY=<your-long-random-string>
   ```
4. Deploy the server:

   ```
   modal deploy modal_server/vllm_server.py
   ```

   It prints a URL ending in `.modal.run`. That is your `VLLM_BASE_URL`.
5. The first request starts the GPU and downloads the model (about 33 GB), which takes 10 to 20 minutes. Later starts are faster because the download is cached. Warm it up and check it works:

   ```
   curl -s "$VLLM_BASE_URL/v1/models" -H "Authorization: Bearer <your-long-random-string>"
   ```

   Keep re-running it until you get a JSON reply that lists `Qwen/Qwen3-32B-FP8`.

## Running the experiment

In the terminal you run the experiment from:

```
export VLLM_BASE_URL=https://<your-url>.modal.run
export VLLM_API_KEY=<your-long-random-string>
```

Then the same steps as `docs/running.md`, with `--provider vllm`:

```
python3 -m collusion.runner pretest --provider vllm --model Qwen/Qwen3-32B-FP8 --rounds 50 --execute-paid
```

Check `completion.json` for `"pretest_near_one_product_monopoly": true`. If it passes:

```
python3 -m collusion.runner base --provider vllm --model Qwen/Qwen3-32B-FP8 --rounds 150 --runs 12 --pretest-dir logs/pretest_ID --execute-paid | tee logs/live_base_census.txt
```

Log the rho estimate in PROTOCOL.md before forking. Then:

```
python3 -m collusion.campaign --base-list logs/live_base_census.txt --provider vllm --model Qwen/Qwen3-32B-FP8 --execute-paid
python3 -m collusion.amendment_analysis --campaign logs/campaign_ID --resamples 10000
```

`--execute-paid` is still required. The harness uses it for any call to a real model, even though Modal credits pay for this one.

## If the pretest fails

Tran and Yu found Qwen3-32B often just copies the rival's price, so it might not pass. If it doesn't, log it before switching models. Then change `MODEL_NAME` at the top of `modal_server/vllm_server.py`, redeploy, and pass the same name to `--model`. `Qwen/Qwen3-30B-A3B-Instruct-2507` is faster and fits on the same GPU. Larger models like Llama 3.3 70B need two GPUs (set `GPU = "H100:2"` and add `"--tensor-parallel-size", "2"` to the command).

## Costs and shutting it down

The server shuts its GPU down after 10 idle minutes, so you only pay while runs are going. Check Modal's pricing page for the current H100 hourly rate and keep an eye on usage in the Modal dashboard. The whole study is about 7,300 calls, which should take a few GPU hours at most. When everything is done:

```
modal app stop collusion-vllm
```

## Things to watch

- Qwen3 normally "thinks" before answering. The harness turns that off (`enable_thinking: false`) and strips any leftover `<think>` tags, so replies stay plain JSON like the protocol expects.
- If replies fail to parse or prices are out of range, don't change the prompt to work around it without logging it.
- The secret, the URL and the API key never go in the repo. `logs/` is already ignored.
