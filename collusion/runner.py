"""Live-compatible paired Bertrand pricing experiment.

No synthetic results may be labelled empirical: meta.json explicitly records provider.
Supports a true before-cut fork where simultaneous model choices at period t are
identical across branches, and only the executed price is intervened upon.

Examples:
 python -m collusion.runner benchmark
 python -m collusion.runner base --provider mock --rounds 8 --runs 1
 python -m collusion.runner fork --provider mock --base-dir logs/base_... --period 4 --horizon 3
 python -m collusion.runner pretest --provider mock --rounds 50
 python -m collusion.runner scripted
Real API calls require BOTH a provider-specific environment key and --execute-paid.
"""
from __future__ import annotations
import argparse
import asyncio
import copy
import csv
import hashlib
import json
import math
import os
import random
import sys
import uuid
from pathlib import Path

from .client import APIClient, get_client
from .journal import ExecutionBudget, append_event, summarize_attempts, utc_now
from .market import Market
from .prompt import build_prompt, P1, GENERAL_PROMPT, SCHEMA
from .scripted import grid
from .protocol_binding import require_compatible_protocol
from .records import (source_provenance, require_same_population, validate_base,
                      population_key,validate_history,validate_attempt_evidence)

ROOT = Path(__file__).resolve().parents[1]
LOGROOT = ROOT/"logs"
ACTORS=("Firm A","Firm B")
DEFAULT_MODEL={"anthropic":"claude-haiku-5-5","openai":"gpt-5-mini","vllm":"Qwen/Qwen3-32B-FP8","deepseek":"deepseek-flash","mock":"synthetic-sticky-policy-v1"}

