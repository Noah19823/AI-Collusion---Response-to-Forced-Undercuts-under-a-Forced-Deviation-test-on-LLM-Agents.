"""Experiment pricing clients. No API call without --provider anthropic/openai/vllm.

Only ANTHROPIC_API_KEY / OPENAI_API_KEY / VLLM_API_KEY (plus VLLM_BASE_URL)
are read at runtime, never logged. The vllm provider talks to an
OpenAI-compatible vLLM server (for example one deployed with modal/vllm_server.py)
and sends a per-call seed so that paired fork copies draw the same samples
until the cut changes what an agent sees.
The mock provider is for pipeline integrity testing and is NOT LLM evidence.
"""
from __future__ import annotations
import asyncio
import random
import hashlib
import json
import math
import os
import random
import re
from typing import Any

from .market import Market

class NonRetryableProviderResponse(RuntimeError):
    """Fail fast when repeating a request cannot repair the provider error."""

def validate_reply(raw: str) -> dict:
    try:
        item = json.loads(raw.strip())
    except json.JSONDecodeError as exc:
        raise ValueError(f"Not a single valid JSON object: {exc}") from exc
    if not isinstance(item,dict) or isinstance(item.get("chosen_price"),bool):
        raise ValueError("Expected object containing numeric chosen_price")
    try: price = float(item["chosen_price"])
    except (TypeError,ValueError,KeyError) as exc:
        raise ValueError("Invalid price") from exc
    if not (math.isfinite(price) and 0 < price < 20):
        raise ValueError(f"Out-of-range price: {price}")
    return {
        "chosen_price": price,
        "plans": str(item.get("plans","")),
        "insights": str(item.get("insights","")),
        "observations": str(item.get("observations",""))
    }

class MockClient:
    provider = "mock"
    model = "synthetic-sticky-policy-v1"
    def __init__(self, *, seed: int=0) -> None:
        self.seed = seed
        self.market = Market()
    async def choose(self, prompt: str, agent: str) -> tuple[dict,dict]:
        # Minimal deterministic local stand-in: response driven by market history
        # (different prompt => different seed), but NO real language-model inference.
        # Use regex on the latest source-equivalent market-data block.
        own = re.search(r"- My price: ([0-9.]+)",prompt)
        other = re.search(r"- Competitor's prices: \{[^:]+: ([0-9.]+)\}",prompt)
        prev = float(own.group(1)) if own else 1.9
        rival = float(other.group(1)) if other else 1.9
        target = self.market.best_response(rival) + (1.9-self.market.best_response(1.9))
        base = .85*prev + .15*target
        # Stable per (prompt,agent,seed), suitable for deterministic integrity tests.
        digest=hashlib.sha256(f"{self.seed}|{agent}|{prompt}".encode()).digest()
        noise=(int.from_bytes(digest[:4],"big")/2**32-.5)*.006
        value=max(.50,min(4.51,base+noise))
        response={"chosen_price":round(value,4),
                  "plans":"Synthetic fixture: adjust price conservatively.",
                  "insights":"Synthetic test only; no language model was called.",
                  "observations":""}
        return response,{"provider":self.provider,"model":self.model,"usage":{}}

class ProviderRejected(RuntimeError):
    """The provider refused the request (4xx other than rate limiting)."""

_KEY_RE=re.compile(r"sk-[A-Za-z0-9_\-]{8,}")

def _error_text(resp) -> str:
    try:
        body=resp.json()
        err=body.get("error",body) if isinstance(body,dict) else body
        text=(f"{err.get('type','')}: {err.get('message','')}" if isinstance(err,dict) else str(err))
    except Exception:
        text=resp.text
    return _KEY_RE.sub("[redacted]",text)[:500]

_ROUND_RE=re.compile(r"Round (\d+)")
_THINK_RE=re.compile(r"<think>.*?</think>",re.S)

def call_period(prompt: str) -> int:
    """Period being priced, read from the prompt: one after the newest round shown."""
    m=_ROUND_RE.search(prompt)
    return int(m.group(1))+1 if m else 1

def call_seed(base_seed: int,agent: str,period: int) -> int:
    """Seed set by run, agent and period, so fork copies share draws until they diverge."""
    import zlib
    return (base_seed*1_000_003+zlib.crc32(agent.encode())*1009+period)%(2**31-1)

