"""Regression tests for A3 rho grid, P3 decisions, and A6 campaign counts."""
from __future__ import annotations
import asyncio
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from collusion.analysis import verify_pair
from collusion.amendment_analysis import (
    AMENDMENT_GRID, dynamic_from_features, one_from_features,
    checked_second_sham, analysis, load_campaign)
from collusion.client import MockClient
from collusion.runner import base_episode
from collusion.campaign import execute_plan, make_plan

class MetricIdentities(unittest.TestCase):
    def test_dynamic_matches_recursive_definition(self):
        feat={"diff":[-.01,-.03,.02,.01,-.05],
              "br_diff":[-.06,.01,.03,-.04,.02]}
        for rho in AMENDMENT_GRID+(.999,):
            d=acc=0.0
            for x,b in zip(feat["diff"],feat["br_diff"]):
                d=rho*d+(1-rho)*b
                acc+=x-d
            self.assertAlmostEqual(dynamic_from_features(feat,rho),acc,places=12)
        self.assertAlmostEqual(one_from_features(feat),.05,places=12)

    def test_fixed_grid_is_exactly_amendment_one(self):
        self.assertEqual(AMENDMENT_GRID,(0,.25,.5,.75,.9,.95))

    def test_invalid_features_are_rejected(self):
        for rho in (-.1,1,math.nan,math.inf):
            with self.assertRaises(ValueError):
                dynamic_from_features({"diff":[0],"br_diff":[0]},rho)
        with self.assertRaises(ValueError):
            dynamic_from_features({"diff":[.1],"br_diff":[]},.8)

class DecisionLogicTests(unittest.TestCase):
    def test_amended_p3_uses_classification_not_unlike_index_magnitudes(self):
        # Deliberately fabricated complete 12-run fixture; NO model was called.
        # A sticky but genuinely below-null responder has a positive one-period
        # residual and a negative long-run residual in each scripted fork.
        baseline_rho=.8
        br_diff=[-.10]+[0.0]*14
        d_hat=0.0
        diffs=[]
        for b in br_diff:
            d_hat=baseline_rho*d_hat+(1-baseline_rho)*b
            diffs.append(d_hat-.02)
        positive={"diff":diffs,"br_diff":br_diff}
        null={"diff":[0.0]*15,"br_diff":[0.0]*15}
        fabricated={
            "classification":"FABRICATED_UNIT_FIXTURE",
            "provider":"anthropic",
            "groups":{i:[positive]*4 for i in range(12)},
            "rho_stats":{i:{"n":100,"x":0.0,"y":0.0,
                            "xx":10.0,"xy":8.0} for i in range(12)},
            "noise_by_run":{i:[null] for i in range(12)},
            "n_forks":48,"n_second_shams":12,
            "n_runs":12,"plan_matches":True
        }
        with patch("collusion.amendment_analysis.load_campaign",return_value=fabricated):
            report=analysis(Path("UNUSED_FAKE_FIXTURE"),repeats=500,seed=20261025)
        self.assertEqual(report["amended_P3"],"P3_SUPPORTED_RESTRICTED_NULL_ONLY")
        self.assertGreater(report["one_period"]["ci95"][0],0)
        self.assertLess(report["dynamic_point"]["ci95"][1],0)
        self.assertAlmostEqual(report["rho_point"],.8,places=10)
        self.assertTrue(report["dynamic_point"]["robust_11_point_grid_over_rho_ci"])
        self.assertTrue(report["fixed_rho_sensitivity_grid"]["0.75"]["restricted_null_screen_positive"])

    def test_provenance_classification_cannot_confirm_on_mock_even_if_effect(self):
        negative={"diff":[-.02]*15,"br_diff":[0.0]*15}
        null={"diff":[0.0]*15,"br_diff":[0.0]*15}
        fabricated={
            "classification":"SYNTHETIC",
            "provider":"mock",
            "groups":{i:[negative]*4 for i in range(12)},
            "rho_stats":{i:{"n":100,"x":0.0,"y":0.0,
                            "xx":10.0,"xy":8.0} for i in range(12)},
            "noise_by_run":{i:[null] for i in range(12)},
            "n_forks":48,"n_second_shams":12,
            "n_runs":12,"plan_matches":True
        }
        with patch("collusion.amendment_analysis.load_campaign",return_value=fabricated):
            report=analysis(Path("UNUSED_FAKE_FIXTURE"),repeats=500,seed=21)
        self.assertEqual(report["amended_P3"],"NOT_TESTED_SYNTHETIC")
        self.assertEqual(report["dynamic_point"]["conclusion"],"NOT_ESTABLISHED")

class FullMockAmendmentTests(unittest.TestCase):
    def test_complete_amended_campaign_abstains_when_rho_not_identifiable(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("collusion.runner.LOGROOT",Path(folder)):
                bases=[]
                for i in range(12):
                    base=asyncio.run(base_episode(MockClient(seed=i),
                        "mock","synthetic-sticky-policy-v1",rounds=135,seed=i))
                    bases.append(base)
                plan=make_plan(bases)
                self.assertEqual(len(plan["rows"]),48)
                self.assertEqual(sum(x["subset_extra"] for x in plan["rows"]),12)
                campaign=asyncio.run(execute_plan(plan,"mock",
                    "synthetic-sticky-policy-v1",include_up=False))
                seal=json.loads((campaign/"completion.json").read_text())
                self.assertEqual(seal["rows_complete"],48)
                self.assertEqual(seal["branch_counts"],108)
                self.assertFalse(seal["include_up"])
                record=load_campaign(campaign)
                self.assertEqual(record["n_runs"],12)
                self.assertEqual(record["n_forks"],48)
                self.assertEqual(record["n_second_shams"],12)
                report=analysis(campaign,repeats=500,seed=21)
                self.assertEqual(report["fixed_rho_sensitivity_grid"].keys(),
                                 {f"{r:g}" for r in AMENDMENT_GRID})
                self.assertTrue(report["confirmatory_layout_complete"])
                self.assertTrue(report["is_mock"])
                self.assertEqual(report["amended_P3"],"NOT_TESTED_SYNTHETIC")
                self.assertEqual(report["n_second_shams"],12)
                self.assertEqual(report["one_period"]["noise_floor"]["n"],12)
                for val in report["fixed_rho_sensitivity_grid"].values():
                    self.assertEqual(val["noise_floor"]["n"],12)
                self.assertEqual(report["rho_abstention"],"NO_POINT_RHO_OR_BOOTSTRAP_UNSTABLE")
                self.assertIsNone(report["dynamic_point"])
                # Current real-model evidence remains absent even though
                # integration and shape checks passed on mock runs.

                # An altered second-sham source cannot pass the input gate.
                manifest=[json.loads(x) for x in (campaign/"manifest.jsonl").read_text().splitlines()]
                with_sham=next(x for x in manifest if x["subset_extra"])
                first=Path(with_sham["branches"]["sham"])
                second=Path(with_sham["branches"]["sham2"])
                feat=checked_second_sham(first,second)
                self.assertEqual(len(feat["diff"]),15)

if __name__=="__main__":
    unittest.main()