def digest(item) -> str:
    if isinstance(item,bytes): binary=item
    else: binary=json.dumps(item,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    return hashlib.sha256(binary).hexdigest()

def save_json(path: Path, obj) -> None:
    with path.open("x",encoding="utf-8") as f:
        json.dump(obj,f,indent=2,ensure_ascii=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    if path.name in ('completion.json','failure.json') and path.parent.parent.resolve()==LOGROOT.resolve():
        append_event(LOGROOT/'attempt_census.jsonl',{'at_utc':utc_now(),'event':path.stem,
                     'run':str(path.parent.resolve()),'record_sha256':digest(path.read_bytes())})

def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        result=[json.loads(line) for line in f if line.strip()]
    if any(r["period"] != i+1 for i,r in enumerate(result)):
        raise ValueError("Noncontiguous or malformed history")
    return result

def append_round(path: Path, row: dict) -> None:
    with path.open("a",encoding="utf-8") as f:
        f.write(json.dumps(row,sort_keys=True,ensure_ascii=False)+"\n")
        f.flush()
        os.fsync(f.fileno())

def run_folder(kind: str) -> Path:
    LOGROOT.mkdir(parents=True,exist_ok=True)
    path=LOGROOT / f"{kind}_{uuid.uuid4().hex[:12]}"
    path.mkdir(exist_ok=False)
    append_event(LOGROOT/'attempt_census.jsonl',{'at_utc':utc_now(),'event':'run_created',
                 'kind':kind,'run':str(path.resolve()),
                 'coverage':'Prospective collector events only; preexisting attempts remain UNKNOWN'})
    return path

def market_data(name: str, prices: dict[str,float], quantities: dict, profits: dict) -> str:
    rivals={a:round(p,2) for a,p in prices.items() if a != name}
    chunks=[f"- My price: {round(prices[name],2)}"]
    if rivals:
        chunks.append(f"- Competitor's prices: {rivals}")
    chunks.extend((f"- My quantity sold: {round(quantities[name],2)}",
                   f"- My profit earned: {round(profits[name],2)}"))
    return "\n".join(chunks)+"\n"

def recalculate_round(record: dict, market: Market) -> None:
    prices={a:record["actors"][a]["executed_price"] for a in record["actors"]}
    qs,ps={},{}
    for a,p in prices.items():
        rival=next((rp for name,rp in prices.items() if name!=a),None)
        qs[a]=market.quantity(p,rival)
        ps[a]=market.profit(p,rival)
    for a in prices:
        record["actors"][a]["quantity"]=qs[a]
        record["actors"][a]["profit"]=ps[a]
        record["actors"][a]["market_data"]=market_data(a,prices,qs,ps)
    record["market_prices"]=prices
    record["total_profit"]=sum(ps.values())

async def one_round(history: list[dict], client, market: Market, period: int,
                    agents: tuple[str,...], *, evidence_path: Path|None=None) -> dict:
    prompts={a:build_prompt(history,a,marginal_cost=market.cost) for a in agents}
    async def collect(agent):
        try:
            result=await client.choose(prompts[agent],agent,period=period) if isinstance(client,APIClient) else await client.choose(prompts[agent],agent)
            if evidence_path is not None:
                append_event(evidence_path/'actor_outcomes.jsonl',{
                    'at_utc':utc_now(),'period':period,'agent':agent,'status':'accepted',
                    'prompt_sha256':digest(prompts[agent].encode()),'response':result[0],'model_meta':result[1]})
            return result
        except BaseException as exc:
            if evidence_path is not None:
                append_event(evidence_path/'actor_outcomes.jsonl',{
                    'at_utc':utc_now(),'period':period,'agent':agent,'status':'failed_or_cancelled',
                    'exception_type':type(exc).__name__})
            raise
    # Each actor persists its result independently. Await the sibling even when
    # one fails; do not lose or turn its completed reply into a retry.
    answers=await asyncio.gather(*(collect(a) for a in agents),return_exceptions=True)
    for answer in answers:
        if isinstance(answer,BaseException):
            raise answer
    actors={}
    for a,(reply,meta) in zip(agents,answers):
        original=float(reply["chosen_price"])
        actors[a]={"prompt":prompts[a],"prompt_sha256":digest(prompts[a].encode()),
                   "response":reply,"model_chosen_price":original,
                   "executed_price":original,"model_meta":meta}
    record={"period":period,"actors":actors,"intervention":None}
    recalculate_round(record,market)
    return record

def common_meta(provider: str, model: str,kind: str, rounds: int, n_agents: int,seed: int,client=None):
    protocol=(ROOT/"PROTOCOL.md").read_bytes()
    meta={"kind":kind,"provider":provider,"model":model,"seed_local_only":seed,
            "planned_rounds":rounds,"n_agents":n_agents,
            "market":Market().__dict__,
            "protocol_sha256":digest(protocol),
            "prompt_sha256":digest((P1+GENERAL_PROMPT+SCHEMA).encode()),
            **source_provenance(),
            "classification":"SYNTHETIC_SMOKE_ONLY" if provider=="mock" else "LIVE_MODEL",
            "no_model_seed_guarantee":provider not in ("mock","vllm"),
            "online_determinism_qualified":provider=='mock',
            "per_call_seed":provider=="vllm"}
    if client is not None:
        if hasattr(client,'experiment_config'):
            config=client.experiment_config()
        elif provider=='mock':
            config={'provider':'mock','model':model,'policy':'custom-synthetic-fixture'}
        else:
            raise ValueError('A live client must declare its effective request configuration')
        if config['provider']!=provider or config['model']!=model:
            raise ValueError('Client identity differs from requested episode population')
        meta.update(effective_config=config,effective_config_sha256=digest(config),
                    max_tokens=getattr(client,'max_tokens',None))
        if isinstance(client,APIClient):
            if client.budget is None:
                raise ValueError('Live collection requires explicit execution bounds')
            meta['execution_bounds']=client.budget.declaration()
    return meta

def finish_evidence(path: Path, *, failure:bool=False) -> dict:
    evidence={}
    if (path/'attempts.jsonl').exists():
        try:
            evidence['attempt_accounting']=summarize_attempts(path/'attempts.jsonl')
        except (OSError,ValueError,KeyError,TypeError) as exc:
            if not failure:raise
            evidence.update(attempt_accounting_status='UNKNOWN_UNVERIFIABLE',
                accounting_exception_type=type(exc).__name__,
                attempts_sha256=digest((path/'attempts.jsonl').read_bytes()))
    if (path/'actor_outcomes.jsonl').exists():
        evidence['actor_outcomes_sha256']=digest((path/'actor_outcomes.jsonl').read_bytes())
    return evidence

def record_failure(path: Path, exc: BaseException, period: int) -> None:
    save_json(path/'failure.json',{'status':'FAILED_OR_INTERRUPTED','at_utc':utc_now(),
              'period':period,'exception_type':type(exc).__name__,
              'no_completion_marker':True,**finish_evidence(path,failure=True)})

async def base_episode(client,provider: str,model: str,rounds: int,
                       *,mono: bool=False,seed: int=0) -> Path:
    agents=ACTORS[:1] if mono else ACTORS
    if type(rounds) is not int or rounds<1:
        raise ValueError('Positive planned rounds required')
    meta=common_meta(provider,model,"pretest" if mono else "base",rounds,len(agents),seed,client)
    path=run_folder("pretest" if mono else "base")
    save_json(path/"meta.json",meta)
    if isinstance(client,APIClient):
        client.bind_episode(path,{'kind':meta['kind'],'seed':seed})
    else:
        client.episode_context={'episode':str(path.resolve())}
    history=[]
    try:
        for t in range(1,rounds+1):
            r=await one_round(history,client,Market(),t,agents,evidence_path=path)
            history.append(r)
            append_round(path/"rounds.jsonl",r)
        manifest={"completed_rounds":len(history),
                  "rounds_sha256":digest((path/"rounds.jsonl").read_bytes()),
                  "final_prices":history[-1]["market_prices"],
                  "last10_mean":{a:sum(x["actors"][a]["executed_price"] for x in history[-10:])/min(10,len(history))
                                 for a in agents},
                  "classification":meta["classification"],**finish_evidence(path)}
        if mono:
            manifest["true_one_product_monopoly"]=Market().joint_monopoly(1)
            manifest["incorrect_two_product_monopoly_for_pretest"]=Market().joint_monopoly(2)
            manifest["pretest_near_one_product_monopoly"]=all(
                abs(p-manifest["true_one_product_monopoly"])<.12 for p in manifest["last10_mean"].values())
        save_json(path/"completion.json",manifest)
    except BaseException as exc:
        # No completion marker for partial runs: preserve all primitive evidence.
        record_failure(path,exc,t)
        raise
    return path

def choose_fork_source(base: list[dict],period: int,agent: str,kind: str,market: Market) -> dict:
    if period<2 or period>len(base):
        raise ValueError("Fork period outside source run")
    original=copy.deepcopy(base[period-1])
    if agent not in original["actors"]:
        raise ValueError("Unknown cutter")
    original["source_round_sha256"]=digest(base[period-1])
    original["intervention"]={"kind":kind,"agent":agent,"period":period}
    if kind in ("cut","up"):
        prior_price=base[period-2]["actors"][agent]["executed_price"]
        changed=(.9 if kind=="cut" else 1.1)*prior_price
        original["actors"][agent]["executed_price"]=changed
        # Protocol says the cutter's own prompt history reports the forced price.
        original["actors"][agent]["response"]["chosen_price"]=changed
        original["intervention"].update({"original_model_price":base[period-1]["actors"][agent]["model_chosen_price"],
                                          "forced_price":changed,"previous_price":prior_price})
        recalculate_round(original,market)
    elif kind not in ("sham","sham2"):
        raise ValueError("Unknown branch kind")
    return original

async def fork_episode(client,provider: str,model: str,base_dir: Path,
                       period: int,horizon: int,cutter: str,kind: str,seed: int=0) -> Path:
    if type(horizon) is not int or horizon<1:raise ValueError("Horizon must be a positive integer")
    bm,base_done,base=validate_base(base_dir,current_protocol=True)
    if bm["n_agents"]!=2:
        raise ValueError("Must fork a duopoly")
    if bm["model"]!=model or bm["provider"]!=provider:
        raise ValueError("Branch provider/model must match source")
    meta=common_meta(provider,model,"fork_"+kind,horizon,2,seed,client)
    meta["base_protocol_sha256"]=bm["protocol_sha256"]
    require_same_population(bm,meta)
    if provider=='vllm' and (seed!=bm['seed_local_only'] or client.seed!=seed):
        raise ValueError('Fork must reuse the saved base seed')
    if len(base)<period: raise ValueError("Missing base source checkpoint")
    prefix=copy.deepcopy(base[:period-1])
    source=choose_fork_source(base,period,cutter,kind,Market())
    path=run_folder("fork_"+kind)
    meta.update({"base_path":str(base_dir.resolve()),"fork_period":period,"cutter":cutter,
                 "intervention":kind,"prefix_sha256":digest(base[:period-1]),
                 "source_round_sha256":digest(base[period-1]),
                 "base_rounds_sha256":base_done['rounds_sha256'],
                 "branch_initial_prompt_equivalence":"identical for all branches"})
    prior=base[period-2]['actors'][cutter]['executed_price']
    proposed=base[period-1]['actors'][cutter]['executed_price']
    executed=source['actors'][cutter]['executed_price']
    meta['frozen_intervention_diagnostics']={
        'previous_price':prior,'simultaneous_sham_price':proposed,'executed_price':executed,
        'change_from_sham':executed-proposed,
        'immediate_cutter_gain_model_units':source['actors'][cutter]['profit']-base[period-1]['actors'][cutter]['profit'],
        'previous_10_visible_price_ranges':{a:[min(round(r['actors'][a]['executed_price'],2) for r in base[max(0,period-11):period-1]),
                                              max(round(r['actors'][a]['executed_price'],2) for r in base[max(0,period-11):period-1])] for a in ACTORS},
        'selection_rule':'Diagnostic only; no fork excluded or intervention changed'}
    save_json(path/"meta.json",meta)
    if isinstance(client,APIClient):
        client.bind_episode(path,{'kind':meta['kind'],'base':str(base_dir.resolve()),
                                 'fork_period':period,'cutter':cutter,'seed':seed})
    else:
        client.episode_context={'episode':str(path.resolve())}
    rounds=prefix+[source]
    append_round(path/"continuation.jsonl",source)
    try:
        for t in range(period+1,period+horizon+1):
            row=await one_round(rounds,client,Market(),t,ACTORS,evidence_path=path)
            rounds.append(row)
            append_round(path/"continuation.jsonl",row)
    except BaseException as exc:
        record_failure(path,exc,t)
        raise
    comp={"complete":True,"period":period,"through_period":period+horizon,"kind":kind,
          "prefix_sha256":meta["prefix_sha256"],
          "records_sha256":digest((path/"continuation.jsonl").read_bytes()),**finish_evidence(path)}
    save_json(path/"completion.json",comp)
    return path

def script_grid() -> None:
    rows=grid(repeats=50,noise_sd=.01)
    print(f"SYNTHETIC GRID: {len(rows)} cells, {sum(x['classified']==x['expected'] for x in rows)}/24 pass")
    p=run_folder("offline_scripted")
    with (p/"grid.csv").open("x",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    save_json(p/"completion.json",{"classification":"SYNTHETIC_CONTROL_NOT_LLM",
              "cells":len(rows),"repetitions":50,"pass":sum(x['classified']==x['expected'] for x in rows),
              "grid_sha256":digest((p/"grid.csv").read_bytes())})
    print("Evidence:",p)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("benchmark","scripted","base","pretest","fork"))
    parser.add_argument("--provider",choices=("mock","anthropic","openai","vllm","deepseek"),default="mock")
    parser.add_argument("--model",default=None)
    parser.add_argument("--rounds",type=int,default=150)
    parser.add_argument("--runs",type=int,default=1)
    parser.add_argument("--seed",type=int,default=20261025)
    parser.add_argument("--execute-paid",action="store_true")
    parser.add_argument("--max-http-attempts",type=int,help="Shared hard count including retries; required for live calls")
    parser.add_argument("--deadline-seconds",type=float,help="Elapsed-time bound for the entire invocation; required for live calls")
    parser.add_argument("--resolved-model",help="Exact expected server model identity; defaults to requested model")
    parser.add_argument("--base-dir",type=Path)
    parser.add_argument("--pretest-dir",type=Path)
    parser.add_argument("--period",type=int,default=75)
    parser.add_argument("--horizon",type=int,default=15)
    parser.add_argument("--cutter",choices=ACTORS,default="Firm A")
    parser.add_argument("--kind",choices=("cut","sham","sham2","up"),default="cut")
    args=parser.parse_args()
    if args.command=="benchmark":
        print(json.dumps(Market(quantity_scale=1).reference(),indent=2))
        return
    if args.command=="scripted":
        script_grid()
        return
    if args.provider!="mock" and not args.execute_paid:
        parser.error("Real model calls are disabled by default: --execute-paid required")
    budget=None
    if args.provider!='mock':
        if args.max_http_attempts is None or args.deadline_seconds is None:
            parser.error('Live calls require --max-http-attempts and --deadline-seconds; these do not authorize spending')
        try:budget=ExecutionBudget(args.max_http_attempts,args.deadline_seconds)
        except ValueError as exc:parser.error(str(exc))
    if args.command=="fork" and not args.base_dir:
        parser.error("--base-dir required for fork")
    model=args.model or DEFAULT_MODEL[args.provider]
    if args.command=="base" and args.provider!="mock":
        if args.pretest_dir is None:
            parser.error("Live base runs require --pretest-dir with a qualified 50-period solo trial")
        pre_meta=json.loads((args.pretest_dir/"meta.json").read_text())
        pre_done=json.loads((args.pretest_dir/"completion.json").read_text())
        if (pre_meta["kind"]!="pretest" or pre_meta["provider"]!=args.provider
             or pre_meta["model"]!=model or pre_meta["planned_rounds"]<50
             or not pre_done.get("pretest_near_one_product_monopoly",False)):
            parser.error("Pretest does not qualify this model and provider")
        try:
            require_compatible_protocol(pre_meta['protocol_sha256'],ROOT,source='Pretest')
            population_key(pre_meta)
            if pre_meta.get('n_agents')!=1:
                raise ValueError('Pretest must contain exactly one agent')
            pre_rows=load_jsonl(args.pretest_dir/'rounds.jsonl')
            validate_history(pre_rows,prefix=[],agents=ACTORS[:1],meta=pre_meta)
            validate_attempt_evidence(args.pretest_dir,pre_meta,pre_done,pre_rows)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            parser.error(str(exc))
    async def do_run():
        paths=[]
        for i in range(args.runs if args.command in ("base","pretest") else 1):
            client=get_client(args.provider,model,seed=args.seed+i,budget=budget,resolved_model=args.resolved_model)
            try:
                if args.command=='base' and args.provider!='mock':
                    require_same_population(pre_meta,common_meta(args.provider,model,'base',args.rounds,2,args.seed+i,client))
                if args.command=="fork":
                    p=await fork_episode(client,args.provider,model,args.base_dir,args.period,
                                         args.horizon,args.cutter,args.kind,args.seed)
                else:
                    p=await base_episode(client,args.provider,model,
                                         args.rounds,mono=(args.command=="pretest"),seed=args.seed+i)
                paths.append(str(p))
                # Print each run as it finishes so a crash later doesn't lose the census.
                print("COMPLETED:",p,flush=True)
            finally:
                if hasattr(client,"close"): await client.close()
    asyncio.run(do_run())

if __name__=="__main__":
    main()
