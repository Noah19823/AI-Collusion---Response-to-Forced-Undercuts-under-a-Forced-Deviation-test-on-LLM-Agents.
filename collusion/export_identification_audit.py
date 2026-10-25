"""Produce a reproducible, local-only, checksummed exploratory synthetic audit.

Usage: python3 -m collusion.export_identification_audit
Never include logs/ in PR or represent these results as LLM observations.
"""
from __future__ import annotations
import csv
import json
from dataclasses import asdict
from random import Random
from .runner import run_folder, save_json, digest
from .identification_audit import (
    structural_equivalence,forecast_deterrence_cases,
    shock_sweep, identification_summary, P0)

def save_csv(folder, name, rows):
    target=folder/name
    if not rows:raise ValueError("Empty evidence")
    with target.open("x",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]))
        w.writeheader();w.writerows(rows)
    return digest(target.read_bytes())

def main():
    summary=identification_summary()
    fpath=run_folder("offline_identifiability")
    rng=Random(20261025)
    paths={
      "one_period":[P0*.9]+[P0]*14,
      "persistent":[P0*.9]*15,
      "zigzag":[P0+(.1 if j%2 else -.1) for j in range(15)],
      "random":[max(1.4,min(2.2,P0+rng.uniform(-.25,.25))) for _ in range(15)]
    }
    equivalences=[]
    for label,q in paths.items():
        for rho in (0,.5,.8,.92):
            for delta in (.05,.10):
                result=structural_equivalence(q,rho=rho,delta=delta)
                equivalences.append({"path":label,"rho":rho,"penalty_delta":delta,
                   "max_price_difference":result["max_price_disagreement"],
                   "max_inverse_residual":result["max_optimum_residual"]})
    forecasts=[asdict(x) for x in forecast_deterrence_cases()]
    deviations=shock_sweep()
    shas={
       "equivalence.csv":save_csv(fpath,"equivalence.csv",equivalences),
       "forecast_profit_controls.csv":save_csv(fpath,"forecast_profit_controls.csv",forecasts),
       "deviation_size_sweep.csv":save_csv(fpath,"deviation_size_sweep.csv",deviations)
    }
    # Avoid introducing absolute workstation paths in public reports.
    save_json(fpath/"completion.json",{
       "classification":"EXPLORATORY_SYNTHETIC_ONLY",
       "reproducible_command":"python3 -m collusion.export_identification_audit",
       "counts":{"equivalence":len(equivalences),
                 "forecast_controls":len(forecasts),
                 "size_grid":len(deviations)},
       "summary":summary,
       "source_file_sha256":digest(__import__("pathlib").Path(__file__).read_bytes()),
       "sha256_files":shas})
    print(json.dumps({"evidence_dir":str(fpath),"summary":summary,
                      "sha256_files":shas},indent=2))

if __name__=="__main__":
    main()
