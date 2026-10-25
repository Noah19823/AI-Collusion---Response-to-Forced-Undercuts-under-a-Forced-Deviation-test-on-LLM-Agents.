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
                     run_folder,save_json,digest,fork_episode,common_meta)
from .analysis import estimate_rho,evaluate_pair,verify_pair
from .client import get_client
from .census import FORKS, validate_bases, validate_plan, base_binding
from .journal import ExecutionBudget, append_event, utc_now
from .records import require_same_population


def load_base_list(path:Path) -> list[Path]:
    raw=path.read_text()
    paths=[Path(x.split("COMPLETED: ",1)[1].strip())
           for x in raw.splitlines() if x.startswith("COMPLETED: ")]
    if not paths: raise ValueError("Empty base-run completion list")
    validate_bases(paths,current_protocol=True)
    return paths

def make_plan(bases:list[Path], seed:int=20261025, *, include_up:bool=False) -> dict:
    validate_bases(bases,current_protocol=True)
    candidates=[]
    for run_id,path in enumerate(bases):
        for local_idx,period in enumerate(FORKS):
            candidates.append({"run_id":run_id,"base":str(path.resolve()),"period":period,
                 "cutter":ACTORS[(local_idx+run_id)%2],"subset_extra":False})
    rng=random.Random(seed)
    extra=set(rng.sample(range(len(candidates)),12))
    for i,row in enumerate(candidates):
        row["subset_extra"]=i in extra
    plan={"protocol":"calling-the-bluff/20261024",
            "subsets_fixed_before_fork_data":True,
            "seed_local_only":seed,"rows":candidates,
            "base_bindings":[base_binding(path,i) for i,path in enumerate(bases)],
            "horizon":15,"include_up":include_up,
            "plan_digest":digest(candidates)}
    plan['plan_sha256']=digest(plan)
    return plan

