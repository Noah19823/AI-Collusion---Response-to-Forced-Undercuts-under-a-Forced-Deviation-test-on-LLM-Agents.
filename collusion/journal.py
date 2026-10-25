"""Durable, secret-free attempt evidence and explicit execution bounds.

Bounds count HTTP attempts, including retries. They are not dollar estimates.
Missing response/usage is UNKNOWN, never a zero-cost completion. The journal
is created exclusively inside a new episode; existing artifacts are not edited.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time

_KEY=re.compile(r'sk-[A-Za-z0-9_\-]{8,}')


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_event(path: Path, event: dict) -> None:
    with path.open('a',encoding='utf-8') as stream:
        stream.write(json.dumps(event,sort_keys=True,ensure_ascii=False,allow_nan=False)+'\n')
        stream.flush()
        os.fsync(stream.fileno())


class ExecutionLimit(RuntimeError):
    """The declared request count or elapsed-time limit has been reached."""


class ExecutionBudget:
    def __init__(self, max_requests: int, deadline_seconds: float):
        if isinstance(max_requests,bool) or not isinstance(max_requests,int) or max_requests<1:
            raise ValueError('max_requests must be a positive integer')
        if not math.isfinite(deadline_seconds) or deadline_seconds<=0:
            raise ValueError('deadline_seconds must be positive and finite')
        self.max_requests=max_requests
        self.deadline_seconds=deadline_seconds
        self.started=time.monotonic()
        self.requests=0

    def remaining(self) -> float:
        remaining=self.deadline_seconds-(time.monotonic()-self.started)
        if remaining<=0:
            raise ExecutionLimit('Execution deadline reached; no additional requests authorized')
        return remaining

    def reserve(self) -> int:
        self.remaining()
        if self.requests>=self.max_requests:
            raise ExecutionLimit('HTTP-attempt limit reached; retries also count')
        self.requests+=1
        return self.requests

    def declaration(self) -> dict:
        return {'max_http_attempts':self.max_requests,'deadline_seconds':self.deadline_seconds,
                'scope':'entire CLI invocation, shared across actors/runs/branches',
                'not_a_dollar_cap':True}


class AttemptJournal:
    def __init__(self, path: Path, *, secrets=()):
        self.path=path
        self.secrets=tuple(value for value in secrets if value)
        # No accidental append to/replay of a previous experiment's journal.
        with path.open('x',encoding='utf-8'):
            pass

    def redact(self, value):
        if isinstance(value,str):
            for secret in self.secrets:
                value=value.replace(secret,'[redacted]')
            return _KEY.sub('[redacted]',value)
        if isinstance(value,dict):
            return {k:self.redact(v) for k,v in value.items()}
        if isinstance(value,(list,tuple)):
            return [self.redact(v) for v in value]
        if isinstance(value,float) and not math.isfinite(value):
            return {'non_finite_value':repr(value)}
        return value

    def write(self, event: str, **fields) -> None:
        append_event(self.path,self.redact({'event':event,'at_utc':utc_now(),**fields}))

    def response(self, body: bytes) -> dict:
        # Keep exact bytes unless redaction is necessary. The pre-redaction hash
        # remains explicit; redacted evidence is never called an exact copy.
        try:
            text=body.decode('utf-8')
            clean=self.redact(text)
            try:
                parsed=json.loads(text)
                sanitized=self.redact(parsed)
                if sanitized!=parsed:
                    clean=json.dumps(sanitized,ensure_ascii=False)
            except (ValueError,TypeError):
                pass
            return {'response_body':clean,'response_body_encoding':'utf-8',
                    'response_body_sha256':hashlib.sha256(body).hexdigest(),
                    'response_body_redacted':clean!=text}
        except UnicodeError:
            cleaned=body
            for secret in self.secrets:
                cleaned=cleaned.replace(secret.encode(),b'[redacted]')
            cleaned=re.sub(rb'sk-[A-Za-z0-9_\-]{8,}',b'[redacted]',cleaned)
            return {'response_body':base64.b64encode(cleaned).decode('ascii'),
                    'response_body_encoding':'base64',
                    'response_body_sha256':hashlib.sha256(body).hexdigest(),
                    'response_body_redacted':cleaned!=body}


def summarize_attempts(path: Path) -> dict:
    records=[json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    starts={}
    responses={}
    outcomes={}
    for record in records:
        key=record.get('attempt_id')
        if record['event']=='request_started':
            if key in starts:
                raise ValueError('Duplicate attempt identity')
            starts[key]=record
        elif record['event']=='response_received':
            if key in responses:
                raise ValueError('Duplicate response identity')
            responses[key]=record
        elif record['event']=='attempt_finished':
            if key in outcomes:
                raise ValueError('Duplicate attempt outcome')
            outcomes[key]=record
    if not set(responses)<=set(starts) or not set(outcomes)<=set(starts):
        raise ValueError('Attempt response/outcome has no request start')
    totals={}
    known=0
    for key,start in starts.items():
        response=responses.get(key)
        usage=None
        if response is not None:
            body=response['response_body'].encode() if response['response_body_encoding']=='utf-8' else base64.b64decode(response['response_body'],validate=True)
            if not response.get('response_body_redacted') and hashlib.sha256(body).hexdigest()!=response['response_body_sha256']:
                raise ValueError('Raw HTTP response digest mismatch')
            try:
                parsed=json.loads(body)
            except (ValueError,UnicodeError):
                parsed=None
            usage=parsed.get('usage') if isinstance(parsed,dict) else None
            if json.dumps(usage,sort_keys=True)!=json.dumps(response.get('usage'),sort_keys=True):
                raise ValueError('Copied usage fields disagree with raw HTTP response')
        fields=('input_tokens','output_tokens') if start['provider']=='anthropic' else ('prompt_tokens','completion_tokens')
        if not isinstance(usage,dict) or not all(
            isinstance(usage.get(f),int) and not isinstance(usage.get(f),bool) and usage[f]>=0 for f in fields
        ):
            continue
        known+=1
        for field,value in usage.items():
            if isinstance(value,int) and not isinstance(value,bool) and value>=0:
                totals[field]=totals.get(field,0)+value
    return {'http_attempts':len(starts),'responses_received':len(responses),
            'accepted_attempts':sum(v.get('status')=='accepted' for v in outcomes.values()),
            'rejected_or_failed_attempts':sum(v.get('status')!='accepted' for v in outcomes.values()),
            'unfinished_attempts':len(starts)-len(outcomes),
            'usage_known_attempts':known,'usage_unknown_attempts':len(starts)-known,
            'known_usage_totals':totals,'all_usage_known':known==len(starts),
            'journal_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'qualification':'Observed token accounting only; unknown usage is not zero, and this is not an invoice.'}
