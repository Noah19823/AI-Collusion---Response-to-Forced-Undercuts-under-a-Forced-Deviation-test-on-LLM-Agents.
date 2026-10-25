"""Focused independent falsification regression suite. Offline only."""
import math
import unittest
from random import Random

from collusion.market import Market
from collusion.identification_audit import (
    inverse_best_response, structural_equivalence,
    profit_derivative_wrt_rival, forecast_deterrence_cases,
    threshold_gain, shock_sweep, identification_summary)

M=Market(quantity_scale=1)

class StructuralEquivalenceTests(unittest.TestCase):
    def test_inverse_best_response(self):
        for q in (1.35,1.4,1.55,1.65,1.9,2.0,2.2,2.5):
            with self.subTest(q=q):
                self.assertAlmostEqual(inverse_best_response(M.best_response(q)),q,delta=1e-8)
    def test_bad_inverse_input_abstains(self):
        for p in (float("nan"),float("inf"),1.0,1.249999):
            with self.subTest(p=p):
                with self.assertRaises(ValueError):
                    inverse_best_response(p)
    def test_equivalence_at_multiple_horizons_and_shock_paths(self):
        rng=Random(20261025)
        programs=[
            [1.9]*15,[1.71]+[1.9]*14,[1.71]*15,
            [1.9 + (-.10 if i%2==0 else .15) for i in range(15)],
            [rng.uniform(1.55,2.20) for _ in range(15)]
        ]
        count=0
        for p in programs:
            for rho in (0,.5,.8,.92):
                for penalty in (.05,.10):
                    with self.subTest(start=p[0],rho=rho,penalty=penalty):
                        trace=structural_equivalence(p,rho=rho,delta=penalty)
                        self.assertLess(trace["max_price_disagreement"],1e-10)
                        self.assertLess(trace["max_optimum_residual"],1e-10)
                        self.assertEqual(len(trace["prices_punitive"]),16)
                        count+=1
        self.assertEqual(count,40)
    def test_no_revelation_of_unobserved_motive(self):
        q=[1.71]+[1.9]*14
        a=structural_equivalence(q,rho=.92,delta=.1)
        for p,f in zip(a["prices_punitive"],a["prices_forecasting"]):
            self.assertAlmostEqual(p,f,delta=1e-12)
        self.assertLess(a["implied_rival_prices"][0],q[0])
        # This construction only shows that a *different forecast* can rationalize
        # the same price; it does not establish whether the forecast is correct.
    def test_profit_derivative_is_strictly_positive_at_positive_margins(self):
        eps=1e-5
        for p in (1.20,1.40,1.71,1.90,2.10):
            for q in (1.35,1.70,1.90,2.20):
                analytical=profit_derivative_wrt_rival(p,q)
                finite=(M.profit(p,q+eps)-M.profit(p,q-eps))/(2*eps)
                self.assertGreater(analytical,0)
                self.assertAlmostEqual(analytical,finite,delta=1e-8)

class ProfitMechanismTests(unittest.TestCase):
    def test_forecast_controls_defeat_both_indicators(self):
        cases=forecast_deterrence_cases()
        self.assertEqual(len(cases),27)
        self.assertTrue(all(x.PI_dynamic<0 for x in cases))
        self.assertTrue(all(x.G_responder_direct<0 for x in cases))
        self.assertEqual(sum(x.G_total<0 for x in cases),22)
        exemplar=next(x for x in cases if (x.rho,x.decay,x.gain)==(.8,.8,.75))
        self.assertAlmostEqual(exemplar.immediate_gain,.0615800344,delta=1e-8)
        self.assertAlmostEqual(exemplar.G_total,-.10011582205,delta=1e-8)
    def test_single_ten_percent_cut_not_global_deterrence(self):
        # Exactly as defined in this deliberately simplified scripted threshold policy.
        near=threshold_gain(.095)
        exact=threshold_gain(.10)
        self.assertFalse(near["triggered"])
        self.assertTrue(exact["triggered"])
        self.assertGreater(near["G_H"],0)
        self.assertLess(exact["G_H"],0)
        self.assertAlmostEqual(near["G_H"],.02454449611,delta=1e-8)
        self.assertAlmostEqual(exact["G_H"],-.43572074307,delta=1e-8)
        best=max(shock_sweep(),key=lambda v:v["G_H"])
        self.assertGreater(best["G_H"],0)
        self.assertAlmostEqual(best["cut_percent"],8.5,delta=1e-8)
    def test_summary_is_explicitly_synthetic(self):
        z=identification_summary()
        self.assertEqual(z["equivalence_cases"],32)
        self.assertEqual(z["forecast_negative_dynamic"],27)
        self.assertEqual(z["forecast_negative_direct_gain"],27)
        self.assertEqual(z["forecast_total_unprofitable"],22)
        self.assertLess(z["max_equivalence_error"],1e-10)
        self.assertIn("No empirical LLM",z["note"])

if __name__=="__main__":
    unittest.main()
