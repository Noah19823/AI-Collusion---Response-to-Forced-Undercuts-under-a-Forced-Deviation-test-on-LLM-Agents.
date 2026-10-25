"""Offline budget preflight for Amendment A7 (Claude Haiku 5.5).

No API calls, no spend authorization, and no guarantee about billable tokens.
Calculates expected *pricing-agent decisions* for the amended campaign.
All token assumptions are adjustable; a bounded paid smoke must measure them.
Use: python3 -m collusion.preflight_budget --credits-usd 3
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path

from .runner import DEFAULT_MODEL
from .journal import summarize_attempts

INPUT_USD_PER_M = .10
OUTPUT_USD_PER_M = .50
INPUT_LONG_USD_PER_M = .50
OUTPUT_LONG_USD_PER_M = 2.50
SHORT_CONTEXT_TOKEN_LIMIT = 100_000

def estimate_cost(n:int,input_tokens:float,output_tokens:float):
    if n<0 or input_tokens<0 or output_tokens<0:
        raise ValueError("Negative usage")
    if not all(math.isfinite(x) for x in (input_tokens,output_tokens)):
        raise ValueError("Non-finite usage")
    long=input_tokens>SHORT_CONTEXT_TOKEN_LIMIT
    rates=(INPUT_LONG_USD_PER_M,OUTPUT_LONG_USD_PER_M) if long else (
           INPUT_USD_PER_M,OUTPUT_USD_PER_M)
    return n*(input_tokens*rates[0]+output_tokens*rates[1])/1_000_000

def stage_counts(*,runs:int=12,periods:int=150,forks_per_run:int=4,
                 horizon:int=15,second_sham_forks:int=12,include_up:bool=False,
                 pretest_periods:int=50)->dict:
    if min(runs,periods,forks_per_run,horizon,pretest_periods)<1:
        raise ValueError("Positive stage periods required")
    if not 0<=second_sham_forks<=runs*forks_per_run:
        raise ValueError("Invalid extra control count")
    return {
        "solo_pretest":pretest_periods,
        "two_agent_baselines":runs*periods*2,
        "cut_and_sham_continuations":runs*forks_per_run*2*horizon*2,
        "second_sham_controls":second_sham_forks*horizon*2,
        "upward_controls":second_sham_forks*horizon*2 if include_up else 0
    }

def scan_usage_records(path:Path)->dict:
    """Estimate actual per-call tokens from real primitive logs, if present.

    Caller must supply an explicit file, and synthetic/mock logs have no
    billable token counts; never mistake those for real-world pricing data.
    """
    if not path.is_file():
        raise FileNotFoundError(path)
    observations=[]
    with path.open(encoding="utf-8") as source:
        for line in source:
            if not line.strip():continue
            record=json.loads(line)
            for actor in record.get("actors",{}).values():
                meta=actor.get("model_meta",{})
                usage=meta.get("usage") or {}
                if meta.get("provider")!="anthropic":
                    continue
                i=usage.get("input_tokens")
                o=usage.get("output_tokens")
                if not (isinstance(i,int) and i>0 and isinstance(o,int) and o>0):
                    continue
                # Caching not used in experiment adapter; do not silently
                # generalize this formula to explicit cached input.
                if (usage.get("cache_read_input_tokens",0) or
                    usage.get("cache_creation_input_tokens",0)):
                    raise ValueError("Cached token accounting requires an explicit rate model")
                observations.append((i,o))
    if not observations:
        raise ValueError("No valid live Anthropic usage observations")
    return {"n_observed_paid_replies":len(observations),
            "mean_input_tokens":sum(x[0] for x in observations)/len(observations),
            "mean_output_tokens":sum(x[1] for x in observations)/len(observations),
            "max_input_tokens":max(x[0] for x in observations),
            "max_output_tokens":max(x[1] for x in observations),
            "scope":"Accepted primitive replies only; copied fork-source replies may repeat and rejected attempts are absent. This is not a unique-call cost ledger.",
            "warning":"An early pretest may underestimate long 100-period-history prompts. Use --attempt-log for all-attempt accounting."}

def scan_attempt_usage(path:Path) -> dict:
    """All received attempts, including rejected replies; unknown stays unknown."""
    accounting=summarize_attempts(path)
    records=[json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    starts={r['attempt_id']:r for r in records if r['event']=='request_started'}
    known_cost=0.0
    priced=0
    for row in records:
        if row['event']!='response_received':continue
        start=starts[row['attempt_id']]
        usage=row.get('usage') or {}
        # Never apply Haiku 5.5 prices to another model population.
        if start['provider']!='anthropic' or start['requested_model']!='claude-haiku-5-5' or row.get('served_model')!='claude-haiku-5-5':continue
        i,o=usage.get('input_tokens'),usage.get('output_tokens')
        if any(isinstance(v,bool) or not isinstance(v,int) or v<0 for v in (i,o)):continue
        if usage.get('cache_read_input_tokens',0) or usage.get('cache_creation_input_tokens',0):continue
        known_cost+=estimate_cost(1,i,o)
        priced+=1
    return {'attempt_accounting':accounting,'priced_attempts':priced,
            'unpriced_or_unknown_attempts':accounting['http_attempts']-priced,
            'known_token_cost_estimate_usd':known_cost if priced else None,
            'cost_complete_under_declared_rate_model':priced==accounting['http_attempts'] and priced>0,
            'qualification':'Token-rate estimate, not an invoice. Missing usage, unsupported models and caching are unpriced, never zero. No collection or cost authorization.'}

def estimate_campaign(*,credits_usd:float,input_tokens:float=3500,
                      output_tokens:float=600,reserve_fraction:float=.15,
                      observed:dict|None=None)->dict:
    if credits_usd<0 or not math.isfinite(credits_usd):
        raise ValueError("Credits must be nonnegative and finite")
    if not 0<=reserve_fraction<1:
        raise ValueError("reserve_fraction outside [0,1)")
    if observed:
        input_tokens=observed["mean_input_tokens"]
        output_tokens=observed["mean_output_tokens"]
    counts=stage_counts()
    stage_usd={name:estimate_cost(calls,input_tokens,output_tokens)
               for name,calls in counts.items()}
    grand=sum(stage_usd.values())
    permitted=credits_usd*(1-reserve_fraction)
    return {
        "model":DEFAULT_MODEL["anthropic"],
        "rate_basis":"Haiku 5.5 public pricing, prompts <=100,000 tokens",
        "price_input_usd_per_million":INPUT_USD_PER_M,
        "price_output_usd_per_million":OUTPUT_USD_PER_M,
        "assumed_input_tokens_per_call":input_tokens,
        "assumed_output_tokens_per_call":output_tokens,
        "usage_source":"live_usage_sample" if observed else "scenario_assumptions",
        "usage_sample":observed,
        "expected_calls_by_stage":counts,
        "total_planned_decisions":sum(counts.values()),
        "expected_spend_usd_by_stage":stage_usd,
        "expected_spend_usd":grand,
        "credits_usd":credits_usd,
        "reserve_fraction":reserve_fraction,
        "available_for_spend_after_reserve_usd":permitted,
        "full_plan_fits_assumed_budget":grand <= permitted,
        "estimated_spend_capacity_gap_usd":max(0.0,grand-permitted),
        "required_starting_credits_with_reserve_usd":grand/(1-reserve_fraction),
        "estimated_additional_budget_required_usd":max(0.0,grand/(1-reserve_fraction)-credits_usd),
        "important":"Not a hard spending cap. Actual tokens vary with 100-period history, tokenizer, thinking, retries, model pricing, caching, and API behavior. Do not start paid campaign solely on this estimate."
    }

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credits-usd",type=float,default=3.0)
    parser.add_argument("--input-tokens",type=float,default=3500)
    parser.add_argument("--output-tokens",type=float,default=600)
    parser.add_argument("--reserve-fraction",type=float,default=.15)
    logs=parser.add_mutually_exclusive_group()
    logs.add_argument("--usage-log",type=Path)
    logs.add_argument('--attempt-log',type=Path,help='Reconstruct received-attempt costs, including rejected replies')
    parser.add_argument("--strict-budget",action="store_true",
                        help="Exit nonzero if estimated full design exceeds available credits")
    args=parser.parse_args()
    if args.attempt_log:
        print(json.dumps(scan_attempt_usage(args.attempt_log),indent=2))
        return
    sample=scan_usage_records(args.usage_log) if args.usage_log else None
    output=estimate_campaign(credits_usd=args.credits_usd,
                    input_tokens=args.input_tokens,output_tokens=args.output_tokens,
                    reserve_fraction=args.reserve_fraction,observed=sample)
    print(json.dumps(output,indent=2))
    if args.strict_budget and not output["full_plan_fits_assumed_budget"]:
        raise SystemExit(2)

if __name__=="__main__":
    main()
