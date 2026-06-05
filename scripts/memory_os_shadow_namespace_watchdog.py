#!/usr/bin/env python3
"""No-agent watchdog for Memory OS shadow namespace leaks.

Alerts only when the selected shadow log window has private/user candidates with
namespace=<empty>. Supports MEMORY_OS_SHADOW_SINCE_ISO to ignore pre-fix residue.
Silent on OK. Redacts content; never modifies data.
"""
import json, re, os
from datetime import datetime
from pathlib import Path

log = Path.home()/'.hermes/logs/shadow_writes'/f'shadow_{datetime.now().strftime("%Y-%m-%d")}.jsonl'
if not log.exists():
    raise SystemExit(0)

since_raw = os.environ.get('MEMORY_OS_SHADOW_SINCE_ISO', '').strip()
since = None
if since_raw:
    try:
        since = datetime.fromisoformat(since_raw.replace('Z', '+00:00'))
    except Exception:
        since = None

private_type = {'user_fact','preference','target_function','procedural_memory','credential_route','exam_context','creative_preference','correction_learning_event'}
examples=[]; count=0; total=0
for line in log.read_text(errors='replace').splitlines():
    try:
        e=json.loads(line)
    except Exception:
        continue
    if since is not None:
        try:
            ts = datetime.fromisoformat(str(e.get('timestamp','')).replace('Z', '+00:00'))
            if ts <= since:
                continue
        except Exception:
            continue
    ns=e.get('namespace','') or ''
    for c in e.get('candidate_writes',[]):
        total += 1
        blob=json.dumps(c, ensure_ascii=False)
        risky=(c.get('memory_type') in private_type or re.search(r'用户档案|偏好|考试|凭据|credential|token|github|claude|家庭|学校', blob, re.I))
        if not ns and risky:
            count += 1
            if len(examples)<5:
                red={k:c.get(k) for k in ['memory_type','target_store','target_path','subject','predicate','requires_review','reason']}
                examples.append(red)
if count:
    print(f'Memory OS shadow namespace watchdog ALERT: {count}/{total} private/user candidate(s) in namespace=<empty> in {log.name}.')
    if since_raw:
        print(f'Window since: {since_raw}')
    for ex in examples:
        print(json.dumps(ex, ensure_ascii=False)[:500])
