"""Estimate rho from finished base runs, before any fork runs.

Uses the same shown-price (two-decimal) estimator as collusion.inference, so the
number posted before forks is the one the analysis uses.

    python3 -m collusion.rho --base-list logs/live_base_census.txt
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from .campaign import load_base_list
from .inference import fit_pooled_rho, pooled_rho_diagnostics, rho_sufficient_stats
from .census import validate_bases


def estimate(bases: list[Path], max_period: int = 75) -> dict:
    validate_bases(bases,current_protocol=True)
    stats = [rho_sufficient_stats(b, max_period) for b in bases]
    pooled = fit_pooled_rho(stats)
    per_run = {str(b): fit_pooled_rho([s]) for b, s in zip(bases, stats)}
    return {"n_runs": len(bases), "max_period": max_period,
            "pooled_rho": pooled,
            'pooled_diagnostics':pooled_rho_diagnostics(stats),
            'per_run_diagnostics':{str(b):pooled_rho_diagnostics([s]) for b,s in zip(bases,stats)},
            "decision": "RHO_IDENTIFIED" if pooled is not None else "ABSTAIN_RHO_NOT_IDENTIFIABLE",
            "per_run_rho": per_run}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base-list", required=True, type=Path)
    p.add_argument("--max-period", type=int, default=75)
    args = p.parse_args()
    print(json.dumps(estimate(load_base_list(args.base_list), args.max_period), indent=2))


if __name__ == "__main__":
    main()
