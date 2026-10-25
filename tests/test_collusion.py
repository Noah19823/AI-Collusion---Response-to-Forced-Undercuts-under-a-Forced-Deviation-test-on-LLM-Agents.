"""Independent runnable tests. Run: python3 -m unittest discover -s tests -v"""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from collusion.market import Market
from collusion.scripted import simulate,grid
from collusion.client import MockClient,validate_reply
from collusion.runner import base_episode,fork_episode,load_jsonl
from collusion.analysis import verify_pair,evaluate_pair

class MarketTests(unittest.TestCase):
    def test_benchmarks(self):
        m=Market(quantity_scale=1)
        for got,expected in [(m.nash(),1.47292666003),
            (m.joint_monopoly(1),1.80198500789),
            (m.joint_monopoly(2),1.92498091902),
            (m.best_response(1.92),1.65990850258),
            (m.best_response(1.66),1.55399659653),
            (m.profit(1.92,1.92),.33747237861),
            (m.profit(1.66,1.92),.40990849218)]:
            self.assertAlmostEqual(got,expected,places=8)
    def test_units(self):
        n=Market(quantity_scale=1); s=Market(quantity_scale=100)
        self.assertAlmostEqual(s.profit(1.66,1.92)/n.profit(1.66,1.92),100)
        self.assertAlmostEqual(s.best_response(1.92),n.best_response(1.92))
    def test_pretest_not_joint_monopoly(self):
        m=Market()
        self.assertGreater(m.joint_monopoly(2)-m.joint_monopoly(1),.12)

class SyntheticTests(unittest.TestCase):
    def test_seven_fixtures(self):
        fixtures=[
            (0,0,False,0,0,0),
            (0,.1,False,-.1,-1,-1),
            (.5,.1,False,.001,-.997,-.997),
            (.92,0,False,.094,.029,0),
            (.92,.1,False,.086,-.542,-.571),
            (.92,0,True,.094,.836,0),
            (.92,.1,True,.086,.265,-.571)
        ]
        for rho,delta,persists,a,b,c in fixtures:
            with self.subTest(rho=rho,delta=delta,persists=persists):
                x=simulate(rho,delta,persists=persists)
                for got,expected in zip((x.one,x.static,x.dynamic),(a,b,c)):
                    self.assertAlmostEqual(got,expected,delta=.0015)
    def test_24_noisy_cells(self):
        cells=grid()
        self.assertEqual(len(cells),24)
        self.assertTrue(all(r["classified"]==r["expected"] for r in cells),
            [(r["rho"],r["delta"],r["mode"],r["classified"]) for r in cells
             if r["classified"]!=r["expected"]])
    def test_wrong_rho_false_punishment(self):
        zero=simulate(.92,0,persists=True,baseline_rho=.92)
        wrong=simulate(.92,0,persists=True,baseline_rho=.97)
        self.assertAlmostEqual(zero.dynamic,0,places=10)
        self.assertLess(wrong.dynamic,-.30)
    def test_p3_raw_comparison_fails_on_nonpunisher(self):
        x=simulate(.92,0,persists=False)
        self.assertLess(x.dynamic,x.one)  # Yet delta=0: no retaliation!
    def test_clean_reply_validation(self):
        good=validate_reply('{"chosen_price":1.7,"plans":"test"}')
        self.assertEqual(good["chosen_price"],1.7)
        for bad in ('{"chosen_price":NaN}', '{"chosen_price":true}',
                    '{"chosen_price":-0.1}','not JSON'):
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                validate_reply(bad)

class BranchTests(unittest.TestCase):
    def test_smoke_and_invariants(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("collusion.runner.LOGROOT",Path(folder)):
                base=asyncio.run(base_episode(MockClient(seed=42),"mock",
                    "synthetic-sticky-policy-v1",rounds=8,seed=42))
                sham=asyncio.run(fork_episode(MockClient(seed=42),"mock",
                    "synthetic-sticky-policy-v1",base,4,3,"Firm A","sham",42))
                cut=asyncio.run(fork_episode(MockClient(seed=42),"mock",
                    "synthetic-sticky-policy-v1",base,4,3,"Firm A","cut",42))
                sham2=asyncio.run(fork_episode(MockClient(seed=42),"mock",
                    "synthetic-sticky-policy-v1",base,4,3,"Firm A","sham2",42))
                meta,rs,rc,other=verify_pair(base,sham,cut)
                self.assertEqual(meta["fork_period"],4)
                self.assertEqual(other,"Firm B")
                # The exact no-cut continuation is reproducible in MOCK mode.
                first=load_records(sham/"continuation.jsonl")
                second=load_records(sham2/"continuation.jsonl")
                # Branch label differs intentionally; observed behavior must not.
                first[0]["intervention"]["kind"]="placebo"
                second[0]["intervention"]["kind"]="placebo"
                self.assertEqual(first,second)
                raw=load_jsonl(base/"rounds.jsonl")
                expected=.9*raw[2]["actors"]["Firm A"]["executed_price"]
                self.assertAlmostEqual(rc[0]["actors"]["Firm A"]["executed_price"],expected)
                self.assertEqual(rc[0]["actors"]["Firm B"]["executed_price"],
                                 rs[0]["actors"]["Firm B"]["executed_price"])
                self.assertNotEqual(rc[1]["actors"]["Firm B"]["prompt"],
                                    rs[1]["actors"]["Firm B"]["prompt"])
                result=evaluate_pair(base,sham,cut,.85)
                self.assertEqual(result["scope"],"SCRIPTED_MOCK")
                self.assertEqual(result["horizon"],3)
                self.assertLess(abs(result["G_H"]),10)
                # Verify primitive tampering cannot silently pass.
                original=(cut/"continuation.jsonl").read_bytes()
                with (cut/"continuation.jsonl").open("ab") as f:
                    f.write(b"\n")
                with self.assertRaisesRegex(ValueError,"Corrupt"):
                    verify_pair(base,sham,cut)
                (cut/"continuation.jsonl").write_bytes(original)

def load_records(p: Path):
    return [json.loads(x) for x in p.read_text().splitlines() if x]

if __name__=="__main__":
    unittest.main()
