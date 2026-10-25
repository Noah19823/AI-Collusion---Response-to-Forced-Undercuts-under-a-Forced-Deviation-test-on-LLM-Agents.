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
import hashlib
import json
import math
import os
import random
import re
import time
import uuid
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit
from typing import Any

from .market import Market
from .journal import AttemptJournal, ExecutionBudget, ExecutionLimit,EvidencePersistenceError

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

def reply_schema_violations(raw: str) -> list[str]:
    """Derive diagnostics from the original reply, never copied annotations."""
    original=json.loads(raw.strip())
    issues=[key for key in ('plans','insights','observations') if not isinstance(original.get(key),str)]
    if not isinstance(original.get('chosen_price'),(int,float)) or isinstance(original.get('chosen_price'),bool):
        issues.append('chosen_price')
    return issues

class MockClient:
    provider = "mock"
    model = "synthetic-sticky-policy-v1"
    def __init__(self, *, seed: int=0) -> None:
        self.seed = seed
        self.market = Market()
    def experiment_config(self) -> dict:
        return {"provider":self.provider,"model":self.model,"policy":"synthetic-sticky-policy-v1"}
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

def _error_text(resp, secret: str='') -> str:
    try:
        body=resp.json()
        err=body.get("error",body) if isinstance(body,dict) else body
        text=(f"{err.get('type','')}: {err.get('message','')}" if isinstance(err,dict) else str(err))
    except Exception:
        text=resp.text
    if secret:text=text.replace(secret,'[redacted]')
    return _KEY_RE.sub("[redacted]",text)[:500]

_ROUND_RE=re.compile(r"Round (\d+)")
_THINK_RE=re.compile(r"<think>.*?</think>",re.S)

def call_period(prompt: str) -> int:
    """Period being priced, read from the prompt: one after the newest round shown."""
    marker="Section name: MARKET DATA (read-only)\n+++++++++++++++++++++\n"
    if marker in prompt:
        # Notes are model output and may mention arbitrary past/future rounds.
        prompt=prompt.rsplit(marker,1)[1].split("\n+++++++++++++++++++++",1)[0]
    m=_ROUND_RE.search(prompt)
    return int(m.group(1))+1 if m else 1

def call_seed(base_seed: int,agent: str,period: int) -> int:
    """Seed set by run, agent and period, so fork copies share draws until they diverge."""
    import zlib
    return (base_seed*1_000_003+zlib.crc32(agent.encode())*1009+period)%(2**31-1)

