#!/usr/bin/env python3
"""Dry-run consumer for Memory OS review-target proposals.

Reads the live ReviewProposal JSONL and the newest redacted action queue,
then emits private conversion drafts. It never writes Memory Graph and never
changes proposal statuses. Reports redact raw content by default.
"""
from __future__ import annotations
import argparse, hashlib, json, os, re, time
from collections import Counter
from pathlib import Path
from typing import Any

PROFILE_DIR = Path(os.environ.get('HERMES_PROFILE_DIR') or (Path.home()/'.hermes'))
DEFAULT_QUEUE = Path(os.environ.get('MEMORY_REVIEW_QUEUE') or (PROFILE_DIR/'logs'/'memory_review_queue'/'review_proposals.current.jsonl'))
BASE = Path(os.environ.get('DIGITAL_BRAIN_99_TASK_DIR') or (PROFILE_DIR/'tasks'/'digital-brain-99'))
ACTION_DIR = BASE/'action_queue'
DRAFT_DIR = BASE/'conversion_drafts'
REPORT_DIR = BASE/'reports'
SAFE_ACTIONS = {
    'needs_skill_or_procedural_memory_conversion',
    'needs_private_tool_route_memory_conversion',
    'needs_memory_graph_conversion',
    'needs_private_context_memory_conversion',
    'needs_distillation_before_memory_graph',
    'eligible_memory_graph_approval_review',
}

def get(d: dict[str, Any], path: str, default: Any = '') -> Any:
    x: Any = d
    for p in path.split('.'):
        if not isinstance(x, dict):
            return default
        x = x.get(p, default)
    return default if x is None else x

def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows=[]
    if not path.exists():
        return rows
    for i,line in enumerate(path.read_text(encoding='utf-8', errors='ignore').splitlines(), 1):
        if not line.strip(): continue
        try:
            o=json.loads(line); o['_line_no']=i; rows.append(o)
        except Exception as e:
            rows.append({'_line_no':i,'_parse_error':repr(e)})
    return rows

def latest_action_queue() -> Path | None:
    files=sorted(ACTION_DIR.glob('proposal-actions-*.json'), key=lambda p:p.stat().st_mtime, reverse=True)
    return files[0] if files else None

def redact_path_hint(path: str) -> str:
    if not path: return ''
    # Keep generic routing category, not full private content.
    parts=[p for p in re.split(r'[/：:]+', path) if p]
    return '/'.join(parts[:2]) if parts else '[present]'

def digest_text(*parts: str) -> str:
    h=hashlib.sha256()
    for p in parts:
        h.update((p or '').encode('utf-8', errors='ignore')); h.update(b'\0')
    return h.hexdigest()[:16]

