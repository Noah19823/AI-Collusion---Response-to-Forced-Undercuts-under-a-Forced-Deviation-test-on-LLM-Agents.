"""Upward-copy control, added after the main campaign (exploratory, logged in PROTOCOL.md).

On the 12 fork points that already have a second no-cut copy, force the cutter
10% ABOVE its own previous price instead of below, and score the rival with the
same three measures. If the rival also prices below the non-punishing baseline
after a forced raise, it is reacting to any change, and its response to cuts
should not be read as punishment.

Run (paid):
    python -m collusion.upward_control run --campaign logs/campaign_ID --provider anthropic \
        --model claude-haiku-5-5 --concurrency 3 --execute-paid
Analyze (free):
    python -m collusion.upward_control analyze --upward logs/upward_ID --rho 0.9215871718895743
"""
from __future__ import annotations
import argparse
import asyncio
import json
import random
import statistics as st
from pathlib import Path

from .runner import run_folder, save_json, digest, fork_episode, load_jsonl, DEFAULT_MODEL
from .analysis import evaluate_pair, _read_branch
from .client import get_client
from .market import Market

M = Market()


def _read(d: Path):
    return _read_branch(d)


def score(base_dir: Path, sham_dir: Path, up_dir: Path, rho: float) -> dict:
    """Same three measures as evaluate_pair, for an upward copy against its no-cut copy."""
    sm, s = _read(sham_dir)
    um, u = _read(up_dir)
    for f in ("model", "provider", "fork_period", "cutter", "prefix_sha256", "source_round_sha256"):
        if sm[f] != um[f]:
            raise ValueError(f"Nonmatching fork {f}")
    if um["intervention"] != "up" or sm["intervention"] != "sham":
        raise ValueError("Expected an up copy and a sham copy")
    base = load_jsonl(base_dir / "rounds.jsonl")
    period = um["fork_period"]
    if digest(base[:period - 1]) != um["prefix_sha256"]:
        raise ValueError("Prefix hash wrong")
    cutter = um["cutter"]
    other = next(a for a in ("Firm A", "Firm B") if a != cutter)
    expected = base[period - 2]["actors"][cutter]["executed_price"] * 1.1
    if abs(u[0]["actors"][cutter]["executed_price"] - expected) > 1e-9:
        raise ValueError("Forced price does not match a 10% raise")
    if len(s) != len(u):
        raise ValueError("Unequal horizons")
    one = static = dynamic = dhat = 0.0
    for k in range(1, len(u)):
        diff = u[k]["actors"][other]["executed_price"] - s[k]["actors"][other]["executed_price"]
        dbr = (M.best_response(round(u[k - 1]["actors"][cutter]["executed_price"], 2)) -
               M.best_response(round(s[k - 1]["actors"][cutter]["executed_price"], 2)))
        dhat = rho * dhat + (1 - rho) * dbr
        if k == 1:
            one = diff - dbr
        static += diff - dbr
        dynamic += diff - dhat
    return {"PI_one_period": one, "PI_static_sum": static, "PI_dynamic_sum": dynamic,
            "responder": other, "cutter": cutter, "fork_period": period}


