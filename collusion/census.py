"""Exact amended campaign layout, ownership and population admission."""
from __future__ import annotations

import json
from pathlib import Path
import random

from .records import population_key, validate_base
from .runner import ACTORS, digest

FORKS=(75,95,115,135)


def validate_bases(bases: list[Path], *, current_protocol: bool=False) -> dict:
    if len(bases)!=12:
        raise ValueError('Protocol expects 12 distinct independent base identities')
    paths=set()
    raw_ids=set()
    populations=set()
    checked={}
    for supplied in bases:
        path=supplied.resolve()
        if path in paths:
            raise ValueError('Duplicate/aliased base path; labels do not establish independence')
        paths.add(path)
        meta,done,rows=validate_base(path,current_protocol=current_protocol)
        if len(rows)<max(FORKS):
            raise ValueError('Base is too short for the frozen fork periods')
        identity=done['rounds_sha256']
        if identity in raw_ids:
            raise ValueError('Duplicate base primitive identity, including copied files')
        raw_ids.add(identity)
        populations.add(population_key(meta))
        checked[path]=(meta,done,rows)
    if len(populations)!=1:
        raise ValueError('Mixed base model/provider/configuration/source populations')
    return checked


def base_binding(path: Path, run_id: int) -> dict:
    return {'run_id':run_id,'base':str(path.resolve()),
            **{name+'_sha256':digest((path/name).read_bytes())
               for name in ('meta.json','completion.json','rounds.jsonl')}}


def validate_plan(plan: dict, *, current_protocol: bool=False) -> dict:
    rows=plan.get('rows',[])
    if len(rows)!=48 or digest(rows)!=plan.get('plan_digest') or plan.get('subsets_fixed_before_fork_data') is not True:
        raise ValueError('Invalid frozen 48-row campaign plan/digest')
    seed=plan.get('seed_local_only')
    if type(seed) is not int:
        raise ValueError('Plan subset seed must be an integer')
    extra=set(random.Random(seed).sample(range(48),12))
    owners={}
    for index,row in enumerate(rows):
        run,local=divmod(index,4)
        if type(row.get('run_id')) is not int or row['run_id']!=run or type(row.get('period')) is not int or row['period']!=FORKS[local]:
            raise ValueError('Plan must contain exactly the four frozen periods for each of 12 runs')
        if row.get('cutter')!=ACTORS[(run+local)%2]:
            raise ValueError('Cutter differs from the frozen balanced assignment')
        if type(row.get('subset_extra')) is not bool or row['subset_extra']!=(index in extra):
            raise ValueError('Second-sham subset differs from the frozen seeded assignment')
        path=Path(row['base']).resolve()
        if run in owners and owners[run]!=path:
            raise ValueError('One run label refers to multiple bases')
        owners[run]=path
    checked=validate_bases([owners[i] for i in range(12)],current_protocol=current_protocol)
    if 'base_bindings' in plan:
        if plan['base_bindings']!=[base_binding(owners[i],i) for i in range(12)]:
            raise ValueError('Base bytes changed after the plan was frozen')
        if plan.get('horizon')!=15 or type(plan.get('include_up')) is not bool:
            raise ValueError('Plan horizon/control declaration mismatch')
        if plan.get('plan_sha256')!=digest({k:v for k,v in plan.items() if k!='plan_sha256'}):
            raise ValueError('Full plan digest mismatch')
    elif any(meta['provider']!='mock' for meta,_,_ in checked.values()):
        raise ValueError('Live plan lacks frozen base bindings; no retrospective promotion')
    return checked


def validate_branch_ownership(entry: dict, seen_paths: set, seen_raw: set) -> None:
    for kind,name in entry['branches'].items():
        path=Path(name).resolve()
        if path in seen_paths:
            raise ValueError('A branch path is assigned to multiple campaign rows/roles')
        seen_paths.add(path)
        raw_id=digest((path/'continuation.jsonl').read_bytes())
        if raw_id in seen_raw:
            raise ValueError('A copied branch primitive identity is assigned more than once')
        seen_raw.add(raw_id)
        meta=json.loads((path/'meta.json').read_text())
        if meta.get('intervention')!=kind or meta.get('fork_period')!=entry['period'] or meta.get('cutter')!=entry['cutter'] or meta.get('planned_rounds')!=15:
            raise ValueError('Branch role/source period/cutter/horizon differs from plan')
        if Path(meta['base_path']).resolve()!=Path(entry['base']).resolve():
            raise ValueError('Branch owner differs from planned base')
