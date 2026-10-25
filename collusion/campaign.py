"""Generate/follow a frozen 12x4 fork census and run matched copies.

Mock campaigns verify the complete experiment plumbing only. Real model
campaigns require --execute-paid and provider credentials; this script does
not authorize API costs by itself. No branch result is silently discarded.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import random
from pathlib import Path

from .runner import (LOGROOT, DEFAULT_MODEL,ACTORS,
                     run_folder,save_json,digest,fork_episode)
from .analysis import estimate_rho,evaluate_pair,verify_pair
from .client import get_client

FORKS=(75,95,115,135)

def load_base_list(path:Path) -> list[Path]:
    raw=path.read_text()
    paths=[Path(x.split("COMPLETED: ",1)[1].strip())
           for x in raw.splitlines() if x.startswith("COMPLETED: ")]
    if not paths: raise ValueError("Empty base-run completion list")
    for d in paths:
        if not (d/"completion.json").exists(): raise ValueError(f"Incomplete base: {d}")
        meta=json.loads((d/"meta.json").read_text())
        completed=json.loads((d/"completion.json").read_text())
        if meta["kind"]!="base" or meta["n_agents"]!=2 or completed["completed_rounds"]<max(FORKS):
            raise ValueError(f"Bad or too-short duopoly base: {d}")
        if meta["protocol_sha256"]!=digest((Path(__file__).resolve().parents[1]/"PROTOCOL.md").read_bytes()):
            raise ValueError(f"Protocol mismatch in base: {d}")
    return paths

def make_plan(bases:list[Path], seed:int=20261025) -> dict:
    if len(bases)!=12:raise ValueError("Protocol expects 12 independent base runs")
    candidates=[]
    for run_id,path in enumerate(bases):
        for local_idx,period in enumerate(FORKS):
            candidates.append({"run_id":run_id,"base":str(path.resolve()),"period":period,
                 "cutter":ACTORS[(local_idx+run_id)%2],"subset_extra":False})
    rng=random.Random(seed)
    extra=set(rng.sample(range(len(candidates)),12))
    for i,row in enumerate(candidates):
        row["subset_extra"]=i in extra
    return {"protocol":"calling-the-bluff/20261024",
            "subsets_fixed_before_fork_data":True,
            "seed_local_only":seed,"rows":candidates,
            "plan_digest":digest(candidates)}

async def execute_plan(plan:dict,provider:str,model:str,limit:int=None,include_up:bool=False) -> Path:
    # Fail BEFORE opening a campaign if the source cannot satisfy its claims.
    checked=set()
    for row in plan["rows"]:
        base=Path(row["base"])
        if base in checked: continue
        checked.add(base)
        meta=json.loads((base/"meta.json").read_text())
        completed=json.loads((base/"completion.json").read_text())
        if meta["provider"]!=provider or meta["model"]!=model:
            raise ValueError("Mixed model/provider base runs")
        if provider!="mock" and any(p <= 1.47292666003 for p in completed["last10_mean"].values()):
            raise ValueError("Base runs did not stabilize above Nash; do not silently substitute constructed histories")
    path=run_folder("campaign")
    save_json(path/"plan.json",plan)
    manifest=path/"manifest.jsonl"
    selected=plan["rows"] if limit is None else plan["rows"][:limit]
    for ix,row in enumerate(selected):
        collected={}
        kinds=["sham","cut"]+((["sham2","up"] if include_up else ["sham2"]) if row["subset_extra"] else [])
        for kind in kinds:
            client=get_client(provider,model,seed=plan["seed_local_only"]+row["run_id"])
            try:
                p=await fork_episode(client,provider,model,Path(row["base"]),
                     row["period"],15,row["cutter"],kind,plan["seed_local_only"]+row["run_id"])
                collected[kind]=str(p.resolve())
            finally:
                if hasattr(client,"close"): await client.close()
        verify_pair(Path(row["base"]),Path(collected["sham"]),Path(collected["cut"]))
        record={"plan_row":ix,**row,"branches":collected,"status":"COMPLETE"}
        with manifest.open("a",encoding="utf-8") as f:
            f.write(json.dumps(record,sort_keys=True)+"\n")
        if (ix+1)%12==0:
            print(f"Validated {ix+1}/{len(selected)} matched fork points",flush=True)
    save_json(path/"completion.json",{"rows_complete":len(selected),
              "branch_counts":sum(2+(2 if r["subset_extra"] else 0) for r in selected),
              "provider":provider,
              "classification":"SYNTHETIC_INTEGRATION" if provider=="mock" else "LIVE_MODEL",
              "manifest_sha256":digest(manifest.read_bytes())})
    return path

def summarize(plan:dict,manifest:Path) -> dict:
    results=[json.loads(line) for line in manifest.read_text().splitlines() if line.strip()]
    bases=[Path(x) for x in dict.fromkeys(row["base"] for row in results)]
    try:
        fit=estimate_rho(bases)
        rh=fit["rho_clipped_for_model"]
    except ValueError as exc:
        # Failure to identify rho is a scientific result about measurement
        # validity, not permission to silently use an arbitrary point estimate.
        fit={"status":"NOT_IDENTIFIABLE","reason":str(exc)}
        rh=None
    per_run=[]
    if rh is not None:
        pairs=[]
        for row in results:
            r=evaluate_pair(Path(row["base"]),Path(row["branches"]["sham"]),
                           Path(row["branches"]["cut"]),rh)
            r["run_id"]=row["run_id"]
            pairs.append(r)
        for run_id in sorted({r["run_id"] for r in pairs}):
            group=[p for p in pairs if p["run_id"]==run_id]
            per_run.append({"run_id":run_id,
                            "PI_dynamic_mean":sum(g["PI_dynamic_sum"] for g in group)/len(group),
                            "G_H_mean":sum(g["G_H"] for g in group)/len(group)})
    vals=[x["PI_dynamic_mean"] for x in per_run]
    is_mock=all(json.loads((Path(r["base"])/"meta.json").read_text())["provider"]=="mock" for r in results)
    return {"scope":"SYNTHETIC_PIPELINE_SMOKE" if is_mock else "LIVE_MODEL_DESCRIPTIVE",
            "provider_classification":"SYNTHETIC_MOCK" if is_mock else "LIVE",
            "rho_fit":fit,"n_base_runs":len(bases),
            "n_forks":len(results),"n_extra_sham":sum("sham2" in x["branches"] for x in results),
            "n_extra_up":sum("up" in x["branches"] for x in results),
            "per_run":per_run,
            "mean_PI_dynamic_fixed_rho":sum(vals)/len(vals) if vals else None,
            "decision":"ABSTAIN_RHO_NOT_IDENTIFIED" if rh is None else "DESCRIPTIVE_ONLY",
            "note":"Model-visible prices are rounded to 2dp. If rho is unidentified, do not issue PI_dyn conclusions. Even when identified, proper run-cluster bootstrap is required."}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--base-list",required=True,type=Path)
    p.add_argument("--provider",choices=("mock","anthropic","openai","vllm","deepseek"),default="mock")
    p.add_argument("--model")
    p.add_argument("--max-forks",type=int,default=None)
    p.add_argument("--execute-paid",action="store_true")
    p.add_argument("--include-up",action="store_true",help="Also run the upward copy (dropped for scope in Amendment 1)")
    args=p.parse_args()
    if args.provider!="mock" and not args.execute_paid:
        p.error("Paid calls disabled without --execute-paid")
    bases=load_base_list(args.base_list)
    plan=make_plan(bases)
    model=args.model or DEFAULT_MODEL[args.provider]
    out=asyncio.run(execute_plan(plan,args.provider,model,args.max_forks,args.include_up))
    summary=summarize(plan,out/"manifest.jsonl")
    save_json(out/"descriptive_summary.json",summary)
    print(json.dumps({"campaign":str(out),"n_runs":summary["n_base_runs"],
                      "n_forks":summary["n_forks"],
                      "provider":summary["provider_classification"],
                      "rho":summary["rho_fit"].get("rho_clipped_for_model"),
                      "mean_index":summary["mean_PI_dynamic_fixed_rho"]},indent=2))

if __name__=="__main__":
    main()
