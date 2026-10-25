"""Audit counterexamples: flat heterogeneous bases and missed interior signs."""
import json
import math
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from collusion.inference import rho_sufficient_stats,fit_pooled_rho,pooled_rho_diagnostics
from collusion.amendment_analysis import analysis,dynamic_from_features
from collusion.robustness import certify_rho_interval


class IdentificationRegressions(unittest.TestCase):
    def test_twelve_flat_levels_cannot_manufacture_identified_rho(self):
        with tempfile.TemporaryDirectory() as folder:
            stats=[]
            for i in range(12):
                path=Path(folder)/str(i)
                path.mkdir()
                price=1.60+.05*i
                rows=[{'period':t,'actors':{a:{'executed_price':price} for a in ('Firm A','Firm B')}} for t in range(1,76)]
                (path/'rounds.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
                stat=rho_sufficient_stats(path)
                self.assertIsNone(fit_pooled_rho([stat]))
                stats.append(stat)
            report=pooled_rho_diagnostics(stats)
            self.assertAlmostEqual(report['rho_unrestricted'],1,places=9)
            self.assertIsNone(report['rho_for_model'])
            self.assertEqual(report['visible_price_transitions'],0)
            self.assertEqual(report['reason'],'NO_WITHIN_RUN_AGENT_VISIBLE_EXCITATION')
            rng=random.Random(20261025)
            self.assertTrue(all(fit_pooled_rho(rng.choices(stats,k=12)) is None for _ in range(10000)))

    def test_out_of_domain_ols_is_reported_without_clipping_into_qualification(self):
        for slope in (-.2,1.2):
            stats=[{'n':100,'x':0,'y':0,'xx':10,'xy':10*slope,
                    'within_run_agent_xx':10,'visible_price_transitions':80}]
            result=pooled_rho_diagnostics(stats)
            self.assertAlmostEqual(result['rho_unrestricted'],slope)
            self.assertIsNone(result['rho_for_model'])
            self.assertFalse(result['clipping_applied'])
            self.assertEqual(result['reason'],'OLS_OUTSIDE_DECLARED_RHO_DOMAIN')

    def test_valid_common_intercept_ols_is_unchanged(self):
        stats=[{'n':100,'x':0,'y':0,'xx':10,'xy':8,
                'within_run_agent_xx':10,'visible_price_transitions':80}]
        self.assertAlmostEqual(fit_pooled_rho(stats),.8)
        del stats[0]['within_run_agent_xx']
        self.assertIsNone(fit_pooled_rho(stats))


class ContinuumRegressions(unittest.TestCase):
    def setUp(self):
        # PI(r)=(r-.706)*(.714-r): negative at all eleven .70:.02:.90
        # scan points, positive inside (.706,.714).
        self.feature={'diff':[-.084084,0.0],'br_diff':[-1.0,1.42]}
        self.groups={i:[self.feature]*4 for i in range(12)}

    def test_interior_sign_reversal_cannot_pass_discrete_grid_gate(self):
        self.assertTrue(all(dynamic_from_features(self.feature,.70+.02*j)<0 for j in range(11)))
        self.assertGreater(dynamic_from_features(self.feature,.71),0)
        result=certify_rho_interval(self.groups,[list(range(12))]*100,[.70,.90])
        self.assertFalse(result['certified'])

    def test_true_uniform_negative_is_certified_including_degenerate_interval(self):
        groups={i:[{'diff':[-.1]*15,'br_diff':[0.0]*15}] for i in range(12)}
        for interval in ([0,.999],[.8,.8]):
            self.assertTrue(certify_rho_interval(groups,[list(range(12))]*100,interval)['certified'])

    def test_bound_encloses_direct_values_with_mixed_polynomial_coefficients(self):
        groups={0:[{'diff':[.03,-.2,.1],'br_diff':[-.9,.4,-.12]}]}
        result=certify_rho_interval(groups,[[0]]*100,[.2,.95])
        for check in result['subintervals']:
            for j in range(21):
                rho=check['rho_low']+(check['rho_high']-check['rho_low'])*j/20
                self.assertLessEqual(dynamic_from_features(groups[0][0],rho),check['ci_high_upper_bound']+1e-14)

    def test_p3_does_not_promote_grid_only_robustness(self):
        data={'classification':'FABRICATED_OFFLINE_FIXTURE','provider':'anthropic',
              'groups':self.groups,'rho_stats':{i:{'n':100,'x':0,'y':0,'xx':10,'xy':8,
               'within_run_agent_xx':10,'visible_price_transitions':80} for i in range(12)},
              'noise_by_run':{i:[{'diff':[0.0]*2,'br_diff':[0.0]*2}] for i in range(12)},
              'n_forks':48,'n_second_shams':12,'n_runs':12,'plan_matches':True}
        with patch('collusion.amendment_analysis.load_campaign',return_value=data),patch(
                'collusion.amendment_analysis.fit_pooled_rho',side_effect=[.8]+[.7,.9]*50):
            report=analysis(Path('UNUSED_OFFLINE_FIXTURE'),repeats=100)
        self.assertTrue(report['dynamic_point']['robust_11_point_grid_over_rho_ci'])
        self.assertFalse(report['dynamic_point']['rho_continuum_certificate']['certified'])
        self.assertEqual(report['dynamic_point']['conclusion'],'NOT_ESTABLISHED')
        self.assertEqual(report['amended_P3'],'P3_NOT_SUPPORTED')
