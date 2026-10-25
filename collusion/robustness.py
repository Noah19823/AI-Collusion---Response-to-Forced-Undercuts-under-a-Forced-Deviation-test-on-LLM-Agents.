"""Conservative all-rho upper-CI bound for the existing bootstrap statistic.

No estimator or confidence level is changed. Each run mean is a polynomial
in rho. Exact rational interval Horner bounds enclose that polynomial on
each subinterval; outward rounding encloses each bootstrap mean and its
97.5th percentile. Failure to certify is inconclusive, never evidence of a
sign reversal. The 11-point descriptive scan is not a substitute for this.
"""
from __future__ import annotations

from fractions import Fraction
import math


def _run_polynomial(features: list[dict]) -> list[Fraction]:
    degree=max(len(f['br_diff']) for f in features)
    coefficients=[Fraction(0) for _ in range(degree+1)]
    for f in features:
        d,b=f['diff'],f['br_diff']
        if len(d)!=len(b) or not b:
            raise ValueError('Invalid paired features')
        coefficients[0]+=sum(map(Fraction,d))-sum(map(Fraction,b))
        for j,value in enumerate(b):
            coefficients[len(b)-j]+=Fraction(value)
    return [c/len(features) for c in coefficients]


def _interval_upper(coefficients: list[Fraction], lower: Fraction, upper: Fraction) -> Fraction:
    low=high=coefficients[-1]
    for coefficient in reversed(coefficients[:-1]):
        products=(low*lower,low*upper,high*lower,high*upper)
        low=min(products)+coefficient
        high=max(products)+coefficient
    return high


def _outward(value: Fraction) -> float:
    return math.nextafter(float(value),math.inf)


def _mean_upper(values: dict, sample: list[int]) -> float:
    total=0.0
    for i in sample:
        total=math.nextafter(total+values[i],math.inf)
    return math.nextafter(total/len(sample),math.inf)


def _percentile_upper(values: list[float]) -> float:
    ordered=sorted(values)
    index=Fraction(975,1000)*(len(ordered)-1)
    i=index.numerator//index.denominator
    fraction=index-i
    j=min(i+1,len(ordered)-1)
    return _outward(Fraction(ordered[i])*(1-fraction)+Fraction(ordered[j])*fraction)


def certify_rho_interval(groups: dict, sampled_ids: list[list[int]],
                         interval: list[float], *, subdivisions: int=32) -> dict:
    lower,upper=interval
    if not 0<=lower<=upper<1 or not sampled_ids or subdivisions<1:
        raise ValueError('Invalid rho interval/bootstrap samples')
    polynomials={i:_run_polynomial(features) for i,features in groups.items()}
    a,b=Fraction(lower),Fraction(upper)
    count=1 if a==b else subdivisions
    checks=[]
    for j in range(count):
        lo=a+(b-a)*j/count
        hi=a+(b-a)*(j+1)/count
        run_bounds={i:_outward(_interval_upper(c,lo,hi)) for i,c in polynomials.items()}
        bound=_percentile_upper([_mean_upper(run_bounds,sample) for sample in sampled_ids])
        checks.append({'rho_low':float(lo),'rho_high':float(hi),'ci_high_upper_bound':bound})
    return {'certified':all(c['ci_high_upper_bound']<0 for c in checks),
            'method':'exact-rational interval Horner with outward-rounded bootstrap upper-quantile bounds',
            'scope':'every rho in the closed reported rho interval; existing 97.5th percentile statistic',
            'subintervals':checks,
            'qualification':'Conservative certification; failure to certify is inconclusive, not a detected sign reversal.'}