def draft_from(payload: dict[str, Any], action: dict[str, Any], private_dir: Path | None = None) -> dict[str, Any]:
    c=payload.get('candidate') or {}
    decision=payload.get('decision') or {}
    changeset=payload.get('changeset') or {}
    proposal_id=str(payload.get('proposal_id') or payload.get('id') or action.get('proposal_id') or '')
    target_store=str(decision.get('target_store') or c.get('suggested_store') or '')
    risk=str(decision.get('risk_level') or c.get('risk_level') or '')
    namespace=str(c.get('namespace_security_scope') or changeset.get('namespace') or payload.get('namespace') or '')
    kind=str(c.get('kind') or c.get('type') or 'unknown')
    target_path=str(c.get('target_path') or changeset.get('target_path_uri') or '')
    evidence=str(c.get('evidence_quote') or payload.get('evidence_quote') or '')
    content=str(c.get('value') or c.get('content') or evidence or '')
    queries=c.get('readback_queries') or get(payload, 'readback.queries', []) or []
    if not isinstance(queries, list): queries=[]
    action_hint=str(action.get('action_hint') or '')
    route={
        'needs_skill_or_procedural_memory_conversion': 'skill_or_procedural_memory_review',
        'needs_private_tool_route_memory_conversion': 'private_tool_route_memory_review',
        'needs_memory_graph_conversion': 'private_memory_graph_conversion_review',
        'needs_private_context_memory_conversion': 'private_context_memory_review',
        'needs_distillation_before_memory_graph': 'distill_raw_material_before_memory_graph',
        'eligible_memory_graph_approval_review': 'direct_memory_graph_approval_review',
    }.get(action_hint, 'manual_review')
    private_raw_path = ''
    if private_dir is not None:
        private_raw_path = str(private_dir / f"{proposal_id or action.get('proposal_id') or digest_text(content)}.json")
        raw_payload = {
            'proposal_id': proposal_id,
            'line_no': payload.get('_line_no') or action.get('line_no'),
            'route': route,
            'action_hint': action_hint,
            'namespace_scope': namespace,
            'candidate_kind': kind,
            'risk_level': risk,
            'target_store': target_store,
            'target_path': target_path,
            'content': content,
            'evidence_quote': evidence,
            'readback_queries': queries,
            'distillation_prompt': (
                'Distill this raw source material into one concise durable memory only if it states a stable user preference, '
                'system rule, project convention, or self-model fact. Preserve uncertainty. Do not store raw excerpts directly.'
            ),
            'proposed_memory_draft': '',
            'approval_status': 'needs_private_distillation_review',
        }
        p = Path(private_raw_path)
        p.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding='utf-8')
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
    # Do NOT include raw content by default. Store hashes/lengths for dedup and optional private expansion.
    return {
        'draft_id': 'draft_'+digest_text(proposal_id, action_hint, namespace, kind, target_path, content),
        'proposal_id': proposal_id,
        'line_no': payload.get('_line_no') or action.get('line_no'),
        'status': 'draft_open',
        'dry_run': True,
        'writes_memory_graph': False,
        'mutates_review_queue': False,
        'route': route,
        'action_hint': action_hint,
        'target_store': target_store,
        'candidate_kind': kind,
        'risk_level': risk,
        'namespace_scope': namespace,
        'target_path_hint': redact_path_hint(target_path),
        'target_path_present': bool(target_path),
        'content_sha256_16': digest_text(content),
        'evidence_sha256_16': digest_text(evidence),
        'content_length': len(content),
        'evidence_length': len(evidence),
        'readback_queries_redacted': [digest_text(str(q)) for q in queries[:5]],
        'readback_query_count': len(queries),
        'private_raw_path': private_raw_path,
        'private_raw_available': bool(private_raw_path),
        'private_raw_mode': '0600_local_file' if private_raw_path else '',
        'recommended_next_step': {
            'skill_or_procedural_memory_review': 'Review raw candidate privately; if generic reusable workflow, patch/create an appropriate skill and mark proposal consumed with evidence.',
            'private_tool_route_memory_review': 'Review raw candidate privately; if it is a durable credential/tool route, store only the route pointer in private namespace, never the secret.',
            'private_memory_graph_conversion_review': 'Review raw candidate privately; if durable correction/fact, write to owner namespace with readback verification.',
            'private_context_memory_review': 'Review raw candidate privately; if current user context, write to owner namespace and verify future recall.',
            'distill_raw_material_before_memory_graph': 'Distill raw source material into a concise durable memory first; do not approve the raw excerpt directly.',
            'direct_memory_graph_approval_review': 'Use existing approve path only after namespace and readback verification.',
            'manual_review': 'Inspect privately; no safe automatic route inferred.',
        }.get(route, 'Inspect privately; no safe automatic route inferred.'),
    }

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--queue', default=str(DEFAULT_QUEUE))
    ap.add_argument('--action-queue', default='')
    ap.add_argument('--limit', type=int, default=500)
    ap.add_argument('--write-raw-private', action='store_true', help='Unsafe for reports; currently refused unless explicitly implemented later.')
    args=ap.parse_args()
    if args.write_raw_private:
        private_dir = DRAFT_DIR / 'private_raw'
        private_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(private_dir, 0o700)
        except OSError:
            pass
    queue=Path(args.queue)
    aq=Path(args.action_queue) if args.action_queue else latest_action_queue()
    ts=time.strftime('%Y%m%d_%H%M%S')
    DRAFT_DIR.mkdir(parents=True, exist_ok=True); REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report={'timestamp':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'queue':str(queue),'action_queue':str(aq) if aq else None,'counts':{},'findings':[]}
    if not queue.exists():
        report['findings'].append({'severity':'P0','title':'proposal queue missing'})
        drafts=[]
    elif not aq or not aq.exists():
        report['findings'].append({'severity':'P1','title':'action queue missing; run proposal-triage-audit first'})
        drafts=[]
    else:
        rows=load_jsonl(queue)
        action_data=json.loads(aq.read_text(encoding='utf-8'))
        actions={str(a.get('proposal_id')):a for a in action_data.get('actions',[]) if a.get('proposal_id')}
        drafts=[]; skipped=Counter()
        for p in rows:
            if '_parse_error' in p:
                skipped['parse_error']+=1; continue
            if str(p.get('status','pending') or 'pending')!='pending':
                skipped['not_pending']+=1; continue
            pid=str(p.get('proposal_id') or p.get('id') or '')
            a=actions.get(pid)
            if not a:
                skipped['no_action']+=1; continue
            action_hint=str(a.get('action_hint') or '')
            if action_hint not in SAFE_ACTIONS:
                skipped['unsafe_or_manual_action']+=1; continue
            d=draft_from(p,a, private_dir if args.write_raw_private else None)
            drafts.append(d)
            if len(drafts)>=args.limit: break
        by_route=Counter(d['route'] for d in drafts)
        by_risk=Counter(d['risk_level'] or 'unknown' for d in drafts)
        by_ns=Counter(d['namespace_scope'] or 'unknown' for d in drafts)
        private_raw_files=sum(1 for d in drafts if d.get('private_raw_available'))
        report['counts']={'drafts':len(drafts),'private_raw_files':private_raw_files,'skipped':dict(skipped),'by_route':dict(by_route),'by_risk':dict(by_risk),'by_namespace':dict(by_ns)}
        if not drafts:
            report['findings'].append({'severity':'P1','title':'no conversion drafts generated'})
        if by_route.get('manual_review',0):
            report['findings'].append({'severity':'P2','title':'manual review drafts remain','count':by_route['manual_review']})
    out=DRAFT_DIR/f'conversion-drafts-{ts}.json'
    md=REPORT_DIR/f'proposal-consumer-dry-run-{ts}.md'
    out.write_text(json.dumps({'timestamp':report['timestamp'],'dry_run':True,'drafts':drafts}, ensure_ascii=False, indent=2), encoding='utf-8')
    report['draft_file']=str(out)
    lines=['# Proposal Review Consumer Dry-Run','',f"Time: {report['timestamp']}",f"Queue: {report['queue']}",f"Action queue: {report['action_queue']}",f"Draft file: {out}",'','## Counts']
    for k,v in report.get('counts',{}).items(): lines.append(f'- {k}: `{json.dumps(v, ensure_ascii=False)}`')
    lines += ['','## Findings']
    if report['findings']:
        for f in report['findings']: lines.append(f"- [{f.get('severity','P?')}] {f.get('title')} `{json.dumps({k:v for k,v in f.items() if k not in ['severity','title']}, ensure_ascii=False)}`")
    else:
        lines.append('- No P1 findings in dry-run consumer.')
    lines += ['','## Privacy note','','Drafts intentionally contain only metadata, hashes, route hints, redacted readback query hashes, and lengths. They do not include raw candidate/evidence content and do not mutate any memory store.']
    md.write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(md); print(out); print('drafts', len(drafts)); print('findings', len(report['findings']))
    return 0 if not any(f.get('severity')=='P0' for f in report['findings']) else 2
if __name__=='__main__':
    raise SystemExit(main())