async def execute_plan(plan:dict,provider:str,model:str,limit:int=None,include_up:bool=False,
                       concurrency:int=1,resume:Path=None, *,budget=None,resolved_model=None) -> Path:
    # Main's new resume implementation trusts row labels and replays partial rows.
    # Do not touch old evidence or start requests until recovery has a validated
    # branch/attempt/budget ledger. Parallel scheduling is likewise not qualified.
    if type(concurrency) is not int or concurrency != 1:
        raise ValueError('Parallel campaigns are not qualified; use concurrency=1')
    if resume is not None:
        raise ValueError('Resume is disabled until partial-branch and prior-budget recovery is validated; preserve the original campaign')
    # Fail BEFORE opening a campaign if the source cannot satisfy its claims.
    checked=validate_plan(plan,current_protocol=True)
    if limit is not None and (type(limit) is not int or not 1<=limit<=48):
        raise ValueError('max-forks must lie in [1,48]')
    if plan.get('include_up',include_up)!=include_up:
        raise ValueError('Control count differs from the frozen plan')
    if provider!='mock' and budget is None:
        raise ValueError('Live campaign requires a shared HTTP-attempt count and deadline')
    for base,(meta,completed,_) in checked.items():
        if meta["provider"]!=provider or meta["model"]!=model:
            raise ValueError("Mixed model/provider base runs")
        if provider!="mock" and any(p <= 1.47292666003 for p in completed["last10_mean"].values()):
            raise ValueError("Base runs did not stabilize above Nash; do not silently substitute constructed histories")
    # A credential check opens no requests. Compare actual effective request
    # configuration before opening any branch or spending on any population.
    probe=get_client(provider,model,budget=budget,resolved_model=resolved_model)
    try:
        target=common_meta(provider,model,'fork_sham',15,2,0,probe)
        for meta,_,_ in checked.values():require_same_population(meta,target)
    finally:
        if hasattr(probe,'close'):await probe.close()
    path=run_folder("campaign")
    save_json(path/"plan.json",plan)
    manifest=path/"manifest.jsonl"
    selected=plan["rows"] if limit is None else plan["rows"][:limit]
    for ix,row in enumerate(selected):
        collected={}
        kinds=["sham","cut"]+((["sham2","up"] if include_up else ["sham2"]) if row["subset_extra"] else [])
        for kind in kinds:
            base=Path(row['base']).resolve()
            source_seed=checked[base][0]['seed_local_only']
            append_event(path/'attempts.jsonl',{'at_utc':utc_now(),'plan_row':ix,'kind':kind,'event':'branch_started'})
            client=None
            try:
                client=get_client(provider,model,seed=source_seed,budget=budget,resolved_model=resolved_model)
                p=await fork_episode(client,provider,model,Path(row["base"]),
                     row["period"],15,row["cutter"],kind,source_seed)
                collected[kind]=str(p.resolve())
                append_event(path/'attempts.jsonl',{'at_utc':utc_now(),'plan_row':ix,'kind':kind,
                             'event':'branch_complete','branch':str(p.resolve())})
            except BaseException as exc:
                save_json(path/'failure.json',{'status':'FAILED_OR_INTERRUPTED','at_utc':utc_now(),
                    'plan_row':ix,'kind':kind,'completed_branches_in_row':collected,
                    'failed_branch':getattr(client,'episode_context',{}).get('episode'),
                    'exception_type':type(exc).__name__,'no_completion_marker':True})
                raise
            finally:
                if client is not None and hasattr(client,"close"): await client.close()
        try:
            verify_pair(Path(row["base"]),Path(collected["sham"]),Path(collected["cut"]))
        except BaseException as exc:
            save_json(path/'failure.json',{'status':'FAILED_VALIDATION','at_utc':utc_now(),
                'phase':'pair_validation','plan_row':ix,'completed_branches_in_row':collected,
                'exception_type':type(exc).__name__,'no_completion_marker':True})
            raise
        record={"plan_row":ix,**row,"branches":collected,"status":"COMPLETE"}
        append_event(manifest,record)
        if (ix+1)%12==0:
            print(f"Validated {ix+1}/{len(selected)} matched fork points",flush=True)
    actual_branch_count=sum(
        2+(1+int(include_up) if r["subset_extra"] else 0)
        for r in selected
    )
    try:
        save_json(path/"completion.json",{"rows_complete":len(selected),
                  "branch_counts":actual_branch_count,
                  "include_up":include_up,
                  "provider":provider,
                  "classification":"SYNTHETIC_INTEGRATION" if provider=="mock" else "LIVE_MODEL",
                  "plan_sha256":plan.get('plan_sha256'),
                  "campaign_attempts_sha256":digest((path/'attempts.jsonl').read_bytes()),
                  "manifest_sha256":digest(manifest.read_bytes())})
    except BaseException as exc:
        save_json(path/'failure.json',{'status':'FAILED_COMPLETION_PUBLICATION','at_utc':utc_now(),
            'phase':'completion_publication','rows_complete':len(selected),
            'exception_type':type(exc).__name__,
            'no_completion_marker':not (path/'completion.json').exists()})
        raise
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
    p.add_argument('--max-http-attempts',type=int)
    p.add_argument('--deadline-seconds',type=float)
    p.add_argument('--resolved-model')
    p.add_argument('--concurrency',type=int,default=1,help='Only 1 is currently qualified')
    p.add_argument('--resume',type=Path,help='Recognized but blocked until evidence-preserving recovery is validated')
    p.add_argument("--include-up",action="store_true",help="Also run the upward copy (dropped for scope in Amendment 1)")
    args=p.parse_args()
    if args.provider!="mock" and not args.execute_paid:
        p.error("Paid calls disabled without --execute-paid")
    budget=None
    if args.provider!='mock':
        if args.max_http_attempts is None or args.deadline_seconds is None:
            p.error('Live campaigns require --max-http-attempts and --deadline-seconds')
        try:budget=ExecutionBudget(args.max_http_attempts,args.deadline_seconds)
        except ValueError as exc:p.error(str(exc))
    bases=load_base_list(args.base_list)
    plan=make_plan(bases,include_up=args.include_up)
    model=args.model or DEFAULT_MODEL[args.provider]
    out=asyncio.run(execute_plan(plan,args.provider,model,args.max_forks,args.include_up,
                               concurrency=args.concurrency,resume=args.resume,
                               budget=budget,resolved_model=args.resolved_model))
    summary=summarize(plan,out/"manifest.jsonl")
    save_json(out/"descriptive_summary.json",summary)
    print(json.dumps({"campaign":str(out),"n_runs":summary["n_base_runs"],
                      "n_forks":summary["n_forks"],
                      "provider":summary["provider_classification"],
                      "rho":summary["rho_fit"].get("rho_clipped_for_model"),
                      "mean_index":summary["mean_PI_dynamic_fixed_rho"]},indent=2))

if __name__=="__main__":
    main()