class APIClient:
    def __init__(self,provider: str,model: str,temperature: float=.7,
                 max_tokens: int|None=None,seed: int=0) -> None:
        if provider not in ("anthropic","openai","vllm","deepseek"):
            raise ValueError("API provider must be anthropic, openai, vllm or deepseek")
        key_name={"anthropic":"ANTHROPIC_API_KEY","openai":"OPENAI_API_KEY",
                  "vllm":"VLLM_API_KEY","deepseek":"DEEPSEEK_API_KEY"}[provider]
        self.key=os.environ.get(key_name,"")
        if not self.key:
            raise RuntimeError(f"Missing {key_name}; no paid calls attempted")
        self.base_url=""
        if provider=="vllm":
            self.base_url=os.environ.get("VLLM_BASE_URL","").rstrip("/")
            if not self.base_url:
                raise RuntimeError("Missing VLLM_BASE_URL (the Modal web endpoint URL)")
        self.provider, self.model = provider, model
        if max_tokens is None:
            # A10: Haiku 5.5's PLANS/INSIGHTS notes grow over a 150-round game and one
            # reply passed 1200 tokens near round 120, so its cap is raised to 4096.
            max_tokens=4096 if provider=="anthropic" and model.startswith("claude-haiku-5-5") else 1200
        self.temperature, self.max_tokens, self.seed = temperature, max_tokens, seed
        import httpx
        self.http=httpx.AsyncClient(timeout=120)
    async def close(self) -> None:
        await self.http.aclose()
    def build_request(self,prompt: str,agent: str) -> tuple[str,dict,dict]:
        from .prompt import P1,SCHEMA
        if self.provider=="vllm":
            url=self.base_url+"/v1/chat/completions"
            headers={"Authorization":"Bearer "+self.key}
            payload={"model":self.model,"max_tokens":self.max_tokens,
                     "temperature":self.temperature,
                     "seed":call_seed(self.seed,agent,call_period(prompt)),
                     "messages":[{"role":"system","content":SCHEMA+"\n"+P1},
                                 {"role":"user","content":prompt}],
                     "response_format":{"type":"json_object"},
                     # Qwen3 models think by default; the protocol uses plain replies.
                     "chat_template_kwargs":{"enable_thinking":False}}
            return url,headers,payload
        if self.provider=="deepseek":
            # OpenAI-compatible; no per-call seed support is assumed, so fork copies
            # can drift like other hosted APIs and the second no-cut copy measures it.
            url="https://api.deepseek.com/chat/completions"
            headers={"Authorization":"Bearer "+self.key}
            payload={"model":self.model,"max_tokens":self.max_tokens,
                     "temperature":self.temperature,
                     "thinking":{"type":"disabled"},
                     "messages":[{"role":"system","content":SCHEMA+"\n"+P1},
                                 {"role":"user","content":prompt}],
                     "response_format":{"type":"json_object"}}
            return url,headers,payload
        if self.provider=="anthropic":
            url="https://api.anthropic.com/v1/messages"
            headers={"x-api-key":self.key,"anthropic-version":"2023-06-01"}
            payload={"model":self.model,"max_tokens":self.max_tokens,
                     "system":SCHEMA+"\n"+P1,
                     "messages":[{"role":"user","content":prompt}]}
            if self.model.startswith("claude-haiku-5-5"):
                # Haiku 5.5 takes no sampling parameters. Thinking is turned off so the
                # agent answers directly like the other providers here, which also keeps
                # replies inside max_tokens and the cost near the A7 estimate.
                payload["thinking"]={"type":"disabled"}
                payload["output_config"]={"effort":"medium"}
            else:
                payload["temperature"]=self.temperature
        else:
            url="https://api.openai.com/v1/chat/completions"
            headers={"Authorization":"Bearer "+self.key}
            payload={"model":self.model,"max_completion_tokens":self.max_tokens,
                     "messages":[{"role":"system","content":SCHEMA+"\n"+P1},
                                 {"role":"user","content":prompt}],
                     "response_format":{"type":"json_object"}}
        return url,headers,payload
    async def choose(self,prompt: str,agent: str) -> tuple[dict,dict]:
        url,headers,payload=self.build_request(prompt,agent)
        # Do not log payload headers/credential. Only safe error summaries.
        tries=8
        for attempt in range(tries):
            try:
                resp=await self.http.post(url,headers=headers,json=payload)
                if resp.status_code in (408,429,500,502,503,504,529) and attempt<tries-1:
                    # Rate limits on small accounts need real waits. Use the server's
                    # retry-after when given, otherwise back off up to about a minute.
                    try: wait=float(resp.headers.get("retry-after",""))
                    except ValueError: wait=min(60,5*2**attempt)
                    await asyncio.sleep(max(1.0,wait)+random.uniform(0,2))
                    continue
                if 400<=resp.status_code<500 and resp.status_code not in (408,429):
                    # Client errors won't fix themselves on retry. Show the provider's
                    # own error text (never the key) so the cause is visible.
                    raise ProviderRejected(f"HTTP {resp.status_code} from {self.provider}: "
                                           f"{_error_text(resp)}")
                resp.raise_for_status()
                data=resp.json()
                if self.provider=="anthropic" and data.get("stop_reason") in ("max_tokens","model_context_window_exceeded"):
                    raise NonRetryableProviderResponse(f"response ended with {data['stop_reason']}; revise max_tokens or effort before repeating")
                if self.provider=="anthropic":
                    blocks=data.get("content",[])
                    content="\n".join(b.get("text","") for b in blocks if b.get("type")=="text")
                    usage=data.get("usage",{})
                else:
                    content=data["choices"][0]["message"]["content"] or ""
                    content=_THINK_RE.sub("",content).strip()
                    usage=data.get("usage",{})
                meta={"provider":self.provider,"model":self.model,
                      "usage":usage,"retry_attempts":attempt}
                if self.provider!="anthropic" and data.get("model"):
                    # The model version the server says it actually used.
                    meta["served_model"]=data["model"]
                if "seed" in payload: meta["call_seed"]=payload["seed"]
                meta.update({"resolved_model":data.get("model",self.model),
                             "provider_response_id":data.get("id"),
                             "stop_reason":data.get("stop_reason")})
                return validate_reply(content),meta
            except ProviderRejected:
                raise
            except NonRetryableProviderResponse as exc:
                raise RuntimeError(f"Non-retryable model response; provider={self.provider}: {exc}") from exc
            except Exception as exc:
                if attempt == tries-1:
                    raise RuntimeError(f"Model request failed; provider={self.provider},"
                                       f" exception={type(exc).__name__}. No raw key or response logged.") from exc
                await asyncio.sleep(min(60,5*2**attempt))
        raise RuntimeError("Unreachable")

def get_client(provider: str,model: str, *, seed: int=0):
    if provider=="mock": return MockClient(seed=seed)
    return APIClient(provider,model,seed=seed)
