"""Exploratory falsification: structural observational equivalence and shock-size stress.

These are DEMONSTRATIONS IN SCRIPTED POLICIES, not empirical LLM observations.
A constructive belief-based price setter can exactly reproduce a punitive
price path because the monotone best-response function is invertible locally.
The implied beliefs need not be accurate, calibrated, or sincerely held by an LLM.

The threshold-deviation counterexample echoes related analyses already in
Tran & Yu (2026) and Lopes de Moraes & De-Losso (2026); no novelty is claimed.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import exp, log, isfinite
from random import Random
from .market import Market
from .adversarial import grid as forecasting_grid, path, policy, P0, H

M = Market(quantity_scale=1.0)
K=10

def inverse_best_response(own_optimum: float, market: Market=M) -> float:
    """Rival price q satisfying BR(q) = own_optimum.

    For sigma=0 Bertrand logit:
    share* = 1 - mu/(p - cost)
    exp((a-q)/mu) = exp((a-p)/mu) * (1/share* - 1) - exp(a0/mu)
    The domain excludes unreachable prices. This is an inverse construction,
    not an observationally estimated opponent forecast.
    """
    p=float(own_optimum)
    if not isfinite(p) or p <= market.cost+market.mu:
        raise ValueError("Price outside economic interior")
    s=1-market.mu/(p-market.cost)
    rival_weight=exp((market.a-p)/market.mu)*(1/s-1)-exp(market.outside/market.mu)
    if rival_weight<=0 or not isfinite(rival_weight):
        raise ValueError("Target best response is not reachable by a finite rival price")
    return market.a-market.mu*log(rival_weight)

def structural_equivalence(q_path:list[float], *, rho:float, delta:float,
                           punishment_periods:int=K, p0:float=P0) -> dict:
    """Same realized responder prices under two different posited mechanisms.

    Punitive policy: target = markup+BR(q)-delta in active window.
    Belief policy: target = markup+BR(q_hat) where
      BR(q_hat)=BR(q)-delta (a forecast, not a penalty term).
    Exogenous cutter trajectory is held identical. This can be embedded in a
    closed loop with a deterministic cutter by induction.
    """
    if not 0<=rho<1 or delta<0 or punishment_periods<1: raise ValueError("Bad parameters")
    markup=p0-M.best_response(p0)
    punished=[p0]; forecast=[p0]; implied=[]
    for h,q in enumerate(q_path,1):
        is_active=h<=punishment_periods
        shift=delta if is_active else 0.0
        best=M.best_response(q)
        price_forecast=inverse_best_response(best-shift)
        punitive_target=markup+best-shift
        belief_target=markup+M.best_response(price_forecast)
        punished.append(rho*punished[-1]+(1-rho)*punitive_target)
        forecast.append(rho*forecast[-1]+(1-rho)*belief_target)
        implied.append(price_forecast)
    return {"prices_punitive":punished,"prices_forecasting":forecast,
            "implied_rival_prices":implied,
            "max_price_disagreement":max(abs(a-b) for a,b in zip(punished,forecast)),
            "max_optimum_residual":max(abs(
                M.best_response(qf)-(M.best_response(q)-(
                    delta if h<=punishment_periods else 0.0)))
                for h,(q,qf) in enumerate(zip(q_path,implied),1))}

def profit_derivative_wrt_rival(own:float,rival:float,market:Market=M) -> float:
    """Exact derivative d profit_A / d price_B = scale*(own-c)*share_A*share_B / mu."""
    if own<=market.cost:
        raise ValueError("Strictly positive margin required for positive derivative")
    own_s=market.share(own,rival)
    rival_s=market.share(rival,own)
    return market.quantity_scale*(own-market.cost)*own_s*rival_s/market.mu

@dataclass(frozen=True)
class ForecastDeterrence:
    rho:float
    decay:float
    gain:float
    PI_dynamic:float
    immediate_gain:float
    G_total:float
    G_responder_direct:float

def forecast_deterrence_cases() -> list[ForecastDeterrence]:
    """P4 stress test with fixed A continuation as in the independent fixture.

    A cuts from 1.9 to 1.71 at t=0 then returns to 1.9 at t>=1;
    the responder forecasts a price war, but never optimizes deterrence.
    """
    qc=path("down"); qs=path("sham")
    results=[]
    for x in forecasting_grid():
        if x.scenario!="down": continue
        cut_B=policy(qc,x.rho,x.decay,x.forecast_gain)
        sham_B=policy(qs,x.rho,x.decay,x.forecast_gain)
        dhat=0.0
        total=0.0;direct=0.0;first=0.0
        for h in range(H+1):
            if h:
                dhat=x.rho*dhat+(1-x.rho)*(M.best_response(qc[h-1])-M.best_response(qs[h-1]))
            a_cut=qc[h];a_sham=qs[h]
            gain=M.profit(a_cut,cut_B[h])-M.profit(a_sham,sham_B[h])
            if h==0:first=gain
            total+=gain
            direct+=M.profit(a_cut,cut_B[h])-M.profit(a_cut,sham_B[h]+dhat)
        results.append(ForecastDeterrence(x.rho,x.decay,x.forecast_gain,
                   x.dynamic,first,total,direct))
    return results

def threshold_gain(fraction:float, *, threshold:float=.10, punishment_delta:float=.10,
                   rho:float=.8,horizon:int=15, punishment_periods:int=K,
                   starting_price:float=P0) -> dict:
    """One forced cut, A returns to its old price, defender has 10%-trigger rule.

    Deliberately simplified scripted scenario: NOT the real Fish/Haiku
    endogenous continuation and NOT an optimal multi-period deviation policy.
    """
    if not 0<=fraction<.5 or not 0<=rho<1: raise ValueError("Bad parameters")
    a_shock=starting_price*(1-fraction)
    B=starting_price
    markup=starting_price-M.best_response(starting_price)
    immediate=M.profit(a_shock,B)-M.profit(starting_price,B)
    total=immediate
    for h in range(1,horizon+1):
        shown_a = a_shock if h==1 else starting_price
        target=markup+M.best_response(shown_a)
        if fraction>=threshold-1e-12 and h<=punishment_periods:
            target-=punishment_delta
        B=rho*B+(1-rho)*target
        total+=M.profit(starting_price,B)-M.profit(starting_price,starting_price)
    return {"cut_percent":100*fraction,
            "immediate_gain":immediate,"G_H":total,
            "triggered":fraction>=threshold-1e-12}

def shock_sweep(step:float=.005,max_fraction:float=.25):
    if step<=0:raise ValueError("step positive")
    n=round(max_fraction/step)
    return [threshold_gain(i*step) for i in range(n+1)]

def identification_summary():
    rng=Random(20261025)
    paths={
        "one_period":[P0*.9]+[P0]*14,
        "persistent":[P0*.9]*15,
        "zigzag":[P0+(.1 if j%2 else -.1) for j in range(15)],
        "random":[max(1.4,min(2.2,P0+rng.uniform(-.25,.25))) for _ in range(15)]
    }
    reps=[]
    for name,p in paths.items():
        for rho in (0,.5,.8,.92):
            for delta in (.05,.10):
                result=structural_equivalence(p,rho=rho,delta=delta)
                reps.append({"path":name,"rho":rho,"delta":delta,
                     "max_price_disagreement":result["max_price_disagreement"]})
    cases=forecast_deterrence_cases()
    sweep=shock_sweep()
    return {
      "equivalence_cases":len(reps),
      "max_equivalence_error":max(x["max_price_disagreement"] for x in reps),
      "forecast_cases":len(cases),
      "forecast_negative_dynamic":sum(x.PI_dynamic<0 for x in cases),
      "forecast_negative_direct_gain":sum(x.G_responder_direct<0 for x in cases),
      "forecast_total_unprofitable":sum(x.G_total<0 for x in cases),
      "shock_095":threshold_gain(.095),
      "shock_100":threshold_gain(.10),
      "shock_best_on_grid":max(sweep,key=lambda x:x["G_H"]),
      "note":"All deliberately constructed scripted tests. No empirical LLM inference."}
