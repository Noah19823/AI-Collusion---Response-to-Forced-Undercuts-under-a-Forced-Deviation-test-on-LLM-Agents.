"""Reproducible differentiated Bertrand/logit market (Fish/Calvano parameters).

Do not confuse normalized beta=1 profits with the model-facing beta=100 units.
One-product monopoly and two-product joint monopoly are DIFFERENT benchmarks.
"""
from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
from math import exp, isfinite

@dataclass(frozen=True)
class Market:
    a: float = 2.0
    outside: float = 0.0
    mu: float = 0.25
    cost: float = 1.0
    quantity_scale: float = 100.0

    def share(self, own: float, rival: float | None = None) -> float:
        """Stable softmax over outside option and active products."""
        z = [(self.a - own) / self.mu, self.outside / self.mu]
        if rival is not None:
            z.append((self.a - rival) / self.mu)
        pivot = max(z)
        weights = [exp(v - pivot) for v in z]
        return weights[0] / sum(weights)

    def quantity(self, own: float, rival: float | None = None) -> float:
        return self.quantity_scale * self.share(own, rival)

    def profit(self, own: float, rival: float | None = None) -> float:
        return (own - self.cost) * self.quantity(own, rival)

    @staticmethod
    def _bisect(f, lower: float, upper: float) -> float:
        a, b = lower, upper
        fa, fb = f(a), f(b)
        if not fa < 0 < fb:
            raise ValueError(f"No bracket: f(lower)={fa}, f(upper)={fb}")
        for _ in range(100):
            mid = (a + b) / 2
            if f(mid) > 0:
                b = mid
            else:
                a = mid
            if b - a < 1e-12:
                break
        return (a + b) / 2

    def best_response(self, rival: float | None) -> float:
        """FOC: (p-c)*(1-own share)-mu=0."""
        if rival is not None and not isfinite(rival):
            raise ValueError("Rival price must be finite")
        return self._bisect(
            lambda p: (p - self.cost) * (1 - self.share(p, rival)) - self.mu,
            self.cost, self.cost + 20.0)

    def nash(self) -> float:
        return self._bisect(
            lambda p: p - self.best_response(p),
            self.cost + 1e-8, self.cost + 10)

    def joint_monopoly(self, num_products: int = 2) -> float:
        if num_products < 1:
            raise ValueError("num_products must be positive")
        def foc(p: float) -> float:
            w0 = exp(self.outside / self.mu - max(self.outside, self.a-p) / self.mu)
            wp = exp((self.a-p) / self.mu - max(self.outside, self.a-p) / self.mu)
            outside_share = w0 / (w0 + num_products * wp)
            return (p - self.cost) * outside_share - self.mu
        return self._bisect(foc, self.cost, self.cost + 20)

    def reference(self) -> dict:
        return {
            "nash_duopoly": self.nash(),
            "monopoly_one_product": self.joint_monopoly(1),
            "joint_monopoly_two_products": self.joint_monopoly(2),
            "br_1_92": self.best_response(1.92),
            "br_1_66": self.best_response(1.66),
            "profit_1_92_1_92": self.profit(1.92, 1.92),
            "profit_1_66_1_92": self.profit(1.66, 1.92),
            "quantity_scale": self.quantity_scale
        }


# No mutable global market state. Cache only this canonical parameterization.
STANDARD = Market()
@lru_cache(maxsize=65536)
def br(q: float) -> float:
    return STANDARD.best_response(round(float(q), 8))
