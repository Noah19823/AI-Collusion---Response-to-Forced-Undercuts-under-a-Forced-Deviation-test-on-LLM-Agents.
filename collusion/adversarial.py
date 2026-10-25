"""Out-of-model scripted adversarial null.

A nonpunitive agent forecasts the rival's future price from remembered shocks.
It maximizes expected one-period profitability given that forecast, and DOES NOT
have a retaliation objective. If its PI_dyn is negative, this only falsifies the
claim that negative residual uniquely identifies strategic punishment.

Exploratory independent stress test, not part of the original preregistration.
"""
from __future__ import annotations
from dataclasses import dataclass
from itertools import product
from .market import Market
M=Market(quantity_scale=1)
P0=1.90
H=15

@dataclass(frozen=True)
class AlternativeNull:
    scenario:str
    rho:float
    decay:float
    forecast_gain:float
    one:float
    static:float
    dynamic:float

def path(scenario: str) -> list[float]:
    if scenario=="sham":return [P0]*(H+1)
    if scenario=="down":return [P0*.9]+[P0]*H
    if scenario=="up":return [P0*1.1]+[P0]*H
    if scenario=="down_persistent":return [P0*.9]*(H+1)
    if scenario=="up_persistent":return [P0*1.1]*(H+1)
    raise ValueError(scenario)

def policy(qs: list[float],rho:float,decay:float,gain:float) -> list[float]:
    p=[P0]
    forecast_shift=0.0
    markup=P0-M.best_response(P0)
    for k in range(1,len(qs)):
        observed=qs[k-1]
        if abs(observed-P0)>.08:
            forecast_shift=observed-P0
        else:
            forecast_shift*=decay
        # Maximizes expected current profit given a future-price forecast.
        target=markup+M.best_response(observed+gain*forecast_shift)
        p.append(rho*p[-1]+(1-rho)*target)
    return p

def indices(rho:float,decay:float,gain:float,scenario:str) -> AlternativeNull:
    q=path(scenario);q0=path("sham")
    actual=policy(q,rho,decay,gain)
    sham=policy(q0,rho,decay,gain)
    d_hat=0.0;one=static=dynamic=0.0
    for k in range(1,H+1):
        d=actual[k]-sham[k]
        dbr=M.best_response(q[k-1])-M.best_response(q0[k-1])
        d_hat=rho*d_hat+(1-rho)*dbr
        if k==1:one=d-dbr
        static+=d-dbr
        dynamic+=d-d_hat
    return AlternativeNull(scenario,rho,decay,gain,one,static,dynamic)

def grid() -> list[AlternativeNull]:
    return [indices(rho,decay,gain,scenario)
            for scenario,rho,decay,gain in product(("down","up"),
                (.5,.8,.92),(.5,.8,.95),(.25,.5,.75))]
