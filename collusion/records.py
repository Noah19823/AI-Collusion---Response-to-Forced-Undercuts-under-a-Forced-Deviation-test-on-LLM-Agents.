"""Read-only semantic and population checks on sealed primitive evidence.

Checksums are necessary but insufficient: rebuild prompts and market outcomes.
Legacy mock fixtures remain readable. Missing live configuration/provenance is
an admission failure, not an invitation to invent metadata or reseal old files.
"""
from __future__ import annotations

import copy
import base64
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import subprocess

from .market import Market
from .prompt import build_prompt
from .protocol_binding import require_compatible_protocol
from .journal import summarize_attempts

ACTORS=('Firm A','Firm B')
ROOT=Path(__file__).resolve().parents[1]


def source_provenance() -> dict:
    paths=sorted((ROOT/'collusion').glob('*.py'))
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    try:
        commit=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,
                              check=True,timeout=5).stdout.decode().strip()
        dirty=bool(subprocess.run(['git','status','--porcelain','--untracked-files=normal'],
                   cwd=ROOT,capture_output=True,check=True,timeout=5).stdout.strip())
    except (OSError,subprocess.SubprocessError):
        commit=dirty=None
    return {'source_commit':commit,'source_dirty':dirty,'source_files_sha256':hashes,
            'collection_source_sha256':hashlib.sha256(json.dumps(
                {k:v for k,v in hashes.items() if Path(k).name in
                 ('client.py','runner.py','prompt.py','market.py','journal.py')},
                sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            'source_commit_status':'RECORDED' if commit else 'UNKNOWN'}


def population_key(meta: dict) -> str:
    config=meta.get('effective_config')
    if meta['provider']!='mock':
        if not isinstance(config,dict) or not meta.get('collection_source_sha256'):
            raise ValueError('Live evidence lacks effective configuration/source binding; historical admission requires explicit review')
        from .runner import digest
        if digest(config)!=meta.get('effective_config_sha256'):
            raise ValueError('Effective configuration digest mismatch')
    return json.dumps({'provider':meta['provider'],'model':meta['model'],
                       'config':config,'max_tokens':meta.get('max_tokens'),
                       'collection_source_sha256':meta.get('collection_source_sha256')},sort_keys=True)


def require_same_population(first: dict, second: dict) -> None:
    if population_key(first)!=population_key(second):
        raise ValueError('Mixed model/provider/effective configuration or collection source')


def _number(value, expected, label):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError('Nonfinite/nonnumeric '+label)
    if not math.isclose(value,expected,rel_tol=1e-12,abs_tol=1e-8):
        raise ValueError('Inconsistent '+label)


def validate_history(rows: list[dict], *, prefix: list[dict], agents: tuple,
                     meta: dict, forced_first: bool=False) -> None:
    from .runner import digest, recalculate_round
    history=list(prefix)
    for offset,row in enumerate(rows):
        if type(row.get('period')) is not int or row['period']!=len(history)+1:
            raise ValueError('Noncontiguous primitive periods')
        if set(row.get('actors',{}))!=set(agents):
            raise ValueError('Wrong primitive actor population')
        if not (forced_first and offset==0) and row.get('intervention') is not None:
            raise ValueError('Unexpected intervention after the frozen source period')
        for agent in agents:
            actor=row['actors'][agent]
            prompt=build_prompt(history,agent,marginal_cost=Market().cost)
            if actor['prompt']!=prompt or actor['prompt_sha256']!=digest(prompt.encode()):
                raise ValueError('Prompt/history or prompt digest mismatch')
            price=actor['executed_price']
            if isinstance(price,bool) or not isinstance(price,(int,float)) or not math.isfinite(price) or not 0<price<20:
                raise ValueError('Invalid executed price')
            _number(actor['response']['chosen_price'],price,'chosen/executed price')
            if not (forced_first and offset==0):
                _number(actor['model_chosen_price'],price,'proposal/executed price')
            model_meta=actor['model_meta']
            if model_meta.get('provider')!=meta['provider'] or model_meta.get('model')!=meta['model']:
                raise ValueError('Actor provider/model differs from episode')
            if meta['provider']!='mock':
                config=meta['effective_config']
                if model_meta.get('resolved_model')!=config['expected_resolved_model']:
                    raise ValueError('Actor resolved model differs from declared population')
                if model_meta.get('reply_schema_violations'):
                    raise ValueError('Legacy reply normalization violated the requested schema; admission requires a methods decision')
        expected=copy.deepcopy(row)
        recalculate_round(expected,Market())
        for agent in agents:
            for field in ('quantity','profit'):
                _number(row['actors'][agent][field],expected['actors'][agent][field],field)
            if row['actors'][agent]['market_data']!=expected['actors'][agent]['market_data']:
                raise ValueError('Displayed market data differs from executed outcomes')
        if row['market_prices']!=expected['market_prices']:
            raise ValueError('Market price map differs from executed prices')
        _number(row['total_profit'],expected['total_profit'],'total profit')
        history.append(row)


@lru_cache(maxsize=32)
def _validated_base_bytes(meta_bytes: bytes, done_bytes: bytes, raw: bytes):
    from .runner import digest
    meta=json.loads(meta_bytes)
    done=json.loads(done_bytes)
    if meta.get('kind')!='base' or meta.get('n_agents')!=2 or meta.get('market')!=Market().__dict__:
        raise ValueError('Expected a duopoly base under the declared market')
    if digest(raw)!=done.get('rounds_sha256'):
        raise ValueError('Corrupt base primitive seal')
    rows=[json.loads(line) for line in raw.splitlines() if line.strip()]
    if not rows or len(rows)!=meta['planned_rounds'] or len(rows)!=done.get('completed_rounds'):
        raise ValueError('Incomplete planned base history')
    population_key(meta)
    validate_history(rows,prefix=[],agents=ACTORS,meta=meta)
    for agent in ACTORS:
        _number(done['final_prices'][agent],rows[-1]['actors'][agent]['executed_price'],'base final price')
        mean=sum(r['actors'][agent]['executed_price'] for r in rows[-10:])/min(10,len(rows))
        _number(done['last10_mean'][agent],mean,'base last-ten mean')
    return meta,done,rows


def validate_base(path: Path, *, current_protocol: bool=False):
    require_unfailed(path)
    meta,done,rows=_validated_base_bytes((path/'meta.json').read_bytes(),
        (path/'completion.json').read_bytes(),(path/'rounds.jsonl').read_bytes())
    if current_protocol:
        require_compatible_protocol(meta['protocol_sha256'],ROOT,source=str(path))
    validate_attempt_evidence(path,meta,done,rows)
    return meta,done,rows


def require_unfailed(path: Path) -> None:
    if (path/'failure.json').exists():
        raise ValueError('Episode/campaign has a failure latch; completion cannot override it')


def validate_attempt_evidence(path: Path, meta: dict, seal: dict, rows: list[dict], *, skip_first=False):
    from .runner import digest
    from .client import validate_reply, reply_schema_violations
    require_unfailed(path)
    if 'actor_outcomes_sha256' in seal:
        if digest((path/'actor_outcomes.jsonl').read_bytes())!=seal['actor_outcomes_sha256']:
            raise ValueError('Actor outcome journal seal mismatch')
    if meta['provider']=='mock':
        return
    if 'actor_outcomes_sha256' not in seal:
        raise ValueError('Completed live episode lacks an actor outcome seal')
    if summarize_attempts(path/'attempts.jsonl')!=seal.get('attempt_accounting'):
        raise ValueError('Attempt journal/accounting seal mismatch')
    events=[json.loads(line) for line in (path/'attempts.jsonl').read_text().splitlines() if line.strip()]
    starts={e['attempt_id']:e for e in events if e['event']=='request_started'}
    responses={e['attempt_id']:e for e in events if e['event']=='response_received'}
    accepted={e['attempt_id']:e for e in events if e['event']=='attempt_finished' and e['status']=='accepted'}
    if seal['attempt_accounting']['unfinished_attempts']:
        raise ValueError('Completed episode contains unfinished HTTP attempts')
    consumed=set()
    primitive={}
    for row in rows[1:] if skip_first else rows:
        for agent,actor in row['actors'].items():
            mm=actor['model_meta']
            identity=mm.get('accepted_attempt_id')
            if identity in consumed or identity not in accepted or identity not in responses:
                raise ValueError('Primitive reply lacks a unique accepted raw HTTP attempt')
            consumed.add(identity)
            start,response=starts[identity],responses[identity]
            if start.get('agent')!=agent or start.get('period')!=row['period'] or start.get('call_id')!=mm.get('call_id') or Path(start['episode']).resolve()!=path.resolve():
                raise ValueError('HTTP attempt belongs to another actor/period/episode')
            payload=start['request']
            request_hash=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            if request_hash!=start['request_sha256'] or payload['messages'][-1]['content']!=actor['prompt']:
                raise ValueError('HTTP request does not bind the primitive prompt')
            if start['effective_config']!=meta['effective_config']:
                raise ValueError('HTTP attempt configuration differs from episode')
            config=meta['effective_config']
            if {k:v for k,v in payload.items() if k not in ('messages','system','seed')}!=config['request_parameters'] or start['request_url']!=config['endpoint'] or start.get('api_version')!=config['api_version']:
                raise ValueError('Actual request options/endpoint differ from the declared configuration')
            from .prompt import SCHEMA,P1
            system=SCHEMA+'\n'+P1
            if meta['provider']=='anthropic':
                if payload.get('system')!=system or payload['messages']!=[{'role':'user','content':actor['prompt']}]:
                    raise ValueError('Actual request system/message history differs from the declared prompt')
            elif payload['messages']!=[{'role':'system','content':system},{'role':'user','content':actor['prompt']}]:
                raise ValueError('Actual request system/message history differs from the declared prompt')
            if meta['provider']=='vllm':
                from .client import call_seed
                if payload.get('seed')!=call_seed(meta['seed_local_only'],agent,row['period']):
                    raise ValueError('Actual request seed differs from the saved base/period')
            if response.get('response_body_redacted'):
                raise ValueError('Redacted accepted response requires explicit evidence review')
            body=response['response_body'].encode() if response['response_body_encoding']=='utf-8' else base64.b64decode(response['response_body'],validate=True)
            if hashlib.sha256(body).hexdigest()!=response['response_body_sha256']:
                raise ValueError('Raw response body digest mismatch')
            raw=json.loads(body)
            if raw.get('model')!=meta['effective_config']['expected_resolved_model'] or raw.get('usage')!=mm.get('usage') or raw.get('id')!=mm.get('provider_response_id'):
                raise ValueError('Raw response model/usage/identity differs from primitive reply')
            if meta['provider']=='anthropic':
                stop=raw.get('stop_reason')
                content='\n'.join(b.get('text','') for b in raw.get('content',[]) if b.get('type')=='text')
                expected_stop='end_turn'
            else:
                from .client import _THINK_RE
                stop=raw['choices'][0].get('finish_reason')
                content=_THINK_RE.sub('',raw['choices'][0]['message']['content'] or '').strip()
                expected_stop='stop'
            if stop!=expected_stop or mm.get('stop_reason')!=stop or validate_reply(content)!=actor['response']:
                raise ValueError('Raw response differs from accepted primitive fields')
            issues=reply_schema_violations(content)
            if issues or mm.get('reply_schema_violations')!=issues or accepted[identity].get('reply_schema_violations')!=issues:
                raise ValueError('Raw response or accepted-attempt diagnostics violate the requested schema')
            primitive[(row['period'],agent)]=actor
    if consumed!=set(accepted):
        raise ValueError('Accepted HTTP replies are missing from the completed primitive history')
    outcomes=[json.loads(line) for line in (path/'actor_outcomes.jsonl').read_text().splitlines() if line.strip()]
    if len(outcomes)!=len(primitive):
        raise ValueError('Actor outcome census differs from completed primitives')
    seen=set()
    for outcome in outcomes:
        key=(outcome['period'],outcome['agent'])
        if key in seen or key not in primitive or outcome['status']!='accepted':
            raise ValueError('Invalid completed actor outcome census')
        seen.add(key)
        actor=primitive[key]
        if any(outcome.get(k)!=actor[k] for k in ('response','model_meta','prompt_sha256')):
            raise ValueError('Actor outcome differs from completed primitive')


def validate_branch(base_dir: Path, branch_dir: Path):
    from .runner import digest, choose_fork_source
    require_unfailed(branch_dir)
    bm,bd,base=validate_base(base_dir)
    meta=json.loads((branch_dir/'meta.json').read_text())
    seal=json.loads((branch_dir/'completion.json').read_text())
    raw=(branch_dir/'continuation.jsonl').read_bytes()
    if digest(raw)!=seal.get('records_sha256'):
        raise ValueError('Corrupt branch log')
    rows=[json.loads(line) for line in raw.splitlines() if line.strip()]
    require_same_population(bm,meta)
    require_compatible_protocol(bm['protocol_sha256'],ROOT,source=str(base_dir))
    require_compatible_protocol(meta['protocol_sha256'],ROOT,source=str(branch_dir))
    period=meta['fork_period']
    horizon=meta['planned_rounds']
    if type(period) is not int or not 2<=period<=len(base) or type(horizon) is not int or horizon<1:
        raise ValueError('Invalid source period/horizon')
    if meta.get('kind')!='fork_'+meta['intervention'] or meta.get('n_agents')!=2 or meta.get('market')!=bm.get('market'):
        raise ValueError('Branch kind/market/actor mismatch')
    if Path(meta['base_path']).resolve()!=base_dir.resolve():
        raise ValueError('Branch belongs to a different base')
    if bm['provider']=='vllm' and meta['seed_local_only']!=bm['seed_local_only']:
        raise ValueError('Branch must retain the saved base seed')
    if len(rows)!=horizon+1 or not seal.get('complete') or seal.get('period')!=period or seal.get('through_period')!=period+horizon or seal.get('kind')!=meta['intervention']:
        raise ValueError('Branch completion/horizon mismatch')
    if meta['prefix_sha256']!=digest(base[:period-1]) or meta['source_round_sha256']!=digest(base[period-1]) or seal['prefix_sha256']!=meta['prefix_sha256']:
        raise ValueError('Branch prefix/source seal mismatch')
    if meta.get('base_rounds_sha256',bd['rounds_sha256'])!=bd['rounds_sha256']:
        raise ValueError('Branch base seal mismatch')
    expected=choose_fork_source(base,period,meta['cutter'],meta['intervention'],Market())
    if not rows or rows[0]!=expected:
        raise ValueError('Source proposal, memory or simultaneous intervention changed')
    validate_history(rows,prefix=base[:period-1],agents=ACTORS,meta=meta,forced_first=True)
    validate_attempt_evidence(branch_dir,meta,seal,rows,skip_first=True)
    return meta,rows
