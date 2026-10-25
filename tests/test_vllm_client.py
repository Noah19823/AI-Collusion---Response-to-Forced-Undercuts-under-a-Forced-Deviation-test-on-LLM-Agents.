import os, unittest
from unittest import mock

from collusion.client import APIClient, call_period, call_seed, get_client
from offline_support import offline_client


class VLLMClientTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"VLLM_API_KEY": "test-key",
                                                "VLLM_BASE_URL": "https://example.modal.run/"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_period_read_from_newest_round(self):
        self.assertEqual(call_period("No previous data available."), 1)
        self.assertEqual(call_period("Round 41\n...\nRound 40\n..."), 42)

    def test_seed_depends_on_run_agent_period_only(self):
        a = call_seed(7, "Firm A", 42)
        self.assertEqual(a, call_seed(7, "Firm A", 42))
        self.assertNotEqual(a, call_seed(7, "Firm B", 42))
        self.assertNotEqual(a, call_seed(7, "Firm A", 43))
        self.assertNotEqual(a, call_seed(8, "Firm A", 42))

    def test_request_shape(self):
        client = offline_client(self,"vllm", "Qwen/Qwen3-32B-FP8", seed=3)
        url, headers, payload = client.build_request("Round 9\nmarket data", "Firm A")
        self.assertEqual(url, "https://example.modal.run/v1/chat/completions")
        self.assertEqual(headers["Authorization"], "Bearer test-key")
        self.assertEqual(payload["seed"], call_seed(3, "Firm A", 10))
        self.assertFalse(payload["chat_template_kwargs"]["enable_thinking"])
        self.assertEqual(payload["response_format"], {"type": "json_object"})

    def test_cut_and_sham_share_seed_at_same_period(self):
        client = offline_client(self,"vllm", "m", seed=11)
        _, _, sham = client.build_request("Round 75\nprice 1.90", "Firm B")
        _, _, cut = client.build_request("Round 75\nprice 1.71", "Firm B")
        self.assertEqual(sham["seed"], cut["seed"])

    def test_choose_end_to_end_with_fake_server(self):
        import asyncio, json, httpx
        seen = {}

        def handler(request):
            seen["body"] = json.loads(request.content)
            reply = '<think>\n\n</think>{"chosen_price": 1.85, "plans": "hold", "insights": "", "observations": ""}'
            return httpx.Response(200, json={"model":"m","choices": [{"finish_reason":"stop","message": {"content": reply}}],
                                             "usage": {"prompt_tokens": 10, "completion_tokens": 5}})

        client = offline_client(self,"vllm", "m", seed=1)
        client.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        reply, meta = asyncio.run(client.choose("Round 4\nx", "Firm A"))
        self.assertEqual(reply["chosen_price"], 1.85)
        self.assertEqual(meta["call_seed"], seen["body"]["seed"])
        self.assertEqual(meta["provider"], "vllm")

    def test_deepseek_request_and_served_model(self):
        import asyncio, json, httpx
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "ds-key"}):
            client = offline_client(self,"deepseek", "deepseek-chat", seed=1,resolved_model="deepseek-v3.1")
        url, headers, payload = client.build_request("Round 3\nx", "Firm A")
        self.assertEqual(url, "https://api.deepseek.com/chat/completions")
        self.assertNotIn("chat_template_kwargs", payload)
        self.assertNotIn("seed", payload)

        def handler(request):
            reply = '{"chosen_price": 1.8, "plans": "", "insights": "", "observations": ""}'
            return httpx.Response(200, json={"model": "deepseek-v3.1",
                                             "choices": [{"finish_reason":"stop","message": {"content": reply}}]})
        client.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        reply, meta = asyncio.run(client.choose("Round 3\nx", "Firm A"))
        self.assertEqual(reply["chosen_price"], 1.8)
        self.assertEqual(meta["served_model"], "deepseek-v3.1")

    def test_client_error_shows_provider_message_without_key(self):
        import asyncio, httpx
        from collusion.client import ProviderRejected
        def handler(request):
            return httpx.Response(400, json={"type": "error", "error": {
                "type": "invalid_request_error",
                "message": "model: claude-x not found (key sk-ant-abcdef123456)"}})
        client = offline_client(self,"vllm", "m", seed=1)
        client.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with self.assertRaises(ProviderRejected) as ctx:
            asyncio.run(client.choose("Round 1\nx", "Firm A"))
        msg = str(ctx.exception)
        self.assertIn("HTTP 400", msg)
        self.assertIn("not found", msg)
        self.assertNotIn("sk-ant-abcdef", msg)

    def test_missing_base_url_refuses(self):
        with mock.patch.dict(os.environ, {"VLLM_BASE_URL": ""}):
            with self.assertRaises(RuntimeError):
                offline_client(self,"vllm", "m")


if __name__ == "__main__":
    unittest.main()
