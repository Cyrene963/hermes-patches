#!/usr/bin/env python3
"""Deterministic quality gate for the Digital Stand-in / Memory Graph WebUI loop.

This script is intentionally evidence-first and mostly no-LLM:
- checks Memory Graph + Hindsight service health
- checks mg.bz9.me public surface and standalone WebUI API
- inventories review proposals and shadow writes
- checks proposal approval safety fields
- probes API route availability
- runs focused Memory OS tests when requested
- emits a compact report artifact for continuous improvement

It should be safe for cron: it does not approve/reject/write memories.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
import http.cookiejar
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path.home()
PROFILE_DIR = Path(os.environ.get('HERMES_PROFILE_DIR') or (ROOT / '.hermes'))
TASK_DIR = Path(os.environ.get('DIGITAL_BRAIN_99_TASK_DIR') or (PROFILE_DIR / 'tasks' / 'digital-brain-99'))
REPORT_DIR = TASK_DIR / 'reports'
REVIEW_JSONL = Path(os.environ.get('MEMORY_REVIEW_QUEUE') or (PROFILE_DIR / 'logs' / 'memory_review_queue' / 'review_proposals.current.jsonl'))
SHADOW_DIR = Path(os.environ.get('SHADOW_WRITES_DIR') or (PROFILE_DIR / 'logs' / 'shadow_writes'))
MG_REPO = Path(os.environ.get('MEMORY_GRAPH_REPO') or (ROOT / 'projects' / 'memory-graph'))
HERMES_REPO = Path(os.environ.get('HERMES_REPO') or (PROFILE_DIR / 'hermes-agent'))
AI_STUDIO_INDEX = Path(os.environ.get('AI_STUDIO_INDEX') or (PROFILE_DIR / 'memories' / 'default' / 'aistudio_gemini' / 'conversation_index.jsonl'))


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 60) -> dict:
    try:
        p = subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True, timeout=timeout)
        return {'ok': p.returncode == 0, 'code': p.returncode, 'stdout': p.stdout[-6000:], 'stderr': p.stderr[-3000:]}
    except Exception as e:
        return {'ok': False, 'code': None, 'stdout': '', 'stderr': f'{type(e).__name__}: {e}'}


def fetch(url: str, timeout: int = 10) -> dict:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'digital-brain-99-gate/1.0'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(2_000_000)
            text = body.decode('utf-8', 'replace')
            return {'ok': 200 <= resp.status < 300, 'status': resp.status, 'content_type': resp.headers.get('content-type',''), 'bytes': len(body), 'text': text}
    except urllib.error.HTTPError as e:
        body = e.read(200_000)
        return {'ok': False, 'status': e.code, 'content_type': e.headers.get('content-type',''), 'bytes': len(body), 'text': body.decode('utf-8','replace'), 'error': f'HTTPError: {e.code}'}
    except Exception as e:
        return {'ok': False, 'status': None, 'content_type': '', 'bytes': 0, 'text': '', 'error': f'{type(e).__name__}: {e}'}


def fetch_with_dogfood_session(path: str, timeout: int = 10) -> dict:
    cred_path = TASK_DIR / 'dogfood-login.json'
    if not cred_path.exists():
        return {'ok': False, 'status': None, 'error': f'missing dogfood credentials: {cred_path}', 'text': ''}
    try:
        cred = json.loads(cred_path.read_text())
        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        login_req = urllib.request.Request(
            'http://127.0.0.1:8233/api/auth/login',
            data=json.dumps(cred).encode('utf-8'),
            headers={'Content-Type': 'application/json', 'User-Agent': 'digital-brain-99-gate/1.0'},
        )
        with opener.open(login_req, timeout=timeout) as resp:
            login_text = resp.read(200_000).decode('utf-8','replace')
            login_ok = 200 <= resp.status < 300
        if not login_ok:
            return {'ok': False, 'status': resp.status, 'error': 'dogfood login failed', 'text': login_text}
        req = urllib.request.Request('http://127.0.0.1:8233' + path, headers={'User-Agent': 'digital-brain-99-gate/1.0'})
        with opener.open(req, timeout=timeout) as resp:
            body = resp.read(2_000_000)
            text = body.decode('utf-8','replace')
            return {'ok': 200 <= resp.status < 300, 'status': resp.status, 'content_type': resp.headers.get('content-type',''), 'bytes': len(body), 'text': text}
    except urllib.error.HTTPError as e:
        body = e.read(200_000)
        return {'ok': False, 'status': e.code, 'content_type': e.headers.get('content-type',''), 'bytes': len(body), 'text': body.decode('utf-8','replace'), 'error': f'HTTPError: {e.code}'}
    except Exception as e:
        return {'ok': False, 'status': None, 'error': f'{type(e).__name__}: {e}', 'text': ''}


def load_jsonl(path: Path) -> tuple[list[dict], int]:
    rows, bad = [], 0
    if not path.exists():
        return rows, bad
    for line in path.read_text(errors='replace').splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            bad += 1
    return rows, bad


def _candidate_text_pair(r: dict) -> tuple[str, str]:
    cand = r.get('candidate') or {}
    return (
        str(cand.get('value', cand.get('content', '')) or '').strip(),
        str(r.get('evidence_quote') or cand.get('evidence_quote') or '').strip(),
    )


def _candidate_readback_query_count(r: dict) -> int:
    cand = r.get('candidate') or {}
    queries = r.get('readback_queries') or cand.get('readback_queries') or (r.get('readback') or {}).get('queries') or []
    return len(queries) if isinstance(queries, list) else 0


def review_stage(r: dict) -> str:
    cand = r.get('candidate') or {}
    metadata = cand.get('metadata') or {}
    target = str(metadata.get('target_store') or (r.get('decision') or {}).get('target_store') or cand.get('target_store') or cand.get('suggested_store') or '')
    content, evidence = _candidate_text_pair(r)
    explicitly_distilled = bool(cand.get('distilled') or metadata.get('distilled'))
    has_distinct_evidence = bool(content and evidence and content != evidence)
    has_readback = _candidate_readback_query_count(r) > 0
    source = str(cand.get('source_type') or cand.get('source') or r.get('source') or '')
    if target == 'memory_graph' and explicitly_distilled and has_readback:
        return 'ready_memory'
    if target == 'memory_graph' and has_distinct_evidence and has_readback and source not in {'state_db_message', 'google_ai_studio'}:
        return 'ready_memory'
    return 'raw_material'


def proposal_stats() -> dict:
    rows, bad = load_jsonl(REVIEW_JSONL)
    status = Counter()
    kind = Counter()
    namespace = Counter()
    direct_approvable = 0
    pending_raw_material = 0
    missing_namespace = 0
    explicit_mg = 0
    pending_mg = 0
    pending_non_mg = 0
    stage_counts = Counter()
    for r in rows:
        cand = r.get('candidate') or {}
        decision = r.get('decision') or {}
        changeset = r.get('changeset') or {}
        metadata = cand.get('metadata') or {}
        row_status = str(r.get('status', 'pending') or 'pending')
        k = str(metadata.get('memory_type') or cand.get('kind') or cand.get('type') or '')
        ns = str(r.get('namespace') or cand.get('namespace') or cand.get('namespace_security_scope') or changeset.get('namespace') or '')
        target = str(metadata.get('target_store') or decision.get('target_store') or cand.get('target_store') or cand.get('suggested_store') or '')
        stage = review_stage(r)
        status[row_status] += 1
        kind[k] += 1
        namespace[ns] += 1
        stage_counts[stage] += 1
        if not ns:
            missing_namespace += 1
        if target == 'memory_graph':
            explicit_mg += 1
            if row_status == 'pending':
                pending_mg += 1
        elif row_status == 'pending':
            pending_non_mg += 1
        if row_status == 'pending' and target == 'memory_graph' and ns:
            if stage == 'ready_memory':
                direct_approvable += 1
            else:
                pending_raw_material += 1
    return {
        'exists': REVIEW_JSONL.exists(),
        'path': str(REVIEW_JSONL),
        'rows': len(rows),
        'bad_jsonl': bad,
        'status': dict(status.most_common()),
        'candidate_kind': dict(kind.most_common(12)),
        'namespace_top': dict(namespace.most_common(12)),
        'review_stage': dict(stage_counts.most_common()),
        'missing_namespace': missing_namespace,
        'explicit_memory_graph_target': explicit_mg,
        'pending_memory_graph_target': pending_mg,
        'pending_non_memory_graph_target': pending_non_mg,
        'direct_approvable': direct_approvable,
        'pending_raw_material': pending_raw_material,
    }


def shadow_stats() -> dict:
    files = sorted(SHADOW_DIR.glob('shadow_*.jsonl')) if SHADOW_DIR.exists() else []
    total = 0
    recent = []
    bad_total = 0
    for f in files[-14:]:
        rows, bad = load_jsonl(f)
        total += len(rows)
        bad_total += bad
        recent.append({'file': f.name, 'rows': len(rows), 'bad': bad, 'bytes': f.stat().st_size})
    all_total = 0
    for f in files:
        rows, bad = load_jsonl(f)
        all_total += len(rows)
    return {'dir_exists': SHADOW_DIR.exists(), 'files': len(files), 'total_rows': all_total, 'recent': recent, 'recent_bad_total': bad_total}


def api_checks() -> dict:
    checks = {}
    for name, url in {
        'mg_webui_health': 'http://127.0.0.1:8233/health',
        'mg_embedded_health': 'http://127.0.0.1:8900/health',
        'hindsight_health': 'http://127.0.0.1:9177/health',
        'mg_public_root': 'https://mg.bz9.me/',
        'proposal_inbox_unauth': 'http://127.0.0.1:8233/api/proposal-review/inbox?status=pending&limit=5',
        'review_groups': 'http://127.0.0.1:8233/api/review/groups',
        'namespaces': 'http://127.0.0.1:8233/api/browse/namespaces',
    }.items():
        data = fetch(url)
        checks[name] = {k: v for k, v in data.items() if k != 'text'}
        if data.get('text'):
            checks[name]['sample'] = data['text'][:300]
    dogfood = fetch_with_dogfood_session('/api/proposal-review/inbox?status=pending&limit=20')
    checks['proposal_inbox_dogfood'] = {k: v for k, v in dogfood.items() if k != 'text'}
    if dogfood.get('text'):
        checks['proposal_inbox_dogfood']['sample'] = dogfood['text'][:300]
        try:
            parsed = json.loads(dogfood['text'])
            inbox = parsed.get('inbox') or {}
            namespaces = inbox.get('by_namespace') or {}
            proposals = inbox.get('proposals') or []
            leaked = [p.get('namespace') for p in proposals if str(p.get('namespace','')).startswith('telegram:')]
            checks['proposal_inbox_dogfood']['parsed'] = {
                'user_namespace': parsed.get('user_namespace'),
                'is_admin': parsed.get('is_admin'),
                'filtered_count': inbox.get('filtered_count'),
                'pending_count': inbox.get('pending_count'),
                'by_namespace': namespaces,
                'telegram_namespace_leak_count': len(leaked),
            }
        except Exception as e:
            checks['proposal_inbox_dogfood']['parse_error'] = f'{type(e).__name__}: {e}'
    return checks


def repo_checks() -> dict:
    return {
        'memory_graph_git': run(['git', 'status', '--short'], MG_REPO),
        'memory_graph_head': run(['git', 'log', '-3', '--oneline'], MG_REPO),
        'frontend_files': run(['bash', '-lc', "find frontend/src -maxdepth 4 -type f | sort | sed -n '1,80p'"], MG_REPO),
        'hermes_memory_imports': run(['bash', '-lc', "source venv/bin/activate && python - <<'PY'\nmods=['agent.memory_write_pipeline','agent.memory_review_proposals','agent.memory_semantic_classifier','agent.memory_auto_hooks','tools.memory_graph_tool']\nfor m in mods:\n    __import__(m); print('import_ok', m)\nPY"], HERMES_REPO, timeout=120),
    }


def focused_tests() -> dict:
    if os.environ.get('RUN_FOCUSED_TESTS') != '1':
        return {'skipped': True, 'reason': 'set RUN_FOCUSED_TESTS=1 to run pytest'}
    cmd = ['bash', '-lc', 'source venv/bin/activate && python -m pytest -q tests/agent/test_memory_review_proposals.py tests/agent/test_memory_semantic_classifier.py tests/agent/test_memory_write_wrapper_pollution.py tests/agent/test_memory_write_pipeline_auto_write.py']
    return run(cmd, HERMES_REPO, timeout=600)


def ai_studio_stats() -> dict:
    rows, bad = load_jsonl(AI_STUDIO_INDEX)
    chars = sum(int(r.get('prompt_char_count') or 0) for r in rows)
    return {'exists': AI_STUDIO_INDEX.exists(), 'rows': len(rows), 'bad': bad, 'total_prompt_chars': chars, 'path': str(AI_STUDIO_INDEX)}


def score(report: dict) -> dict:
    gates = []
    def gate(name, ok, weight, note='', status=None):
        if status is None:
            status = 'pass' if ok else 'fail'
        gates.append({'name': name, 'ok': bool(ok), 'weight': weight, 'note': note, 'status': status})
    api = report['api']
    prop = report['proposal_stats']
    shadow = report['shadow_stats']
    repo = report['repo']
    gate('Memory Graph standalone WebUI health', api['mg_webui_health'].get('ok'), 10)
    gate('Memory Graph embedded health', api['mg_embedded_health'].get('ok'), 8)
    gate('Hindsight health', api['hindsight_health'].get('ok'), 8)
    gate('Public mg.bz9.me reachable', api['mg_public_root'].get('ok'), 8)
    dogfood_parsed = api.get('proposal_inbox_dogfood', {}).get('parsed') or {}
    dogfood_no_cross_ns = (
        api.get('proposal_inbox_dogfood', {}).get('ok')
        and dogfood_parsed.get('user_namespace') == 'dogfood:visual-qa'
        and dogfood_parsed.get('is_admin') is False
        and int(dogfood_parsed.get('telegram_namespace_leak_count') or 0) == 0
    )
    gate('Proposal inbox rejects unauthenticated access', api['proposal_inbox_unauth'].get('status') == 401, 5)
    gate('Dogfood proposal inbox is namespace-isolated', dogfood_no_cross_ns, 10, str(dogfood_parsed))
    gate('Review proposals exist', prop['rows'] > 0, 8, f"rows={prop['rows']}")
    gate('Proposal queue has namespaces', prop['missing_namespace'] == 0 and prop['rows'] > 0, 10, f"missing_namespace={prop['missing_namespace']}")
    safe_proposal_routing = prop['direct_approvable'] > 0 or prop.get('pending_raw_material', 0) > 0
    gate('Proposal queue routes ready memories or blocks raw material', safe_proposal_routing, 8, f"ready={prop['direct_approvable']} raw_material={prop.get('pending_raw_material', 0)}")
    gate('Shadow writes active', shadow['total_rows'] > 0, 8, f"total={shadow['total_rows']}")
    gate('Hermes memory modules import', repo['hermes_memory_imports'].get('ok'), 8)
    tests = report['focused_tests']
    if tests.get('skipped'):
        gate('Focused Memory OS tests', None, 12, 'skipped in lightweight watchdog; set RUN_FOCUSED_TESTS=1 for strict gate', status='skipped')
    else:
        gate('Focused Memory OS tests', tests.get('ok'), 12)
    scored_gates = [g for g in gates if g.get('status') != 'skipped']
    earned = sum(g['weight'] for g in scored_gates if g['ok'])
    total = sum(g['weight'] for g in scored_gates)
    return {
        'score_percent': round(earned / total * 100, 1) if total else 0,
        'earned': earned,
        'total': total,
        'scored_total': total,
        'skipped_weight': sum(g['weight'] for g in gates if g.get('status') == 'skipped'),
        'gates': gates,
    }


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report = {
        'generated_at': now_iso(),
        'purpose': 'Continuous 99% digital stand-in / external-brain quality gate for mg.bz9.me and Memory OS',
        'api': api_checks(),
        'proposal_stats': proposal_stats(),
        'shadow_stats': shadow_stats(),
        'ai_studio': ai_studio_stats(),
        'repo': repo_checks(),
        'focused_tests': focused_tests(),
    }
    report['score'] = score(report)
    out = REPORT_DIR / f'quality-gate-{stamp}.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    latest = REPORT_DIR / 'latest.json'
    latest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    # Human-readable markdown summary.
    md = REPORT_DIR / f'quality-gate-{stamp}.md'
    lines = []
    lines.append(f"# Digital Brain 99 Quality Gate — {report['generated_at']}")
    lines.append('')
    lines.append(f"Score: {report['score']['score_percent']}% ({report['score']['earned']}/{report['score']['total']})")
    lines.append('')
    lines.append('## Gates')
    for g in report['score']['gates']:
        label = {'pass': 'PASS', 'fail': 'FAIL', 'skipped': 'SKIP'}.get(g.get('status'), 'PASS' if g['ok'] else 'FAIL')
        lines.append(f"- {label} — {g['name']} ({g['weight']}) {g.get('note','')}")
    lines.append('')
    lines.append('## Proposal queue')
    ps = report['proposal_stats']
    lines.append(f"- rows: {ps['rows']} bad_jsonl: {ps['bad_jsonl']}")
    lines.append(f"- status: {ps['status']}")
    lines.append(f"- candidate_kind: {ps['candidate_kind']}")
    lines.append(f"- namespace_top: {ps['namespace_top']}")
    lines.append(f"- review_stage: {ps.get('review_stage', {})}")
    lines.append(f"- ready_direct_approvable: {ps['direct_approvable']} pending_raw_material: {ps.get('pending_raw_material', 0)} pending_memory_graph_target: {ps['pending_memory_graph_target']} pending_non_memory_graph_target: {ps['pending_non_memory_graph_target']}")
    lines.append('')
    lines.append('## Shadow writes')
    ss = report['shadow_stats']
    lines.append(f"- files: {ss['files']} total_rows: {ss['total_rows']}")
    for r in ss['recent'][-7:]:
        lines.append(f"  - {r['file']}: {r['rows']} rows bad={r['bad']}")
    lines.append('')
    lines.append('## AI Studio archive')
    ai = report['ai_studio']
    lines.append(f"- exists: {ai['exists']} rows: {ai['rows']} total_prompt_chars: {ai['total_prompt_chars']}")
    lines.append('')
    lines.append('## Artifacts')
    lines.append(f"- JSON: {out}")
    lines.append(f"- latest: {latest}")
    md.write_text('\n'.join(lines), encoding='utf-8')
    print(str(md))
    print(f"score={report['score']['score_percent']} proposal_rows={report['proposal_stats']['rows']} shadow_rows={report['shadow_stats']['total_rows']}")
    # Cron should alert only on severe infra failure; do not fail for lightweight skipped tests.
    dogfood_parsed = report['api'].get('proposal_inbox_dogfood', {}).get('parsed') or {}
    dogfood_inbox_ok = (
        report['api'].get('proposal_inbox_dogfood', {}).get('ok')
        and int(dogfood_parsed.get('telegram_namespace_leak_count') or 0) == 0
    )
    severe_fail = (
        not report['api']['mg_webui_health'].get('ok')
        or not report['api']['mg_public_root'].get('ok')
        or report['api']['proposal_inbox_unauth'].get('status') != 401
        or not dogfood_inbox_ok
    )
    return 2 if severe_fail else 0


if __name__ == '__main__':
    raise SystemExit(main())
