"""Zero-network provider adapter tests. They do not contact any paid model."""
from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import patch
import httpx

from collusion.client import APIClient,validate_reply
from collusion.prompt import P1,GENERAL_PROMPT


class AnthropicContractTests(unittest.TestCase):
    def test_anthropic_payload_and_response_works_offline(self):
        captured=[]
        async def handler(request:httpx.Request) -> httpx.Response:
            captured.append(request)
            payload=json.loads(request.content.decode("utf-8"))
            self.assertEqual(request.url.path,"/v1/messages")
            self.assertEqual(payload["model"],"claude-haiku-4-5-20251001")
            self.assertEqual(payload["max_tokens"],1200)
            self.assertEqual(payload["messages"][0]["role"],"user")
            self.assertEqual(payload["messages"][0]["content"],"The toy market state")
            self.assertIn(P1,payload["system"])
            self.assertIn("chosen_price",payload["system"])
            self.assertEqual(request.headers.get("anthropic-version"),"2023-06-01")
            return httpx.Response(200,json={
                "id":"msg_offline_fixture",
                "type":"message","role":"assistant",
                "content":[{"type":"text","text":json.dumps({
                   "chosen_price":1.82,"plans":"Stay alert","insights":"Strong demand",
                   "observations":"One mock state"})}],
                "usage":{"input_tokens":100,"output_tokens":40}
            })
        async def go():
            with patch.dict("os.environ",{"ANTHROPIC_API_KEY":"dummy-credential-not-real"}):
                client=APIClient("anthropic","claude-haiku-4-5-20251001")
            await client.http.aclose()
            client.http=httpx.AsyncClient(transport=httpx.MockTransport(handler))
            try:
                response,meta=await client.choose("The toy market state","Firm B")
                self.assertEqual(response["chosen_price"],1.82)
                self.assertEqual(response["plans"],"Stay alert")
                self.assertEqual(meta["usage"]["output_tokens"],40)
                self.assertEqual(meta["retry_attempts"],0)
            finally:
                await client.close()
        asyncio.run(go())
        self.assertEqual(len(captured),1)

    def test_anthropic_malformed_content_is_rejected_without_real_network(self):
        async def handler(_:httpx.Request):
            return httpx.Response(200,json={
                "content":[{"type":"text","text":"This is not a JSON price"}],
                "usage":{"input_tokens":100,"output_tokens":20}
            })
        async def go():
            with patch.dict("os.environ",{"ANTHROPIC_API_KEY":"dummy-credential-not-real"}):
                client=APIClient("anthropic","claude-haiku-4-5-20251001")
            await client.http.aclose()
            client.http=httpx.AsyncClient(transport=httpx.MockTransport(handler))
            try:
                with self.assertRaisesRegex(RuntimeError,"Model request failed"):
                    # Existing client retries schema failures; no paid calls here.
                    await client.choose("Toy state","Firm B")
            finally:
                await client.close()
        # Stub immediate asyncio backoff so this test remains sub-second.
        async def fast_sleep(_):
            return None
        with patch("collusion.client.asyncio.sleep",fast_sleep):
            asyncio.run(go())

    def test_no_promotion_of_mock_to_real_provider(self):
        with patch.dict("os.environ",{},clear=True):
            with self.assertRaisesRegex(RuntimeError,"Missing ANTHROPIC_API_KEY"):
                APIClient("anthropic","claude-haiku-4-5-20251001")

if __name__=="__main__":
    unittest.main()
