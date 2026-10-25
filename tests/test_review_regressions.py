"""Offline counterexamples independently found in PR7 and PR7 + PR5."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from collusion import runner
from collusion.amendment_analysis import load_campaign
from collusion.client import APIClient,MockClient
from collusion.journal import ExecutionBudget,summarize_attempts
from collusion.records import validate_base
from collusion.census import admit_reply_identities

MODEL='claude-haiku-5-5'

class IndependentReviewRegressions(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        env=patch.dict('os.environ',{'ANTHROPIC_API_KEY':'offline-fixture'})
        env.start()
        self.addCleanup(env.stop)

    async def client(self, *, reply=None):
        self.calls=[]
        def handler(request):
            self.calls.append(request)
            return httpx.Response(200,json={'id':f'fixture-{len(self.calls)}','model':MODEL,
                'stop_reason':'end_turn','content':[{'type':'text','text':reply or json.dumps({
                    'chosen_price':1.8,'plans':'hold','insights':'fixture','observations':''})}],
                'usage':{'input_tokens':100,'output_tokens':20}})
        client=APIClient('anthropic',MODEL,budget=ExecutionBudget(100,600))
        await client.http.aclose()
        client.http=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(client.close)
        return client

    async def test_persistence_failure_stops_without_retry_or_false_acceptance(self):
        client=await self.client()
        client.bind_episode(self.root,{'kind':'OFFLINE_FIXTURE'})
        write=client.journal.write
        def failed_write(event,**fields):
            if event=='response_received':raise OSError('injected persistence failure')
            write(event,**fields)
        client.journal.write=failed_write
        with self.assertRaisesRegex(OSError,'could not be persisted'):
            await client.choose('offline fixture','Firm A',period=1)
        summary=summarize_attempts(client.journal.path)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(summary['accepted_attempts'],0)
        self.assertEqual(summary['unfinished_attempts'],1)
        self.assertEqual(summary['usage_unknown_attempts'],1)
        from collusion.journal import ExecutionLimit
        with self.assertRaises(ExecutionLimit):client.budget.reserve()

    async def test_transport_timeout_is_not_misclassified_as_storage_failure(self):
        client=await self.client()
        client.bind_episode(self.root,{'kind':'OFFLINE_FIXTURE'})
        post=client.http.post
        calls=0
        async def timeout_once(*args,**kwargs):
            nonlocal calls
            calls+=1
            if calls==1:raise asyncio.TimeoutError('offline timeout')
            return await post(*args,**kwargs)
        async def skip_sleep(delay):pass
        with patch.object(client.http,'post',timeout_once),patch('collusion.client.asyncio.sleep',skip_sleep):
            reply,meta=await client.choose('offline fixture','Firm A',period=1)
        self.assertEqual(calls,2)
        self.assertEqual(meta['retry_attempts'],1)
        self.assertFalse(client.budget.halted)

    async def test_census_failure_cannot_publish_completion(self):
        append=runner.append_event
        def fail_census(path,event):
            if event.get('event')=='completion':raise OSError('injected census failure')
            append(path,event)
        with patch('collusion.runner.LOGROOT',self.root),patch('collusion.runner.append_event',fail_census):
            with self.assertRaisesRegex(OSError,'injected census'):
                await runner.base_episode(MockClient(seed=1),'mock',MockClient.model,2,seed=1)
        base=next(self.root.glob('base_*'))
        self.assertFalse((base/'completion.json').exists())
        self.assertTrue((base/'completion.pending.json').exists())
        self.assertTrue((base/'failure.json').exists())
        with self.assertRaisesRegex(ValueError,'failure latch'):validate_base(base)

    async def test_failure_latch_dominates_existing_completion_and_campaign(self):
        with patch('collusion.runner.LOGROOT',self.root):
            base=await runner.base_episode(MockClient(seed=2),'mock',MockClient.model,2,seed=2)
        validate_base(base)
        (base/'failure.json').write_text('{"status":"FAILED_OR_INTERRUPTED"}')
        with self.assertRaisesRegex(ValueError,'failure latch'):validate_base(base)
        with self.assertRaisesRegex(ValueError,'failure latch'):load_campaign(base)

    async def test_copied_annotations_cannot_override_raw_schema(self):
        client=await self.client(reply=' {"chosen_price":"1.8"} ')
        with patch('collusion.runner.LOGROOT',self.root):
            base=await runner.base_episode(client,'anthropic',MODEL,1)
        original=(base/'attempts.jsonl').read_bytes()
        for filename in ('rounds.jsonl','actor_outcomes.jsonl'):
            rows=[json.loads(x) for x in (base/filename).read_text().splitlines()]
            for row in rows:
                metas=[a['model_meta'] for a in row['actors'].values()] if filename=='rounds.jsonl' else [row['model_meta']]
                for meta in metas:meta['reply_schema_violations']=[]
            (base/filename).write_text(''.join(json.dumps(row)+'\n' for row in rows))
        seal=json.loads((base/'completion.json').read_text())
        seal['rounds_sha256']=runner.digest((base/'rounds.jsonl').read_bytes())
        seal['actor_outcomes_sha256']=runner.digest((base/'actor_outcomes.jsonl').read_bytes())
        (base/'completion.json').write_text(json.dumps(seal))
        with self.assertRaisesRegex(ValueError,'requested schema'):validate_base(base)
        self.assertEqual((base/'attempts.jsonl').read_bytes(),original)

    async def test_live_call_and_response_reuse_is_rejected_even_with_new_other_ids(self):
        for field in ('call_id','accepted_attempt_id','provider_response_id'):
            first={'provider':'anthropic','model':MODEL,'call_id':'call1',
                'accepted_attempt_id':'attempt1','provider_response_id':'response1'}
            second={**first,'call_id':'call2','accepted_attempt_id':'attempt2','provider_response_id':'response2'}
            second[field]=first[field]
            seen=set()
            admit_reply_identities([{'actors':{'Firm A':{'model_meta':first}}}],seen)
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'Duplicate live reply'):
                admit_reply_identities([{'actors':{'Firm A':{'model_meta':second}}}],seen)
