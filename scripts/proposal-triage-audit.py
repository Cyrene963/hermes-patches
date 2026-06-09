#!/usr/bin/env python3
import json, hashlib, os, re, time
from pathlib import Path
from collections import Counter
PROFILE_DIR = Path(os.environ.get('HERMES_PROFILE_DIR') or (Path.home()/'.hermes'))
BASE = Path(os.environ.get('DIGITAL_BRAIN_99_TASK_DIR') or (PROFILE_DIR/'tasks'/'digital-brain-99'))
QUEUE = Path(os.environ.get('MEMORY_REVIEW_QUEUE') or (PROFILE_DIR/'logs'/'memory_review_queue'/'review_proposals.current.jsonl'))
REPORTS=BASE/'reports'; AQ=BASE/'action_queue'
REPORTS.mkdir(parents=True, exist_ok=True); AQ.mkdir(parents=True, exist_ok=True)
now=time.strftime('%Y%m%d_%H%M%S')
report={'timestamp':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'queue':str(QUEUE),'exists':QUEUE.exists(),'counts':{},'buckets':{},'findings':[],'sample_hashes':[]}
actions=[]
if not QUEUE.exists():
    report['findings'].append({'severity':'P0','title':'Review proposal queue file missing','area':'proposal_queue'})
else:
    rows=[]
    for line_no,line in enumerate(QUEUE.read_text(encoding='utf-8', errors='ignore').splitlines(),1):
        if not line.strip(): continue
        try:
            o=json.loads(line); o['_line_no']=line_no; rows.append(o)
        except Exception as e:
            report['findings'].append({'severity':'P1','area':'proposal_queue','title':'Invalid JSONL row','line':line_no,'error':repr(e)})
    pending=[r for r in rows if r.get('status','pending')=='pending']
    report['counts']['total_rows']=len(rows); report['counts']['pending']=len(pending)
    counters={k:Counter() for k in ['target_store','candidate_kind','risk','namespace','source','action_hint']}
    def get(r,path,default=None):
        x=r
        for p in path.split('.'):
            if not isinstance(x,dict): return default
            x=x.get(p,default)
        return x if x is not None else default
    def review_stage(r):
        candidate = r.get('candidate') or {}
        target = (r.get('target_store') or get(r,'decision.target_store') or candidate.get('suggested_store') or candidate.get('target_store') or 'unknown')
        content = str(candidate.get('content') or candidate.get('value') or '')
        evidence = str(candidate.get('evidence_quote') or r.get('evidence_quote') or '')
        queries = candidate.get('readback_queries') or get(r,'readback.queries', []) or []
        if not isinstance(queries, list):
            queries = []
        source = str(r.get('source') or candidate.get('source') or candidate.get('source_type') or '')
        distilled = bool(candidate.get('distilled') or (candidate.get('metadata') or {}).get('distilled'))
        if target == 'memory_graph' and distilled and queries:
            return 'ready_memory'
        if target == 'memory_graph' and content and evidence and content != evidence and queries and source not in {'state_db_message', 'google_ai_studio'}:
            return 'ready_memory'
        return 'raw_material'

    for r in pending:
        candidate=r.get('candidate') or {}
        target=(r.get('target_store') or get(r,'decision.target_store') or candidate.get('suggested_store') or candidate.get('target_store') or 'unknown')
        kind=candidate.get('kind') or r.get('candidate_kind') or 'unknown'
        risk=(r.get('risk') or get(r,'decision.risk_level') or candidate.get('risk_level') or candidate.get('risk') or 'unknown')
        ns=candidate.get('namespace_security_scope') or get(r,'changeset.namespace') or r.get('namespace') or 'unknown'
        source=r.get('source') or candidate.get('source') or 'unknown'
        content=str(candidate.get('content') or candidate.get('value') or candidate.get('evidence_quote') or r.get('content') or '')
        counters['target_store'][target]+=1; counters['candidate_kind'][kind]+=1; counters['risk'][risk]+=1; counters['namespace'][ns]+=1; counters['source'][source]+=1
        stage = review_stage(r)
        counters.setdefault('review_stage', Counter())[stage] += 1
        # Conservative classification. This does NOT write memory; it queues human/agent work.
        target_path = str(candidate.get('target_path') or get(r,'changeset.target_path_uri') or '')
        action='manual_review'
        reason=[]
        low=content.lower()
        target_path_low = target_path.lower()
        if target=='memory_graph':
            if stage == 'ready_memory':
                action='eligible_memory_graph_approval_review'; reason.append('target_store=memory_graph;stage=ready_memory')
            else:
                action='needs_distillation_before_memory_graph'; reason.append('target_store=memory_graph;stage=raw_material')
        elif target=='review':
            if kind in {'noise','temporary','ignore'} or risk in {'low_noise','noise'}:
                action='candidate_reject_noise'; reason.append('noise_or_temporary_kind')
            elif '工具凭据查找规则' in target_path or 'credential' in target_path_low:
                action='needs_private_tool_route_memory_conversion'; reason.append('tool_credential_route_target_path')
            elif '程序性记忆' in target_path or kind in {'procedural_memory'}:
                action='needs_skill_or_procedural_memory_conversion'; reason.append('procedural_memory_target_path')
            elif '纠错' in target_path or any(s in low for s in ['以后','remember','记住','以后要','偏好','不要再','下次','纠错','不是','而是']):
                action='needs_memory_graph_conversion'; reason.append('durable_correction_or_preference_language')
            elif '考试上下文' in target_path:
                action='needs_private_context_memory_conversion'; reason.append('exam_context_target_path')
            elif kind in {'task','decision','user_fact','project_fact','preference','rule','explicit_correction'}:
                action='needs_memory_graph_conversion'; reason.append('durable_kind_but_target_review')
            elif kind in {'lesson','debug_log','evidence'}:
                action='route_to_hindsight_or_lesson_review'; reason.append('evidence_or_lesson_kind')
            else:
                action='manual_review'; reason.append('review_target_unknown_shape')
        else:
            reason.append('unknown_target_store')
        counters['action_hint'][action]+=1
        pid=r.get('proposal_id') or r.get('id') or f'line_{r["_line_no"]}'
        digest=hashlib.sha256((pid+'\n'+content).encode()).hexdigest()[:16]
        item={'proposal_id':pid,'line_no':r['_line_no'],'content_sha256_16':digest,'target_store':target,'candidate_kind':kind,'risk':risk,'namespace_scope':ns,'action_hint':action,'reason':reason,'status':'open'}
        actions.append(item)
    report['buckets']={k:dict(v.most_common()) for k,v in counters.items()}
    report['sample_hashes']=actions[:10]
    consumer_coverage={'latest_draft_file':'','draft_count':0,'covered_by_dry_run':False}
    try:
        draft_files=sorted((BASE/'conversion_drafts').glob('conversion-drafts-*.json'), key=lambda p:p.stat().st_mtime, reverse=True)
        if draft_files:
            consumer_coverage['latest_draft_file']=str(draft_files[0])
            draft_data=json.loads(draft_files[0].read_text(encoding='utf-8'))
            consumer_coverage['draft_count']=len(draft_data.get('drafts',[]))
            consumer_coverage['covered_by_dry_run']=consumer_coverage['draft_count']>=len(pending) and len(pending)>0
    except Exception as e:
        report['findings'].append({'severity':'P1','area':'proposal_queue','title':'Could not inspect consumer coverage','error':repr(e)})
    report['consumer_coverage']=consumer_coverage
    if counters['target_store'].get('review',0) and not consumer_coverage.get('covered_by_dry_run'):
        report['findings'].append({'severity':'P1','area':'proposal_queue','title':'Pending review-target candidates need action consumer','count':counters['target_store']['review'],'consumer_coverage':consumer_coverage})
    if counters['action_hint'].get('manual_review',0)>50:
        report['findings'].append({'severity':'P1','area':'classifier','title':'Too many candidates remain manual_review; triage heuristics need improvement','count':counters['action_hint']['manual_review']})
