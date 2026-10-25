"""Positive control on the real model (exploratory, added after the main results).

Both agents get the main prompt plus an explicit rule to punish a rival who cuts
(PUNISH_RULE in prompt.py). We run 2 base games of 100 rounds, estimate rho from
them, fork each at periods 50, 60, 70 and 80 (8 forks, cutter alternating), and
score the forks with the same three measures. A working audit should score these
agents below zero.

Run (paid):
    python -m collusion.positive_control run --provider anthropic --model claude-haiku-5-5 --execute-paid
Analyze (free):
    python -m collusion.positive_control analyze --folder logs/positive_ID
"""
from __future__ import annotations
import argparse
import asyncio
import json
import os
import random
import statistics as st
from pathlib import Path

os.environ["COLLUSION_PROMPT_VARIANT"] = "punisher_v2"   # set before any prompt is built

from .runner import (run_folder, save_json, base_episode, fork_episode, ACTORS, DEFAULT_MODEL)
from .analysis import evaluate_pair
from .client import get_client
from .rho import estimate

FORKS = (50, 60, 70, 80)
ROUNDS = 100
SEED = 20261100


async def run(provider: str, model: str, concurrency: int, resume: Path | None):
    if resume is None:
        out = run_folder("positive")
        save_json(out / "meta.json", {"prompt_variant": "punisher_v2", "rounds": ROUNDS,
                                      "forks": FORKS, "added_after_main_results": True})
    else:
        out = resume
    bases_file = out / "bases.json"
    bases = json.loads(bases_file.read_text()) if bases_file.exists() else []
    if len(bases) < 2:
        async def one_base(i):
            client = get_client(provider, model, seed=SEED + i)
            try:
                return str(await base_episode(client, provider, model, ROUNDS, seed=SEED + i))
            finally:
                if hasattr(client, "close"):
                    await client.close()
        need = range(len(bases), 2)
        bases += list(await asyncio.gather(*(one_base(i) for i in need)))
        bases_file.write_text(json.dumps(bases) + "\n")
        print("Base games done:", bases, flush=True)
    manifest = out / "manifest.jsonl"
    done = set()
    if manifest.exists():
        done = {json.loads(x)["fork_id"] for x in manifest.read_text().splitlines() if x.strip()}
    jobs = [(ri, period, ACTORS[(k + ri) % 2]) for ri in range(2) for k, period in enumerate(FORKS)]
    sem, lock = asyncio.Semaphore(max(1, concurrency)), asyncio.Lock()

    async def one_fork(ri, period, cutter):
        fid = f"{ri}_{period}"
        async with sem:
            got = {}
            for kind in ("sham", "cut"):
                client = get_client(provider, model, seed=SEED + ri)
                try:
                    p = await fork_episode(client, provider, model, Path(bases[ri]), period, 15,
                                           cutter, kind, SEED + ri)
                    got[kind] = str(p.resolve())
                finally:
                    if hasattr(client, "close"):
                        await client.close()
            async with lock:
                with manifest.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"fork_id": fid, "run_id": ri, "base": bases[ri],
                                        "period": period, "cutter": cutter, **got}) + "\n")
                n = len(manifest.read_text().splitlines())
                print(f"Positive-control fork {n}/{len(jobs)} done", flush=True)

    await asyncio.gather(*(one_fork(*j) for j in jobs if f"{j[0]}_{j[1]}" not in done))
    print(json.dumps({"positive": str(out)}, indent=2))


def analyze(folder: Path, resamples: int = 10000) -> dict:
    bases = [Path(b) for b in json.loads((folder / "bases.json").read_text())]
    fit = estimate(bases, 50)
    rho = fit.get("pooled_rho")
    recs = [json.loads(x) for x in (folder / "manifest.jsonl").read_text().splitlines() if x.strip()]
    out = {"scope": "EXPLORATORY_POSITIVE_CONTROL_ADDED_AFTER_MAIN_RESULTS",
           "rho_fit": fit, "n_forks": len(recs)}
    use = {"rho_own": rho, "rho_main": 0.9215871718895743}
    rng = random.Random(20261025)
    for label, r in use.items():
        if r is None or not 0 <= r < 1:
            out[label] = "NOT_IDENTIFIED"
            continue
        rows = [evaluate_pair(Path(x["base"]), Path(x["sham"]), Path(x["cut"]), r) for x in recs]
        res = {"rho": r}
        for k in ("PI_one_period", "PI_static_sum", "PI_dynamic_sum"):
            v = [x[k] for x in rows]
            bs = sorted(st.mean(rng.choice(v) for _ in v) for _ in range(resamples))
            res[k] = {"mean": st.mean(v), "fork_ci95": [bs[int(.025 * resamples)], bs[int(.975 * resamples) - 1]],
                      "forks_below_zero": sum(x < 0 for x in v), "n": len(v)}
        out[label] = res
    return out


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--provider", default="anthropic")
    r.add_argument("--model", default=None)
    r.add_argument("--concurrency", type=int, default=3)
    r.add_argument("--resume", type=Path, default=None)
    r.add_argument("--execute-paid", action="store_true")
    a = sub.add_parser("analyze")
    a.add_argument("--folder", type=Path, required=True)
    a.add_argument("--resamples", type=int, default=10000)
    a.add_argument("--output", type=Path)
    args = p.parse_args()
    if args.cmd == "run":
        if args.provider != "mock" and not args.execute_paid:
            p.error("Paid calls disabled without --execute-paid")
        asyncio.run(run(args.provider, args.model or DEFAULT_MODEL[args.provider],
                        args.concurrency, args.resume))
    else:
        res = analyze(args.folder, args.resamples)
        if args.output:
            args.output.write_text(json.dumps(res, indent=2) + "\n")
        print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