async def run(campaign: Path, provider: str, model: str, concurrency: int, resume: Path | None):
    plan = json.loads((campaign / "plan.json").read_text())
    man = {json.loads(x)["plan_row"]: json.loads(x)
           for x in (campaign / "manifest.jsonl").read_text().splitlines() if x.strip()}
    rows = [(ix, r) for ix, r in enumerate(plan["rows"]) if r["subset_extra"]]
    if resume is None:
        out = run_folder("upward")
        save_json(out / "meta.json", {"campaign": str(campaign.resolve()), "n_rows": len(rows),
                                      "added_after_main_results": True,
                                      "plan_digest": plan["plan_digest"]})
    else:
        out = resume
    manifest = out / "manifest.jsonl"
    done = set()
    if manifest.exists():
        done = {json.loads(x)["plan_row"] for x in manifest.read_text().splitlines() if x.strip()}
    sem, lock = asyncio.Semaphore(max(1, concurrency)), asyncio.Lock()

    async def one(ix, row):
        async with sem:
            seed = plan["seed_local_only"] + row["run_id"]
            client = get_client(provider, model, seed=seed)
            try:
                p = await fork_episode(client, provider, model, Path(row["base"]),
                                       row["period"], 15, row["cutter"], "up", seed)
            finally:
                if hasattr(client, "close"):
                    await client.close()
            rec = {"plan_row": ix, "run_id": row["run_id"], "base": row["base"],
                   "sham": man[ix]["branches"]["sham"], "up": str(p.resolve())}
            async with lock:
                with manifest.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, sort_keys=True) + "\n")
                n = len(manifest.read_text().splitlines())
                print(f"Upward copy {n}/{len(rows)} done (plan row {ix})", flush=True)

    await asyncio.gather(*(one(ix, r) for ix, r in rows if ix not in done))
    print(json.dumps({"upward": str(out)}, indent=2))


def analyze(upward: Path, rho: float, resamples: int = 10000) -> dict:
    meta = json.loads((upward / "meta.json").read_text())
    campaign = Path(meta["campaign"])
    cmap = {json.loads(x)["plan_row"]: json.loads(x)
            for x in (campaign / "manifest.jsonl").read_text().splitlines() if x.strip()}
    recs = [json.loads(x) for x in (upward / "manifest.jsonl").read_text().splitlines() if x.strip()]
    rows = []
    for r in recs:
        up = score(Path(r["base"]), Path(r["sham"]), Path(r["up"]), rho)
        c = cmap[r["plan_row"]]["branches"]
        cut = evaluate_pair(Path(r["base"]), Path(c["sham"]), Path(c["cut"]), rho)
        rows.append({"plan_row": r["plan_row"], "run_id": r["run_id"],
                     **{"up_" + k: up[k] for k in ("PI_one_period", "PI_static_sum", "PI_dynamic_sum")},
                     **{"cut_" + k: cut[k] for k in ("PI_one_period", "PI_static_sum", "PI_dynamic_sum")}})
    rng = random.Random(20261025)
    out = {"scope": "EXPLORATORY_ADDED_AFTER_MAIN_RESULTS", "rho": rho, "n_forks": len(rows),
           "n_runs": len({r["run_id"] for r in rows}), "forks": rows}
    runs = sorted({r["run_id"] for r in rows})
    for key in ("up_PI_one_period", "up_PI_dynamic_sum", "cut_PI_one_period", "cut_PI_dynamic_sum"):
        vals = [st.mean(r[key] for r in rows if r["run_id"] == i) for i in runs]
        bs = sorted(st.mean(rng.choice(vals) for _ in vals) for _ in range(resamples))
        out[key] = {"mean": st.mean(vals), "ci95": [bs[int(.025 * resamples)], bs[int(.975 * resamples) - 1]],
                    "runs_below_zero": sum(v < 0 for v in vals), "n_runs": len(vals)}
    return out


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--campaign", type=Path, required=True)
    r.add_argument("--provider", default="anthropic")
    r.add_argument("--model", default=None)
    r.add_argument("--concurrency", type=int, default=3)
    r.add_argument("--resume", type=Path, default=None)
    r.add_argument("--execute-paid", action="store_true")
    a = sub.add_parser("analyze")
    a.add_argument("--upward", type=Path, required=True)
    a.add_argument("--rho", type=float, required=True)
    a.add_argument("--resamples", type=int, default=10000)
    a.add_argument("--output", type=Path)
    args = p.parse_args()
    if args.cmd == "run":
        if args.provider != "mock" and not args.execute_paid:
            p.error("Paid calls disabled without --execute-paid")
        asyncio.run(run(args.campaign, args.provider, args.model or DEFAULT_MODEL[args.provider], args.concurrency, args.resume))
    else:
        res = analyze(args.upward, args.rho, args.resamples)
        summary = {k: v for k, v in res.items() if k != "forks"}
        if args.output:
            args.output.write_text(json.dumps(res, indent=2) + "\n")
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
