"""Run-cluster bootstrap for actual paired-fork evidence; rebuilds rho each draw.

Reads frozen primitive logs. Does not use model grading. Null is conditional
on a restricted sticky-BR family; mechanism/intent remain unidentifiable
without stronger experimental restrictions.
"""
from __future__ import annotations
import argparse
import json
import math
import random
from collections import defaultdict
from pathlib import Path

from .market import Market
from .runner import load_jsonl,digest
from .analysis import _read_branch,verify_pair

M=Market(quantity_scale=1)

def rho_sufficient_stats(base:Path,max_period:int=75):
    rows=load_jsonl(base/"rounds.jsonl")
    xs,ys=[],[]
    for i in range(1,min(len(rows),max_period)):
        current,previous=rows[i],rows[i-1]
        for a in ("Firm A","Firm B"):
            rival="Firm B" if a=="Firm A" else "Firm A"
            q=round(previous["actors"][rival]["executed_price"],2)
            b=M.best_response(q)
            xs.append(round(previous["actors"][a]["executed_price"],2)-b)
            ys.append(current["actors"][a]["executed_price"]-b)
    return {"n":len(xs),"x":sum(xs),"y":sum(ys),
            "xx":sum(x*x for x in xs),"xy":sum(x*y for x,y in zip(xs,ys))}

def fit_pooled_rho(stats:list[dict]):
    n=sum(v["n"] for v in stats)
    if n<20:return None
    sx=sum(v["x"] for v in stats);sy=sum(v["y"] for v in stats)
    sxx=sum(v["xx"] for v in stats);sxy=sum(v["xy"] for v in stats)
    denom=sxx-sx*sx/n
    # Report insufficient signal rather than fitting tiny covariances.
    if denom<=1e-10:return None
    r=(sxy-sx*sy/n)/denom
    if not math.isfinite(r):return None
    # Predeclared physical rho interval [0,1). Report clipping explicitly.
    return min(.999,max(0.0,r))

def primitive_features(base:Path, sham:Path, cut:Path):
    cm,s,c,resp=verify_pair(base,sham,cut)
    cutter=cm["cutter"]
    ds=[];brds=[];profits=[]
    for k in range(1,len(c)):
        diff=c[k]["actors"][resp]["executed_price"]-s[k]["actors"][resp]["executed_price"]
        qcut=round(c[k-1]["actors"][cutter]["executed_price"],2)
        qsham=round(s[k-1]["actors"][cutter]["executed_price"],2)
        ds.append(diff)
        brds.append(M.best_response(qcut)-M.best_response(qsham))
    for k in range(len(c)):
        profits.append(c[k]["actors"][cutter]["profit"]-s[k]["actors"][cutter]["profit"])
    # Raw profit logs have scale=100 whereas model index is on prices.
    return {"diff":ds,"br_diff":brds,"G_H_model_units":sum(profits),
            "period":cm["fork_period"],"cutter":cutter}

def dynamic(feat:dict,rho:float):
    dhat=0.0;acc=0.0
    for dp,brd in zip(feat["diff"],feat["br_diff"]):
        dhat=rho*dhat+(1-rho)*brd
        acc+=dp-dhat
    return acc

def percentile(data:list[float],p:float):
    if not data:return None
    a=sorted(data);s=(len(a)-1)*p;i=int(s)
    return a[i] if i>=len(a)-1 else a[i]*(1+i-s)+a[i+1]*(s-i)

def report(campaign:Path,repeats:int=10000,seed:int=20261025):
    if not (campaign/"completion.json").exists():
        raise ValueError("Campaign not complete")
    meta=json.loads((campaign/"completion.json").read_text())
    man=(campaign/"manifest.jsonl")
    if meta["manifest_sha256"]!=digest(man.read_bytes()):
        raise ValueError("Campaign manifest checksum failure")
    rows=[json.loads(x) for x in man.read_text().splitlines() if x.strip()]
    if not rows:raise ValueError("No completed forks")
    group=defaultdict(list);stats={}
    for row in rows:
        i=row["run_id"]
        base=Path(row["base"])
        stats.setdefault(i,rho_sufficient_stats(base))
        branches=row["branches"]
        feat=primitive_features(base,Path(branches["sham"]),Path(branches["cut"]))
        group[i].append(feat)
    ids=sorted(group)
    rho=fit_pooled_rho([stats[i] for i in ids])
    result={"provider":meta["provider"],"classification":meta["classification"],
        "campaign":str(campaign),"n_runs":len(ids),
        "n_forks":len(rows),"rho_fitted":rho,
        "rho_identified":rho is not None,
        "bootstrap_repeats_requested":repeats}
    if rho is None:
        result.update({"decision":"ABSTAIN_RHO_NOT_IDENTIFIABLE",
          "reason":"Model-visible price variation insufficient for stickiness estimation.",
          "PI_dynamic_mean":None,"CI95":None})
        return result
    def run_mean(i,rr):
        return sum(dynamic(feat,rr) for feat in group[i])/len(group[i])
    observed=sum(run_mean(i,rho) for i in ids)/len(ids)
    rng=random.Random(seed)
    draws=[];rhos=[];invalid=0
    for _ in range(repeats):
        sample=rng.choices(ids,k=len(ids))
        r=fit_pooled_rho([stats[i] for i in sample])
        if r is None:
            invalid+=1
            continue
        rhos.append(r)
        draws.append(sum(run_mean(i,r) for i in sample)/len(sample))
    if len(draws)<repeats*.90:
        decision="ABSTAIN_BOOTSTRAP_RHO_UNSTABLE"
    else:
        low,high=percentile(draws,.025),percentile(draws,.975)
        decision="NEGATIVE_DYNAMIC_RESIDUAL_ONLY" if high<0 else "INCONCLUSIVE_RESIDUAL"
    result.update({"PI_dynamic_mean":observed,
      "CI95":[percentile(draws,.025),percentile(draws,.975)] if draws else None,
      "rho_CI95":[percentile(rhos,.025),percentile(rhos,.975)] if rhos else None,
      "bootstrap_valid":len(draws),"bootstrap_invalid":invalid,
      "decision":decision,
      "qualification":"Negative residual is deviation from sticky myopic BR null, NOT proof of retaliation."})
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--campaign",required=True,type=Path)
    p.add_argument("--resamples",type=int,default=10000)
    args=p.parse_args()
    result=report(args.campaign,args.resamples)
    print(json.dumps(result,indent=2))

if __name__=="__main__":
    main()
