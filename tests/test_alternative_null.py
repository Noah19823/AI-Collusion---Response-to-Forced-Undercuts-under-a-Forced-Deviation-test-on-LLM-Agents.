"""Tests for out-of-family nonpunitive mechanisms and identifiable rho fixtures."""
import json
import tempfile
import unittest
from pathlib import Path

from collusion.adversarial import grid,indices
from collusion.analysis import estimate_rho
from collusion.inference import fit_pooled_rho,rho_sufficient_stats
from collusion.market import Market

class OutOfModelTests(unittest.TestCase):
    def test_nonpunitive_forecast_misread(self):
        x=grid()
        down=[r for r in x if r.scenario=="down"]
        up=[r for r in x if r.scenario=="up"]
        self.assertEqual(len(down),27)
        self.assertEqual(len(up),27)
        self.assertTrue(all(r.dynamic<0 for r in down))
        self.assertTrue(all(r.dynamic>0 for r in up))
        # Even the upward perturbation check would fail to expose this
        # alternative legitimate/non-retaliatory forecasting policy.
        self.assertAlmostEqual(indices(.8,.9,.75,"down").dynamic,-.3702,delta=.0002)

    def test_rho_can_be_identified_on_varied_visible_prices(self):
        m=Market(quantity_scale=1)
        rho=.8
        markup=.24
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            base_dirs=[]
            for j in range(12):
                d=base/f"b{j}"
                d.mkdir()
                history=[]
                pa=1.60+j*.005
                pb=2.22-j*.007
                for t in range(1,100):
                    previous_a,previous_b=pa,pb
                    if t>1:
                        # Agent uses rounded historical prices, just like
                        # the live Fish-style prompts. No punishment.
                        pa=rho*round(previous_a,2)+(1-rho)*(m.best_response(round(previous_b,2))+markup)
                        pb=rho*round(previous_b,2)+(1-rho)*(m.best_response(round(previous_a,2))+markup)
                    history.append({"period":t,"actors":{
                        "Firm A":{"executed_price":pa},
                        "Firm B":{"executed_price":pb}}})
                (d/"rounds.jsonl").write_text("".join(json.dumps(x)+"\n" for x in history))
                base_dirs.append(d)
            inferred=estimate_rho(base_dirs,max_period=75)
            pooled=fit_pooled_rho([rho_sufficient_stats(d,75) for d in base_dirs])
            self.assertAlmostEqual(inferred["rho_unrestricted"],rho,delta=1e-8)
            self.assertAlmostEqual(pooled,rho,delta=1e-8)

    def test_constant_visible_prices_cannot_identify_rho(self):
        m=Market()
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)
            recs=[]
            for t in range(1,101):
                recs.append({"period":t,"actors":{
                    "Firm A":{"executed_price":1.90001},
                    "Firm B":{"executed_price":1.90002}}})
            (d/"rounds.jsonl").write_text("".join(json.dumps(x)+"\n" for x in recs))
            with self.assertRaisesRegex(ValueError,"singular"):
                estimate_rho([d])
            self.assertIsNone(fit_pooled_rho([rho_sufficient_stats(d)]))
if __name__=="__main__":
    unittest.main()