# write full action queue (metadata only, no raw content)
action_path=AQ/f'proposal-actions-{now}.json'
report_path=REPORTS/f'proposal-triage-{now}.md'
json_path=REPORTS/f'proposal-triage-{now}.json'
action_path.write_text(json.dumps({'timestamp':report['timestamp'],'actions':actions}, ensure_ascii=False, indent=2), encoding='utf-8')
report['action_queue']=str(action_path)
json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
lines=['# Proposal Triage Audit','',f"Time: {report['timestamp']}",f"Queue: {QUEUE}",f"Action queue: {action_path}",'','## Counts']
for k,v in report['counts'].items(): lines.append(f'- {k}: `{v}`')
lines += ['','## Buckets']
for k,v in report['buckets'].items(): lines.append(f'- {k}: `{json.dumps(v, ensure_ascii=False)}`')
lines += ['','## Findings']
if report['findings']:
    for f in report['findings']: lines.append(f"- [{f['severity']}] {f['area']}: {f['title']} `{json.dumps({kk:vv for kk,vv in f.items() if kk not in ['severity','area','title']}, ensure_ascii=False)}`")
else:
    lines.append('- No P1 findings in proposal triage.')
lines += ['','## Privacy note','','This report and action queue intentionally store no raw proposal content; only IDs, line numbers, hashes, metadata buckets, and action hints.']
report_path.write_text('\n'.join(lines)+'\n', encoding='utf-8')
print(report_path)
print(json_path)
print(action_path)
print('findings', len(report['findings']))
