"""Durable rejected/sibling replies, identity gates and bounded HTTP mocks."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from collusion.client import APIClient,call_period,call_seed
from collusion.journal import ExecutionBudget,ExecutionLimit,summarize_attempts
from collusion.runner import base_episode
from collusion.records import validate_base
from collusion.preflight_budget import scan_attempt_usage

MODEL='claude-haiku-5-5'


def response(n=1, *, malformed=False, model=MODEL, tokens=20, stop='end_turn'):
    return httpx.Response(200,json={'id':f'offline-{n}','model':model,'stop_reason':stop,
        'content':[{'type':'text','text':'malformed' if malformed else json.dumps({
            'chosen_price':1.8,'plans':'hold','insights':'hold','observations':''})}],
        'usage':{'input_tokens':100,'output_tokens':tokens}})


class AttemptIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        env=patch.dict('os.environ',{'ANTHROPIC_API_KEY':'secret-fixture-credential',
                                   'DEEPSEEK_API_KEY':'secret-fixture-credential',
                                   'VLLM_API_KEY':'secret-fixture-credential',
                                   'VLLM_BASE_URL':'https://example.invalid'})
        env.start()
        self.addCleanup(env.stop)

    async def client(self,handler, *, budget=None,provider='anthropic',model=MODEL,resolved_model=None):
        client=APIClient(provider,model,budget=budget or ExecutionBudget(32,600),resolved_model=resolved_model)
        await client.http.aclose()
        client.http=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        folder=self.root/f'adapter-{len(list(self.root.iterdir()))}'
        folder.mkdir()
        client.bind_episode(folder,{'kind':'OFFLINE_FIXTURE'})
        self.addCleanup(lambda:asyncio.run(client.close()))
        return client

    def test_malformed_retry_retains_both_raw_replies_and_all_usage(self):
        calls=[]
        sleeps=[]
        def handler(request):
            calls.append(request)
            return response(len(calls),malformed=len(calls)==1,tokens=50 if len(calls)==1 else 20)
        async def sleep(delay):sleeps.append(delay)
        async def run():
            client=await self.client(handler)
            with patch('collusion.client.asyncio.sleep',sleep):
                reply,meta=await client.choose('fixture','Firm A',period=1)
            summary=summarize_attempts(client.journal.path)
            self.assertEqual(meta['usage']['output_tokens'],20)
            self.assertEqual(summary['known_usage_totals']['output_tokens'],70)
            self.assertEqual(summary['accepted_attempts'],1)
            self.assertEqual(summary['rejected_or_failed_attempts'],1)
            self.assertEqual(summary['usage_unknown_attempts'],0)
            self.assertIn('malformed',client.journal.path.read_text())
            self.assertEqual(sleeps,[5])
            costs=scan_attempt_usage(client.journal.path)
            self.assertEqual(costs['priced_attempts'],2)
            self.assertAlmostEqual(costs['known_token_cost_estimate_usd'],(200*.1+70*.5)/1_000_000)
            self.assertTrue(costs['cost_complete_under_declared_rate_model'])
        asyncio.run(run())

    def test_exhausted_retries_still_retain_all_eight_billed_replies(self):
        calls=[]
        def handler(request):
            calls.append(request)
            return response(len(calls),malformed=True,tokens=50)
        async def sleep(_):pass
        async def run():
            client=await self.client(handler)
            with patch('collusion.client.asyncio.sleep',sleep),self.assertRaisesRegex(RuntimeError,'Model request failed'):
                await client.choose('fixture','Firm A',period=1)
            summary=summarize_attempts(client.journal.path)
            self.assertEqual(len(calls),8)
            self.assertEqual(summary['known_usage_totals']['output_tokens'],400)
            self.assertEqual(summary['rejected_or_failed_attempts'],8)
        asyncio.run(run())

    def test_retry_after_is_honored_but_never_crosses_shared_bounds(self):
        async def run(max_requests,deadline):
            calls=[]
            sleeps=[]
            def handler(request):
                calls.append(request)
                return httpx.Response(429,headers={'retry-after':'60'},json={'error':{'message':'rate limit'}}) if len(calls)<3 else response(3)
            async def sleep(delay):sleeps.append(delay)
            client=await self.client(handler,budget=ExecutionBudget(max_requests,deadline))
            with patch('collusion.client.asyncio.sleep',sleep),patch('collusion.client.random.uniform',return_value=1):
                if max_requests==1 or deadline<60:
                    with self.assertRaises(ExecutionLimit):await client.choose('fixture','Firm A',period=1)
                    self.assertEqual(len(calls),1)
                    self.assertEqual(sleeps,[])
                else:
                    await client.choose('fixture','Firm A',period=1)
                    self.assertEqual(sleeps,[61,61])
                    self.assertEqual(summarize_attempts(client.journal.path)['usage_unknown_attempts'],2)
                    self.assertFalse(scan_attempt_usage(client.journal.path)['cost_complete_under_declared_rate_model'])
        for request_limit,deadline in ((1,600),(10,10),(10,600)):
            with self.subTest(request_limit=request_limit,deadline=deadline):asyncio.run(run(request_limit,deadline))

    def test_unbound_client_cannot_issue_any_http_request(self):
        async def run():
            client=APIClient('anthropic',MODEL)
            await client.http.aclose()
            calls=[]
            client.http=httpx.AsyncClient(transport=httpx.MockTransport(lambda r:calls.append(r)))
            try:
                with self.assertRaises(ExecutionLimit):await client.choose('fixture','Firm A')
                self.assertEqual(calls,[])
            finally:await client.close()
        asyncio.run(run())

    def test_wrong_server_model_and_chat_truncation_fail_fast_with_raw_evidence(self):
        async def run(provider):
            calls=[]
            def handler(request):
                calls.append(request)
                if provider=='anthropic':return response(model='wrong-model')
                return httpx.Response(200,json={'id':'chat-fixture','model':'deepseek-flash',
                    'choices':[{'finish_reason':'length','message':{'content':'{"chosen_price":1.8}'}}],
                    'usage':{'prompt_tokens':100,'completion_tokens':1200}})
            client=await self.client(handler,provider=provider,model=MODEL if provider=='anthropic' else 'deepseek-flash')
            with self.assertRaisesRegex(RuntimeError,'Non-retryable'):
                await client.choose('fixture','Firm A',period=1)
            self.assertEqual(len(calls),1)
            self.assertEqual(summarize_attempts(client.journal.path)['usage_known_attempts'],1)
        for provider in ('anthropic','deepseek'):
            with self.subTest(provider=provider):asyncio.run(run(provider))

    def test_error_key_is_redacted_without_discarding_failure_record(self):
        async def run():
            client=await self.client(lambda r:httpx.Response(400,json={'error':{
                'message':'secret-fixture-credential and sk-ant-abcdef123456'}}))
            with self.assertRaises(RuntimeError) as caught:await client.choose('fixture','Firm A',period=1)
            self.assertNotIn('secret-fixture-credential',str(caught.exception))
            text=client.journal.path.read_text()
            self.assertNotIn('secret-fixture-credential',text)
            self.assertNotIn('sk-ant-abcdef123456',text)
            self.assertNotIn('Authorization',text)
            self.assertIn('response_body_redacted',text)
            self.assertEqual(summarize_attempts(client.journal.path)['http_attempts'],1)
        asyncio.run(run())

    def test_failed_simultaneous_round_keeps_successful_sibling_and_failed_run(self):
        async def run():
            count=0
            def handler(request):
                nonlocal count
                count+=1
                return response(1,tokens=33) if count==1 else httpx.Response(400,json={'error':{'message':'bad request'}})
            client=await self.client(handler)
            with patch('collusion.runner.LOGROOT',self.root/'runs'):
                with self.assertRaises(RuntimeError):await base_episode(client,'anthropic',MODEL,2)
            episode=next((self.root/'runs').glob('base_*'))
            self.assertFalse((episode/'completion.json').exists())
            failure=json.loads((episode/'failure.json').read_text())
            outcomes=[json.loads(x) for x in (episode/'actor_outcomes.jsonl').read_text().splitlines()]
            self.assertEqual(sum(o['status']=='accepted' for o in outcomes),1)
            self.assertEqual(failure['attempt_accounting']['known_usage_totals']['output_tokens'],33)
            self.assertEqual(failure['attempt_accounting']['usage_unknown_attempts'],1)
            census=(self.root/'runs'/'attempt_census.jsonl').read_text()
            self.assertIn('run_created',census)
            self.assertIn('failure',census)
        asyncio.run(run())

    def test_request_bound_is_shared_between_simultaneous_actors(self):
        async def run():
            calls=[]
            def handler(request):
                calls.append(request)
                return response(len(calls))
            client=await self.client(handler,budget=ExecutionBudget(1,600))
            with patch('collusion.runner.LOGROOT',self.root/'runs'):
                with self.assertRaises(ExecutionLimit):await base_episode(client,'anthropic',MODEL,2)
            self.assertEqual(len(calls),1)
            episode=next((self.root/'runs').glob('base_*'))
            self.assertEqual(json.loads((episode/'failure.json').read_text())['attempt_accounting']['accepted_attempts'],1)
        asyncio.run(run())

    def test_legacy_schema_coercion_is_preserved_but_cannot_qualify_evidence(self):
        async def run():
            client=await self.client(lambda request:httpx.Response(200,json={
                'id':'schema-fixture','model':MODEL,'stop_reason':'end_turn',
                'content':[{'type':'text','text':'{"chosen_price":1.8}'}],
                'usage':{'input_tokens':1,'output_tokens':1}}))
            with patch('collusion.runner.LOGROOT',self.root/'runs'):
                base=await base_episode(client,'anthropic',MODEL,1)
            self.assertTrue((base/'completion.json').exists())
            self.assertTrue((base/'attempts.jsonl').exists())
            with self.assertRaisesRegex(ValueError,'requested schema'):validate_base(base)
        asyncio.run(run())

    def test_completed_primitives_bind_original_accepted_http_responses(self):
        async def run():
            counter=0
            def handler(request):
                nonlocal counter
                counter+=1
                return response(counter)
            client=await self.client(handler)
            with patch('collusion.runner.LOGROOT',self.root/'runs'):
                base=await base_episode(client,'anthropic',MODEL,2)
            validate_base(base)
            journal=base/'attempts.jsonl'
            events=[json.loads(line) for line in journal.read_text().splitlines()]
            next(e for e in events if e['event']=='response_received')['usage']['output_tokens']=9999
            journal.write_text(''.join(json.dumps(e)+'\n' for e in events))
            with self.assertRaisesRegex(ValueError,'usage fields disagree'):
                summarize_attempts(journal)
        asyncio.run(run())

    def test_seed_period_is_structured_and_notes_cannot_override_it(self):
        prompt='Section name: PLANS\nRound 12\nSection name: MARKET DATA (read-only)\n+++++++++++++++++++++\nRound 75\nx\n+++++++++++++++++++++'
        self.assertEqual(call_period(prompt),76)
        async def run():
            client=await self.client(lambda r:response(),provider='vllm',model='m')
            _,_,payload=client.build_request('Round 900 in notes','Firm A',period=76)
            self.assertEqual(payload['seed'],call_seed(client.seed,'Firm A',76))
        asyncio.run(run())
