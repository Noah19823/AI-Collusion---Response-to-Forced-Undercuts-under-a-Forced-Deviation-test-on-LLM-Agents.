"""Counterexamples from the independent audit, using disposable mock evidence."""
import asyncio
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from collusion.amendment_analysis import load_campaign
from collusion.analysis import verify_pair
from collusion.campaign import make_plan,execute_plan
from collusion.census import validate_plan
from collusion.client import MockClient
from collusion.records import validate_base
from collusion.runner import base_episode,fork_episode,digest,main,common_meta

MODEL='synthetic-sticky-policy-v1'


def reseal_plan(plan):
    plan['plan_digest']=digest(plan['rows'])
    if 'plan_sha256' in plan:
        plan['plan_sha256']=digest({k:v for k,v in plan.items() if k!='plan_sha256'})


class CampaignIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=tempfile.TemporaryDirectory()
        cls.root=Path(cls.fixture.name)
        with patch('collusion.runner.LOGROOT',cls.root):
            cls.bases=[asyncio.run(base_episode(MockClient(seed=i),'mock',MODEL,135,seed=i)) for i in range(12)]
            cls.plan=make_plan(cls.bases)
            cls.sham=asyncio.run(fork_episode(MockClient(seed=0),'mock',MODEL,cls.bases[0],75,15,'Firm A','sham',0))
            cls.cut=asyncio.run(fork_episode(MockClient(seed=0),'mock',MODEL,cls.bases[0],75,15,'Firm A','cut',0))

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.scratch=Path(self.temp.name)

    def copied(self,source,name='copy'):
        path=self.scratch/name
        shutil.copytree(source,path)
        return path

    def test_distinct_sealed_layout_passes_without_inference(self):
        self.assertEqual(len(validate_plan(self.plan)),12)
        verify_pair(self.bases[0],self.sham,self.cut)

    def test_unqualified_resume_and_parallelism_fail_before_io_or_provider(self):
        for options in ({'resume':self.scratch/'untouched'}, {'concurrency':2}, {'concurrency':0}):
            with self.subTest(options=options), patch('collusion.campaign.get_client') as provider, patch('collusion.campaign.run_folder') as create:
                with self.assertRaises(ValueError):
                    asyncio.run(execute_plan({},'mock',MODEL,**options))
                provider.assert_not_called()
                create.assert_not_called()
        self.assertEqual(list(self.scratch.iterdir()),[])

    def test_duplicate_alias_and_copied_base_fail_before_provider_factory(self):
        alias=self.scratch/'alias'
        alias.symlink_to(self.bases[0],target_is_directory=True)
        duplicate=self.copied(self.bases[0])
        for bad in (self.bases[0],alias,duplicate):
            paths=list(self.bases)
            paths[1]=bad
            with self.subTest(path=bad),self.assertRaisesRegex(ValueError,'Duplicate'):
                make_plan(paths)
        plan=copy.deepcopy(self.plan)
        for row in plan['rows'][4:8]:row['base']=str(self.bases[0])
        reseal_plan(plan)
        with patch('collusion.campaign.get_client') as provider,self.assertRaisesRegex(ValueError,'Duplicate'):
            asyncio.run(execute_plan(plan,'mock',MODEL,limit=1))
        provider.assert_not_called()

    def test_reformatted_copy_is_not_an_independent_base(self):
        copied=self.copied(self.bases[0])
        with (copied/'rounds.jsonl').open('ab') as stream:stream.write(b'\n')
        seal=json.loads((copied/'completion.json').read_text())
        seal['rounds_sha256']=digest((copied/'rounds.jsonl').read_bytes())
        (copied/'completion.json').write_text(json.dumps(seal))
        paths=list(self.bases)
        paths[1]=copied
        with self.assertRaisesRegex(ValueError,'Duplicate base primitive'):make_plan(paths)

    def test_wrong_period_cutter_and_second_sham_assignment_fail_even_when_resealed(self):
        for field,value in (('period',95),('cutter','Firm B'),('subset_extra',not self.plan['rows'][0]['subset_extra'])):
            plan=copy.deepcopy(self.plan)
            plan['rows'][0][field]=value
            reseal_plan(plan)
            with self.subTest(field=field),self.assertRaises(ValueError):validate_plan(plan)

    def test_mixed_output_caps_and_post_plan_metadata_changes_fail(self):
        copied=self.copied(self.bases[1])
        paths=list(self.bases)
        paths[1]=copied
        plan=make_plan(paths)
        meta=json.loads((copied/'meta.json').read_text())
        meta['review_note']='Changed after freezing the base identities'
        (copied/'meta.json').write_text(json.dumps(meta))
        with self.assertRaisesRegex(ValueError,'Base bytes changed'):validate_plan(plan)
        meta['max_tokens']=4096
        (copied/'meta.json').write_text(json.dumps(meta))
        with self.assertRaisesRegex(ValueError,'Mixed base'):make_plan(paths)

    def test_base_checksum_is_checked_before_any_fork(self):
        base=self.copied(self.bases[0])
        with (base/'rounds.jsonl').open('ab') as stream:stream.write(b'\n')
        with self.assertRaisesRegex(ValueError,'Corrupt base'):validate_base(base)

    def test_resealed_later_prompt_and_market_outcomes_do_not_pass_pair_validation(self):
        for field,value in (('prompt','unrelated fabricated history'),('profit',999),('quantity',999)):
            branch=self.copied(self.cut,field)
            rows=[json.loads(line) for line in (branch/'continuation.jsonl').read_text().splitlines()]
            rows[1]['actors']['Firm B'][field]=value
            if field=='prompt':rows[1]['actors']['Firm B']['prompt_sha256']=digest(value.encode())
            raw=''.join(json.dumps(row)+'\n' for row in rows).encode()
            (branch/'continuation.jsonl').write_bytes(raw)
            seal=json.loads((branch/'completion.json').read_text())
            seal['records_sha256']=digest(raw)
            (branch/'completion.json').write_text(json.dumps(seal))
            with self.subTest(field=field),self.assertRaises(ValueError):verify_pair(self.bases[0],self.sham,branch)

    def test_branch_population_mismatch_fails(self):
        branch=self.copied(self.cut)
        meta=json.loads((branch/'meta.json').read_text())
        meta['model']='another-model'
        (branch/'meta.json').write_text(json.dumps(meta))
        with self.assertRaisesRegex(ValueError,'Mixed model'):verify_pair(self.bases[0],self.sham,branch)

    def test_one_base_relabelled_twelve_times_cannot_form_complete_campaign(self):
        plan=copy.deepcopy(self.plan)
        for row in plan['rows']:row['base']=str(self.bases[0])
        reseal_plan(plan)
        manifest=[{'plan_row':i,**row,'status':'COMPLETE','branches':{
            'sham':str(self.sham),'cut':str(self.cut),**({'sham2':str(self.sham)} if row['subset_extra'] else {})}}
            for i,row in enumerate(plan['rows'])]
        campaign=self.scratch/'campaign'
        campaign.mkdir()
        (campaign/'plan.json').write_text(json.dumps(plan))
        raw=''.join(json.dumps(row)+'\n' for row in manifest).encode()
        (campaign/'manifest.jsonl').write_bytes(raw)
        (campaign/'completion.json').write_text(json.dumps({'rows_complete':48,'branch_counts':108,
            'provider':'mock','classification':'SYNTHETIC_INTEGRATION','manifest_sha256':digest(raw),
            'plan_sha256':plan['plan_sha256']}))
        with self.assertRaisesRegex(ValueError,'Duplicate'):load_campaign(campaign)

    def test_failed_cut_keeps_completed_sham_and_failure_link(self):
        class FailingMock(MockClient):
            async def choose(self,*args,**kwargs):raise RuntimeError('deliberate offline failure')
        count=0
        def factory(provider,model,**kwargs):
            nonlocal count
            count+=1
            cls=FailingMock if count==3 else MockClient  # probe, sham, then cut
            return cls(seed=kwargs.get('seed',0))
        with patch('collusion.runner.LOGROOT',self.scratch),patch('collusion.campaign.get_client',factory):
            with self.assertRaisesRegex(RuntimeError,'deliberate offline failure'):
                asyncio.run(execute_plan(self.plan,'mock',MODEL,limit=1))
        campaign=next(self.scratch.glob('campaign_*'))
        failure=json.loads((campaign/'failure.json').read_text())
        self.assertFalse((campaign/'completion.json').exists())
        self.assertTrue((Path(failure['completed_branches_in_row']['sham'])/'completion.json').exists())
        self.assertTrue((Path(failure['failed_branch'])/'failure.json').exists())

    def test_campaign_publication_failure_latches_even_after_completion_appears(self):
        import os
        link=os.link
        def fail_after_link(source,target):
            link(source,target)
            if target.parent.name.startswith('campaign_'):
                raise OSError('injected post-publication failure')
        with patch('collusion.runner.LOGROOT',self.scratch),patch('collusion.runner.os.link',fail_after_link):
            with self.assertRaisesRegex(OSError,'post-publication'):
                asyncio.run(execute_plan(self.plan,'mock',MODEL,limit=1))
        campaign=next(self.scratch.glob('campaign_*'))
        self.assertTrue((campaign/'completion.json').exists())
        self.assertEqual(json.loads((campaign/'failure.json').read_text())['phase'],'completion_publication')
        with self.assertRaisesRegex(ValueError,'failure latch'):load_campaign(campaign)

    def test_post_collection_validation_failure_retains_every_completed_branch(self):
        with patch('collusion.runner.LOGROOT',self.scratch),patch(
                'collusion.campaign.verify_pair',side_effect=ValueError('offline invalid pair')):
            with self.assertRaisesRegex(ValueError,'offline invalid pair'):
                asyncio.run(execute_plan(self.plan,'mock',MODEL,limit=1))
        campaign=next(self.scratch.glob('campaign_*'))
        failure=json.loads((campaign/'failure.json').read_text())
        self.assertEqual(failure['phase'],'pair_validation')
        self.assertFalse((campaign/'completion.json').exists())
        self.assertIn('sham',failure['completed_branches_in_row'])
        self.assertIn('cut',failure['completed_branches_in_row'])
        self.assertTrue(all((Path(p)/'completion.json').exists() for p in failure['completed_branches_in_row'].values()))


class AdmissionOrderingTests(unittest.TestCase):
    def test_invalid_protocol_fails_before_provider_even_with_complete_pass_marker(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)
            (path/'meta.json').write_text(json.dumps({'kind':'pretest','provider':'anthropic',
                'model':'claude-haiku-5-5','planned_rounds':50,'protocol_sha256':'0'*64}))
            (path/'completion.json').write_text(json.dumps({'pretest_near_one_product_monopoly':True}))
            argv=['runner','base','--provider','anthropic','--execute-paid','--pretest-dir',str(path),
                  '--max-http-attempts','10','--deadline-seconds','600']
            with patch.object(sys,'argv',argv),patch('collusion.runner.get_client') as factory:
                with self.assertRaises(SystemExit):main()
            factory.assert_not_called()

    def test_actual_source_identity_is_recorded(self):
        from collusion.runner import ROOT
        meta=common_meta('mock',MODEL,'base',1,2,0,MockClient())
        expected=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
        self.assertEqual(meta['source_commit'],expected)
        self.assertNotEqual(meta['source_commit'],'b210bfb0f8499de9d9710424d7570808e23a885a')
        self.assertTrue(meta['source_files_sha256'])
        self.assertEqual(meta['effective_config_sha256'],digest(meta['effective_config']))
