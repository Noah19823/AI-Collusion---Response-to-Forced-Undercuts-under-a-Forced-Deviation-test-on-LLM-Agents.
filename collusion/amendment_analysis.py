"""Independent Amendment-1-compatible analysis of completed fork campaigns.

Primary goals: 12-run cluster bootstrap, uncertainty in stickiness, an explicit
rho sensitivity grid when stickiness cannot be identified, the amended P3
*decision comparison* (not comparison of unlike statistic magnitudes), and
a sham-vs-sham2 noise floor. Does not infer internal retaliation or intent.

This module does not rewrite frozen PROTOCOL.md, PREDICTIONS.md, or raw logs.
All mock runs are explicitly labelled and are NOT empirical LLM evidence.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from collections import defaultdict
from pathlib import Path

from .analysis import _read_branch, verify_pair
from .inference import fit_pooled_rho, pooled_rho_diagnostics, rho_sufficient_stats, percentile
from .market import Market
from .runner import digest
from .census import validate_plan, validate_branch_ownership
from .records import validate_branch
from .robustness import certify_rho_interval

MARKET = Market(quantity_scale=1)
AMENDMENT_GRID = (0.0, 0.25, 0.5, 0.75, 0.9, 0.95)
EXPECTED_BASE_RUNS = 12
EXPECTED_FORKS = 48
EXPECTED_SECOND_SHAMS = 12


def dynamic_from_features(features: dict, rho: float) -> float:
    """O(H) algebraically exact cumulative version of the recursive null."""
    if not 0 <= rho < 1 or not math.isfinite(rho):
        raise ValueError("rho outside [0,1)")
    d = features["diff"]
    b = features["br_diff"]
    if len(d) != len(b) or not d:
        raise ValueError("Invalid paired features")
    horizon = len(d)
    return sum(d) - sum(
        v * (1-rho ** (horizon-k)) for k,v in enumerate(b)
    )


def one_from_features(features: dict) -> float:
    return features["diff"][0]-features["br_diff"][0]


def pair_features(first: list[dict], second: list[dict],
                  cutter: str, responder: str) -> dict:
    """Price-gap sequence: first branch minus second branch."""
    if len(first) != len(second) or len(first) < 2:
        raise ValueError("Incompatible branch histories")
    diffs, brs = [], []
    for k in range(1,len(first)):
        if first[k]["period"] != second[k]["period"]:
            raise ValueError("Misaligned pair periods")
        diffs.append(
            first[k]["actors"][responder]["executed_price"]-
            second[k]["actors"][responder]["executed_price"]
        )
        qfirst=round(first[k-1]["actors"][cutter]["executed_price"],2)
        qsecond=round(second[k-1]["actors"][cutter]["executed_price"],2)
        brs.append(MARKET.best_response(qfirst)-MARKET.best_response(qsecond))
    return {"diff":diffs,"br_diff":brs,"horizon":len(diffs)}


def checked_second_sham(sham_dir: Path, sham2_dir: Path):
    first_meta, first=_read_branch(sham_dir)
    second_meta, second=_read_branch(sham2_dir)
    if sham_dir.resolve()==sham2_dir.resolve():
        raise ValueError('Second sham must have distinct branch ownership')
    validate_branch(Path(first_meta['base_path']),sham_dir)
    validate_branch(Path(second_meta['base_path']),sham2_dir)
    for k in ("model","provider","fork_period","cutter",
              "prefix_sha256","source_round_sha256"):
        if first_meta[k]!=second_meta[k]:
            raise ValueError("Second-sham source/state mismatch: "+k)
    if first_meta["intervention"] != "sham" or second_meta["intervention"]!="sham2":
        raise ValueError("Expected two no-cut branches")
    if len(first)!=len(second):
        raise ValueError("Second-sham continuation length mismatch")
    # At the simultaneous decision period, branch labels may differ but
    # proposals, executed prices and original PLANS/INSIGHTS may not.
    for actor in ("Firm A","Firm B"):
        a=first[0]["actors"][actor]
        b=second[0]["actors"][actor]
        for name in ("prompt","prompt_sha256","model_chosen_price",
                     "executed_price","response"):
            if a[name]!=b[name]:
                raise ValueError("Second-sham first round differs: "+actor+"."+name)
    cutter=first_meta["cutter"]
    responder=next(a for a in ("Firm A","Firm B") if a!=cutter)
    return pair_features(second,first,cutter,responder)


def load_campaign(campaign:Path) -> dict:
    seal_path=campaign/"completion.json"
    if not seal_path.exists():
        raise ValueError("Campaign not sealed; partial campaigns cannot be confirmatory")
    seal=json.loads(seal_path.read_text())
    manifest_path=campaign/"manifest.jsonl"
    if digest(manifest_path.read_bytes())!=seal.get("manifest_sha256"):
        raise ValueError("Manifest digest mismatch")
    manifest=[json.loads(x) for x in manifest_path.read_text().splitlines() if x.strip()]
    if not manifest:
        raise ValueError('No completed fork rows')
    plan=json.loads((campaign/"plan.json").read_text())
    checked_bases=validate_plan(plan)
    if 'plan_sha256' in plan and seal.get('plan_sha256')!=plan['plan_sha256']:
        raise ValueError('Completion does not bind the frozen plan')
    if digest(plan["rows"])!=plan.get("plan_digest"):
        raise ValueError("Plan digest mismatch")
    if len(manifest)!=seal["rows_complete"]:
        raise ValueError("Manifest row count mismatch")
    if len(manifest)>len(plan["rows"]):
        raise ValueError("Extra rows not in predeclared plan")
    if seal.get('campaign_attempts_sha256'):
        raw_attempts=(campaign/'attempts.jsonl').read_bytes()
        if digest(raw_attempts)!=seal['campaign_attempts_sha256']:
            raise ValueError('Campaign attempt census seal mismatch')
        starts=set()
        completed={}
        for line in raw_attempts.splitlines():
            event=json.loads(line)
            key=(event['plan_row'],event['kind'])
            if event['event']=='branch_started' and key not in starts:
                starts.add(key)
            elif event['event']=='branch_complete' and key in starts and key not in completed:
                completed[key]=str(Path(event['branch']).resolve())
            else:
                raise ValueError('Invalid/duplicate campaign attempt lifecycle')
        expected={(entry['plan_row'],kind):str(Path(path).resolve())
                  for entry in manifest for kind,path in entry['branches'].items()}
        if completed!=expected or starts!=set(expected):
            raise ValueError('Campaign attempt census differs from completed branch ownership')
    elif seal['provider']!='mock':
        raise ValueError('Live campaign lacks its attempt census seal')

    groups=defaultdict(list)
    stats={}
    noise=defaultdict(list)
    providers=set()
    second_shams=0
    seen_rows=set()
    seen_branch_paths=set()
    seen_branch_raw=set()
    for entry in manifest:
        index=entry["plan_row"]
        if index in seen_rows:
            raise ValueError("Duplicate plan row in campaign manifest")
        seen_rows.add(index)
        if type(index) is not int or index<0 or index>=len(plan["rows"]):
            raise ValueError("Bad manifest plan_row")
        expected=plan["rows"][index]
        for name in ("run_id","base","period","cutter","subset_extra"):
            if entry[name]!=expected[name]:
                raise ValueError("Manifest differs from predeclared plan: "+name)
        if entry.get("status")!="COMPLETE":
            raise ValueError("Incomplete manifest row")
        validate_branch_ownership(entry,seen_branch_paths,seen_branch_raw)
        run_id=entry["run_id"]
        base=Path(entry["base"])
        bm=json.loads((base/"meta.json").read_text())
        providers.add(bm["provider"])
        if bm["provider"]!=seal["provider"]:
            raise ValueError("Mixed model providers in evidence")
        stats.setdefault(run_id,rho_sufficient_stats(base))
        branches=entry["branches"]
        include_up=plan.get('include_up',seal.get('include_up',any('up' in r['branches'] for r in manifest)))
        expected_branches={'cut','sham'}|({'sham2'}|({'up'} if include_up else set()) if entry['subset_extra'] else set())
        if set(branches)!=expected_branches:
            raise ValueError('Branch roles/second-sham assignment differ from the frozen plan')
        cm,sham,cut,responder=verify_pair(
            base,Path(branches["sham"]),Path(branches["cut"])
        )
        features=pair_features(cut,sham,entry["cutter"],responder)
        groups[run_id].append(features)
        if "sham2" in branches:
            second_shams+=1
            noise[run_id].append(checked_second_sham(
                Path(branches["sham"]),Path(branches["sham2"])
            ))
        if "up" in branches:
            validate_branch(base,Path(branches['up']))
    if len(providers)!=1:
        raise ValueError("Mixed campaign providers")
    recorded_branch_count=sum(
        len(entry["branches"]) for entry in manifest
    )
    if seal.get("branch_counts")!=recorded_branch_count:
        raise ValueError("Sealed branch count disagrees with manifest")
    return {
        "classification":seal["classification"],
        "provider":seal["provider"],
        "groups":dict(groups),
        "rho_stats":stats,
        "noise_by_run":dict(noise),
        "n_forks":len(manifest),
        "n_second_shams":second_shams,
        "n_runs":len(groups),
        "plan_matches":True,
        "independent_base_identities":len(checked_bases),
        "layout_complete":seen_rows==set(range(48)),
        "amendment":"2026-10-25/A1-A6"
    }


def _mean_by_run(group:dict,rho:float,metric:str) -> dict:
    out={}
    for run_id,features in group.items():
        values = [
            dynamic_from_features(f,rho) if metric=="dynamic"
            else one_from_features(f)
            for f in features
        ]
        out[run_id]=sum(values)/len(values)
    return out


def _ci_from_indices(values_by_run:dict, sampled_ids:list[list[int]]) -> list[float]:
    draws=[sum(values_by_run[i] for i in sample)/len(sample)
           for sample in sampled_ids]
    return [percentile(draws,.025),percentile(draws,.975)]


def _null_floor(noise_by_run:dict, rho:float, metric:str) -> dict:
    all_values=[]
    for features in noise_by_run.values():
        for f in features:
            all_values.append(
                dynamic_from_features(f,rho) if metric=="dynamic"
                else one_from_features(f)
            )
    if not all_values:
        return {"n":0,"p95_absolute":None}
    return {"n":len(all_values),
            "p95_absolute":percentile([abs(x) for x in all_values],.95),
            "median_absolute":percentile([abs(x) for x in all_values],.5),
            "interpretation":"Descriptive 95th percentile of absolute per-fork sham-sham2 residuals; only 12 available and not a calibrated significance threshold."}


def analysis(campaign:Path, *, repeats:int=10000,seed:int=20261025) -> dict:
    if repeats<100:
        raise ValueError("Too few bootstrap resamples")
    data=load_campaign(campaign)
    ids=sorted(data["groups"])
    is_mock=(data["provider"]=="mock")
    complete=(len(ids)==EXPECTED_BASE_RUNS and
              data["n_forks"]==EXPECTED_FORKS and
              data["n_second_shams"]==EXPECTED_SECOND_SHAMS)
    rng=random.Random(seed)
    sampled_ids=[rng.choices(ids,k=len(ids)) for _ in range(repeats)]
    stats=data["rho_stats"]
    raw_rho=fit_pooled_rho([stats[i] for i in ids])
    rho_diagnostics=pooled_rho_diagnostics([stats[i] for i in ids])
    bootstrap_rhos=[
        fit_pooled_rho([stats[i] for i in sample])
        for sample in sampled_ids
    ]
    valid=[r for r in bootstrap_rhos if r is not None]
    valid_fraction=len(valid)/repeats
    rho_ci=[percentile(valid,.025),percentile(valid,.975)] if valid else None
    rho_qualified=(raw_rho is not None and
                   valid_fraction>=.9 and
                   rho_ci is not None)

    one_run={}
    for i,features in data["groups"].items():
        one_run[i]=sum(one_from_features(f) for f in features)/len(features)
    one_mean=sum(one_run.values())/len(ids)
    one_ci=_ci_from_indices(one_run,sampled_ids)
    floor_one=_null_floor(data["noise_by_run"],0,"one")
    one_classification="ONE_PERIOD_NEGATIVE_CI" if one_ci[1]<0 else "ONE_PERIOD_NOT_NEGATIVE_CI"

    fixed_grid={}
    for rho in AMENDMENT_GRID:
        run_means=_mean_by_run(data["groups"],rho,"dynamic")
        obs=sum(run_means.values())/len(ids)
        ci=_ci_from_indices(run_means,sampled_ids)
        floor=_null_floor(data["noise_by_run"],rho,"dynamic")
        fixed_grid[f"{rho:g}"]={
            "rho":rho,"mean":obs,"ci95":ci,
            "negative_ci":ci[1]<0,
            "noise_floor":floor,
            "effect_exceeds_noise_floor":(
                floor["p95_absolute"] is not None and
                abs(obs)>floor["p95_absolute"]),
            "restricted_null_screen_positive":bool(
                ci[1]<0 and floor["p95_absolute"] is not None and
                abs(obs)>floor["p95_absolute"]),
            "fork_sign_disagreement_with_one_period":sum(
                (dynamic_from_features(f,rho)<0)!=(one_from_features(f)<0)
                for rows in data["groups"].values() for f in rows
            ),
            "scope":"DESCRIPTIVE_SENSITIVITY_NOT_A_CONFIRMATORY_DECISION"
        }

    point_dynamic=None
    comparison="NOT_TESTED_RHO_NOT_IDENTIFIED"
    if rho_qualified:
        dynamic_run_means=_mean_by_run(data["groups"],raw_rho,"dynamic")
        observed=sum(dynamic_run_means.values())/len(ids)
        # A new rho is estimated INSIDE each run-cluster bootstrap replicate.
        boot_dynamic=[]
        for sample,rho in zip(sampled_ids,bootstrap_rhos):
            if rho is None:continue
            values=_mean_by_run(data["groups"],rho,"dynamic")
            boot_dynamic.append(sum(values[i] for i in sample)/len(sample))
        dynamic_ci=[percentile(boot_dynamic,.025),percentile(boot_dynamic,.975)] if boot_dynamic else None
        floor=_null_floor(data["noise_by_run"],raw_rho,"dynamic")
        # Preserve the descriptive scan, but never use it to certify the
        # protocol's all-rho requirement. Bound the complete interval below.
        lower,upper=rho_ci
        rho_check=[lower+(upper-lower)*j/10 for j in range(11)]
        robust_checks=[]
        for rho in rho_check:
            run_means=_mean_by_run(data["groups"],rho,"dynamic")
            ci=_ci_from_indices(run_means,sampled_ids)
            robust_checks.append({"rho":rho,"ci_high":ci[1],"negative_ci":ci[1]<0})
        negative_ci=(dynamic_ci is not None and dynamic_ci[1]<0)
        exceeds_floor=(floor["p95_absolute"] is not None and
                       abs(observed)>floor["p95_absolute"])
        continuum=certify_rho_interval(data['groups'],sampled_ids,rho_ci)
        robust=continuum['certified']
        positive_conclusion=bool(negative_ci and exceeds_floor and robust and
                                 complete and not is_mock)
        # Never call an unqualified or synthetic inference 'punishment'.
        point_dynamic={"rho":raw_rho,"mean":observed,
            "ci95":dynamic_ci,"negative_ci":negative_ci,
            "noise_floor":floor,"exceeds_noise_floor":exceeds_floor,
            "robust_11_point_grid_over_rho_ci":all(x['negative_ci'] for x in robust_checks),
            "rho_continuum_certificate":continuum,
            "rho_ci_grid_checks":robust_checks,
            "conclusion":"BELOW_RESTRICTED_NULL" if positive_conclusion
                else "NOT_ESTABLISHED"}
        if not complete:
            comparison="NOT_TESTED_INCOMPLETE_CAMPAIGN"
        elif is_mock:
            comparison="NOT_TESTED_SYNTHETIC"
        elif raw_rho<.5:
            comparison="NOT_TESTED_P2_NOT_MET_RHO_BELOW_0_5"
        elif positive_conclusion and one_ci[1]>=0:
            comparison="P3_SUPPORTED_RESTRICTED_NULL_ONLY"
        else:
            comparison="P3_NOT_SUPPORTED"
    if not complete:
        comparison="NOT_TESTED_INCOMPLETE_CAMPAIGN"
    if is_mock:
        comparison="NOT_TESTED_SYNTHETIC"
    result={
        "version":"amendment1-analysis-1",
        "campaign":str(campaign),
        "provider":data["provider"],
        "classification":data["classification"],
        "is_mock":is_mock,
        "confirmatory_layout_complete":complete,
        "n_runs":len(ids),
        "n_forks":data["n_forks"],
        "n_second_shams":data["n_second_shams"],
        "bootstrap_repeats":repeats,
        "rho_point":raw_rho,
        "rho_unrestricted":rho_diagnostics['rho_unrestricted'],
        "rho_diagnostics":rho_diagnostics,
        "rho_ci95":rho_ci,
        "rho_bootstrap_valid_fraction":valid_fraction,
        "rho_identified_for_decision":rho_qualified,
        "P1":"SCRIPTED_CHECK_SEPARATE",
        "P2":"NOT_TESTED" if not rho_qualified or is_mock else
            ("SUPPORTED" if raw_rho>=.5 else "NOT_SUPPORTED"),
        "one_period":{
            "mean":one_mean,"ci95":one_ci,
            "classification":one_classification,
            "noise_floor":floor_one
        },
        "fixed_rho_sensitivity_grid":fixed_grid,
        "dynamic_point":point_dynamic,
        "amended_P3":comparison,
        "qualification":"A negative price residual establishes a departure from the chosen sticky-myopic null, not strategic intent. Noise floor is descriptive, and this report never treats mock observations as empirical evidence."
    }
    if not rho_qualified:
        result["rho_abstention"]="NO_POINT_RHO_OR_BOOTSTRAP_UNSTABLE"
    return result


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--campaign",type=Path,required=True)
    p.add_argument("--resamples",type=int,default=10000)
    p.add_argument("--seed",type=int,default=20261025)
    p.add_argument("--output",type=Path)
    args=p.parse_args()
    result=analysis(args.campaign,repeats=args.resamples,seed=args.seed)
    if args.output:
        # Never overwrite a published artifact.
        with args.output.open("x",encoding="utf-8") as handle:
            json.dump(result,handle,indent=2)
            handle.write("\n")
    print(json.dumps(result,indent=2))


if __name__=="__main__":
    main()