class APIClient:
    def __init__(self,provider: str,model: str,temperature: float=.7,
                 max_tokens: int|None=None,seed: int=0, *,
                 budget: ExecutionBudget|None=None, resolved_model: str|None=None) -> None:
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
            parsed=urlsplit(self.base_url)
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError('VLLM_BASE_URL must not contain credentials, query secrets or fragments')
        self.provider, self.model = provider, model
        if max_tokens is None:
            # A10: Haiku 5.5's PLANS/INSIGHTS notes grow over a 150-round game and one
            # reply passed 1200 tokens near round 120, so its cap is raised to 4096.
            max_tokens=4096 if provider=="anthropic" and model.startswith("claude-haiku-5-5") else 1200
        self.temperature, self.max_tokens, self.seed = temperature, max_tokens, seed
        self.budget=budget
        self.resolved_model=resolved_model or model
        self.journal=None
        self.episode_context={}
        import httpx
        self.http=httpx.AsyncClient(timeout=120)
    async def close(self) -> None:
        await self.http.aclose()
    def bind_episode(self, path: Path, context: dict) -> None:
        if self.budget is None:
            raise ExecutionLimit('A shared request count and deadline are required before live collection')
        self.journal=AttemptJournal(path/'attempts.jsonl',secrets=(self.key,))
        self.episode_context={"episode":str(path.resolve()),**context}

    def _record_attempt(self,event: str, **fields) -> None:
        try:
            self.journal.write(event,**fields)
        except (OSError,ValueError,TypeError) as exc:
            # Stop future requests sharing this budget, including sibling retries.
            # Already received responses may still be persisted by their owners.
            self.budget.halt()
            raise EvidencePersistenceError('Attempt evidence could not be persisted') from exc

    def experiment_config(self) -> dict:
        url,_,payload=self.build_request('', 'Firm A', period=1)
        return {"provider":self.provider,"model":self.model,
                "expected_resolved_model":self.resolved_model,"endpoint":url,
                "api_version":"2023-06-01" if self.provider=='anthropic' else None,
                "request_parameters":{k:v for k,v in payload.items() if k not in ('messages','system','seed')},
                "reply_parser":"legacy-normalization-v1-with-schema-diagnostics",
                "response_contract":"explicit-model-and-complete-stop-v1",
                "seed_policy":"run-agent-structured-period-v1" if self.provider=='vllm' else None,
                "retry_policy":{"max_attempts":8,"generic_delays_seconds":[5,10,20,40,60,60,60],
                                "transient_http":"Retry-After or exponential backoff, plus uniform 0-2s jitter",
                                "truncation_and_identity_errors":"fail-fast"}}

    def build_request(self,prompt: str,agent: str, *, period: int|None=None) -> tuple[str,dict,dict]:
        from .prompt import P1,SCHEMA
        if self.provider=="vllm":
            url=self.base_url+"/v1/chat/completions"
            headers={"Authorization":"Bearer "+self.key}
            payload={"model":self.model,"max_tokens":self.max_tokens,
                     "temperature":self.temperature,
                     "seed":call_seed(self.seed,agent,period if period is not None else call_period(prompt)),
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
    async def choose(self,prompt: str,agent: str, *, period: int|None=None) -> tuple[dict,dict]:
        if self.journal is None or self.budget is None:
            raise ExecutionLimit('Bind a new episode journal and an explicit execution budget before any HTTP request')
        url,headers,payload=self.build_request(prompt,agent,period=period)
        context={**self.episode_context,"agent":agent,"period":period,
                 "provider":self.provider,"requested_model":self.model,
                 "call_id":uuid.uuid4().hex}
        request_bytes=json.dumps(payload,sort_keys=True,separators=(',',':')).encode()
        request_hash=hashlib.sha256(request_bytes).hexdigest()
        tries=8
        for attempt in range(tries):
            attempt_id=uuid.uuid4().hex
            fields={**context,"attempt_id":attempt_id,"attempt_index":attempt}
            # Reservation and durable request evidence precede the HTTP call.
            ordinal=self.budget.reserve()
            self._record_attempt('request_started',**fields,global_request_number=ordinal,
                request_sha256=request_hash,request=payload,request_url=url,
                api_version=headers.get('anthropic-version'),effective_config=self.experiment_config())
            started=time.monotonic()
            ended=False
            delay=None
            try:
                remaining=self.budget.remaining()
                resp=await asyncio.wait_for(
                    self.http.post(url,headers=headers,json=payload,timeout=min(120,remaining)),
                    timeout=remaining)
                try:
                    data=resp.json()
                except ValueError:
                    data=None
                usage=data.get('usage') if isinstance(data,dict) else None
                self._record_attempt('response_received',**fields,http_status=resp.status_code,
                    provider_response_id=data.get('id') if isinstance(data,dict) else None,
                    served_model=data.get('model') if isinstance(data,dict) else None,
                    usage=usage,retry_after=resp.headers.get('retry-after'),
                    **self.journal.response(resp.content))
                if resp.status_code in (408,429,500,502,503,504,529) and attempt<tries-1:
                    # Rate limits on small accounts need real waits. Use the server's
                    # retry-after when given, otherwise back off up to about a minute.
                    raw=resp.headers.get('retry-after','')
                    try:
                        wait=float(raw)
                        if not math.isfinite(wait):raise ValueError('Nonfinite Retry-After')
                    except ValueError:
                        try:
                            date=parsedate_to_datetime(raw)
                            if date.tzinfo is None:date=date.replace(tzinfo=timezone.utc)
                            wait=(date-datetime.now(timezone.utc)).total_seconds()
                        except (ValueError,TypeError,OverflowError):
                            wait=min(60,5*2**attempt)
                    delay=max(1.0,wait)+random.uniform(0,2)
                    self._record_attempt('attempt_finished',**fields,status='retryable_http',
                        retry_delay_seconds=delay,elapsed_seconds=time.monotonic()-started)
                    ended=True
                    await self._wait_before_retry(delay,fields)
                    continue
                if 400<=resp.status_code<500 and resp.status_code not in (408,429):
                    # Client errors won't fix themselves on retry. Show the provider's
                    # own error text (never the key) so the cause is visible.
                    raise ProviderRejected(f"HTTP {resp.status_code} from {self.provider}: "
                                           f"{_error_text(resp,self.key)}")
                resp.raise_for_status()
                if not isinstance(data,dict):
                    raise ValueError('Provider response is not a JSON object')
                if self.provider=="anthropic" and data.get("stop_reason") in ("max_tokens","model_context_window_exceeded"):
                    raise NonRetryableProviderResponse(f"response ended with {data['stop_reason']}; revise max_tokens or effort before repeating")
                if data.get('model')!=self.resolved_model:
                    raise NonRetryableProviderResponse('Resolved model is missing or outside the declared model population')
                if self.provider=="anthropic":
                    stop=data.get('stop_reason')
                    if stop!='end_turn':
                        raise NonRetryableProviderResponse('Anthropic response has no complete end_turn status')
                    blocks=data.get("content",[])
                    content="\n".join(b.get("text","") for b in blocks if b.get("type")=="text")
                    usage=data.get("usage",{})
                else:
                    stop=data['choices'][0].get('finish_reason')
                    if stop!='stop' or data['choices'][0]['message'].get('refusal'):
                        raise NonRetryableProviderResponse('Chat response is truncated, refused, or has unknown finish_reason')
                    content=data["choices"][0]["message"]["content"] or ""
                    content=_THINK_RE.sub("",content).strip()
                    usage=data.get("usage",{})
                meta={"provider":self.provider,"model":self.model,
                      "usage":usage,"retry_attempts":attempt,
                      "call_id":context['call_id'],"accepted_attempt_id":attempt_id}
                if self.provider!="anthropic" and data.get("model"):
                    # The model version the server says it actually used.
                    meta["served_model"]=data["model"]
                if "seed" in payload: meta["call_seed"]=payload["seed"]
                meta.update({"resolved_model":data.get("model",self.model),
                             "provider_response_id":data.get("id"),
                             "stop_reason":stop})
                reply=validate_reply(content)
                # Diagnose the legacy normalization without silently changing
                # its retry/selection policy. Admission rejects these warnings.
                issues=reply_schema_violations(content)
                meta['reply_schema_violations']=issues
                self._record_attempt('attempt_finished',**fields,status='accepted',
                    reply_schema_violations=issues,elapsed_seconds=time.monotonic()-started)
                ended=True
                return reply,meta
            except EvidencePersistenceError:
                # Evidence persistence is not a model/transport retry. A retry
                # could spend again after losing the response just received.
                # Leave this attempt unfinished and fail the owning episode.
                ended=True
                raise
            except (ProviderRejected,ExecutionLimit) as exc:
                if not ended:
                    self._record_attempt('attempt_finished',**fields,status='provider_rejected_or_limit',
                        exception_type=type(exc).__name__,error=str(exc),elapsed_seconds=time.monotonic()-started)
                    ended=True
                raise
            except NonRetryableProviderResponse as exc:
                self._record_attempt('attempt_finished',**fields,status='non_retryable_response',
                    exception_type=type(exc).__name__,error=str(exc),elapsed_seconds=time.monotonic()-started)
                ended=True
                raise RuntimeError(f"Non-retryable model response; provider={self.provider}: {exc}") from exc
            except Exception as exc:
                if not ended:
                    self._record_attempt('attempt_finished',**fields,status='rejected_or_transport_failed',
                        exception_type=type(exc).__name__,error=str(exc),elapsed_seconds=time.monotonic()-started)
                    ended=True
                if attempt == tries-1:
                    raise RuntimeError(f"Model request failed; provider={self.provider},"
                                       f" exception={type(exc).__name__}; attempt evidence retained.") from exc
                await self._wait_before_retry(min(60,5*2**attempt),fields)
            finally:
                if not ended:
                    self._record_attempt('attempt_finished',**fields,status='failed_or_cancelled',
                        elapsed_seconds=time.monotonic()-started)
        raise RuntimeError("Unreachable")

    async def _wait_before_retry(self, seconds: float, context: dict) -> None:
        if self.budget.requests>=self.budget.max_requests or seconds>=self.budget.remaining():
            self._record_attempt('retry_blocked_by_execution_limit',**context,requested_delay_seconds=seconds)
            raise ExecutionLimit('Retry would exceed the declared request or elapsed-time limit')
        await asyncio.sleep(seconds)

def get_client(provider: str,model: str, *, seed: int=0,budget=None,resolved_model=None):
    if provider=="mock": return MockClient(seed=seed)
    return APIClient(provider,model,seed=seed,budget=budget,resolved_model=resolved_model)
