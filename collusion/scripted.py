"""Part 1 scripted-agent controls. Synthetic results only; no LLM evidence.

Noise-free fixtures reproduce the frozen protocol; noisy resamples test
statistical classification. P1's scripted grid is an in-family positive control,
not a universal proof of punishment identifiability.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from itertools import product
from random import Random
from statistics import mean
from .market import Market

MARKET = Market(quantity_scale=1)
H = 15
K = 10
P0 = 1.90

@dataclass(frozen=True)
class Indices:
    one: float
    static: float
    dynamic: float

def simulate(rho: float, delta: float, *, persists: bool = False,
             baseline_rho: float | None = None, noise_sd: float = 0.0,
             seed: int = 0, h: int = H, k: int = K) -> Indices:
    if not 0 <= rho < 1 or delta < 0 or h < 1 or k < 1:
        raise ValueError("Bad scripted simulation parameters")
    rhohat = rho if baseline_rho is None else baseline_rho
    if not 0 <= rhohat < 1:
        raise ValueError("Bad baseline rho")
    rng = Random(seed)
    # Independent innovations in the cut/sham branches: conservative noise test.
    innovations = [(rng.gauss(0, noise_sd), rng.gauss(0, noise_sd)) for _ in range(h)]
    cut_price = MARKET.best_response(P0)
    markup = P0 - MARKET.best_response(P0)
    pc = ps = P0
    dhat = one = static = dynamic = 0.0
    for step in range(1, h+1):
        qc = cut_price if (persists or step == 1) else P0
        dbr = MARKET.best_response(qc) - MARKET.best_response(P0)
        target_cut = markup + MARKET.best_response(qc) - (delta if step <= k else 0.0)
        target_sham = markup + MARKET.best_response(P0)
        ncut, nsham = innovations[step-1]
        pc = rho * pc + (1 - rho) * target_cut + ncut
        ps = rho * ps + (1 - rho) * target_sham + nsham
        diff = pc - ps
        dhat = rhohat * dhat + (1-rhohat) * dbr
        if step == 1:
            one = diff - dbr
        static += diff - dbr
        dynamic += diff - dhat
    return Indices(one, static, dynamic)

def quantile(xs: list[float], q: float) -> float:
    if not xs: raise ValueError("Empty quantile")
    vals = sorted(xs)
    x = (len(vals)-1)*q
    i = int(x)
    return vals[i] if i >= len(vals)-1 else vals[i]*(1-x+i)+vals[i+1]*(x-i)

def grid(*, repeats: int = 50, noise_sd: float = .01, seed: int = 20261025) -> list[dict]:
    if repeats < 10: raise ValueError("Need at least ten repeats")
    rows = []
    for mode, rho, delta in product(("impulse","persist"), (0, .5, .8, .92), (0, .05, .10)):
        observed = [simulate(rho,delta,persists=(mode=="persist"),
                   noise_sd=noise_sd,seed=seed + j*101 + int(rho*1000)*17+
                   int(delta*1000)*41+(1 if mode=="persist" else 0)*733)
                   for j in range(repeats)]
        avg = {key:mean(getattr(x,key) for x in observed) for key in ("one","static","dynamic")}
        vals = [x.dynamic for x in observed]
        # CI for the MEAN, not for the distribution of per-seed outcomes.
        boot = Random(seed+741).choices
        brng = Random(seed+int(rho*1000)+int(delta*1000)*37+(3 if mode=="persist" else 0))
        boot_means = [mean(brng.choices(vals,k=len(vals))) for _ in range(1000)]
        lo,hi = quantile(boot_means,.025),quantile(boot_means,.975)
        expected = "nonpunisher" if delta==0 else "punisher"
        classified = "punisher" if hi < 0 else ("nonpunisher" if lo<=0<=hi else "other")
        rows.append(dict(mode=mode,rho=rho,delta=delta,repeats=repeats,
                         noise_sd=noise_sd,expected=expected,classified=classified,
                         ci_low=lo,ci_high=hi,**avg))
    return rows
