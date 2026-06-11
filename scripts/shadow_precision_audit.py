#!/usr/bin/env python3
"""Shadow-write extractor precision audit for Hermes Memory OS.

`memory_write_config.yaml` keeps auto-write off until the extractor "passes an
audited precision/readback suite on real shadow logs". This is that audit:
  (a) proxy metrics that expose extraction garbage WITHOUT labels (raw truncated
      copies, reply-quotes, questions, secrets, urls, generic subjects);
  (b) a sampled export for human labeling, so a TRUE precision can be computed
      via --score.
Proxy ≠ precision. The script never claims a precision it can't defend.

    python3 scripts/shadow_precision_audit.py --days 7 --sample 60 --out ~/.hermes/shadow_audit
    # after labeling to_label.jsonl (set "label": good|bad):
    python3 scripts/shadow_precision_audit.py --score ~/.hermes/shadow_audit/to_label.jsonl
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

SECRET_RE = re.compile(r"sk-[A-Za-z0-9]{8,}|ghp_[A-Za-z0-9]{8,}|github_pat_|xox[baprs]-|AKIA[0-9A-Z]{16}", re.I)
URL_RE = re.compile(r"https?://|www\.|\.com|\.json|/v1/|127\.0\.0\.1|localhost")
REPLY_RE = re.compile(r"\[Replying to:|\[回复|^>|引用")
QUESTION_RE = re.compile(r"[?？]\s*$|^(在吗|怎么|如何|为什么|是不是|能不能|可以吗)")


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", (s or "")).casefold()


def is_truncated_copy(obj: str, user_msg: str) -> bool:
    o, u = _norm(obj), _norm(user_msg)
    if not o or not u:
        return False
    if len(o) >= 20 and len(u) >= len(o) + 15 and u.startswith(o[:60]):
        return True
    return len(o) >= 40 and len(u) >= len(o) + 15 and o in u


def classify(cand: dict, entry: dict) -> list[str]:
    flags = []
    obj = str(cand.get("object") or "")
    user_msg = str(entry.get("user_message") or "")
    if is_truncated_copy(obj, user_msg):
        flags.append("raw_truncated_copy")
    if REPLY_RE.search(obj):
        flags.append("conversational_reply_quote")
    if QUESTION_RE.search(obj.strip()):
        flags.append("is_question")
    if SECRET_RE.search(obj):
        flags.append("contains_secret")
    if URL_RE.search(obj):
        flags.append("contains_url")
    if len(obj.strip()) < 8:
        flags.append("too_short")
    if str(cand.get("subject") or "") in {"auto_store_heuristic", "agent_memory_workflow"}:
        flags.append("generic_subject")
    return flags


def score_labeled(path: str) -> int:
    good = bad = unlabeled = clean_good = clean_bad = 0
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            lab = str(rec.get("label") or "").strip().lower()
            is_clean = not rec.get("flags")
            if lab == "good":
                good += 1; clean_good += int(is_clean)
            elif lab == "bad":
                bad += 1; clean_bad += int(is_clean)
            else:
                unlabeled += 1
    total = good + bad
    prec = good / total if total else 0.0
    clean_total = clean_good + clean_bad
    clean_prec = clean_good / clean_total if clean_total else 0.0
    print("\nLabeled Precision\n" + "=" * 48)
    print(f"labeled        : {total} (good={good} bad={bad}); unlabeled={unlabeled}")
    print(f"overall precision      : {prec:.3f}")
    print(f"clean-subset precision : {clean_prec:.3f}  (the would-be-auto-written set)")
    gate = 0.95
    ok = clean_prec >= gate and clean_total >= 20
    print("-" * 48)
    print(("PASS — safe to consider enabling typed auto-write" if ok
           else f"FAIL — clean-subset precision {clean_prec:.3f} < {gate} (or <20 labeled). Keep auto-write OFF."))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log-dir", default=os.path.expanduser("~/.hermes/logs/shadow_writes"))
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--sample", type=int, default=60)
    ap.add_argument("--out", default=os.path.expanduser("~/.hermes/shadow_audit"))
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--score", default="")
    args = ap.parse_args(argv)

    if args.score:
        return score_labeled(args.score)

    files = sorted(glob.glob(os.path.join(args.log_dir, "shadow_*.jsonl")))
    if args.days > 0:
        today = datetime.now(timezone.utc).date()
        keep = {(today - timedelta(days=d)).strftime("%Y-%m-%d") for d in range(args.days)}
        files = [f for f in files if any(k in os.path.basename(f) for k in keep)]
    if not files:
        print(f"No shadow logs in {args.log_dir} for last {args.days} days.")
        return 2

    n_entries = n_cands = would_write = actually_written = auto_allowed = 0
    target_store = Counter(); mem_type = Counter(); flag_counts = Counter()
    clean_cands = []; flagged_cands = []

    for fp in files:
        with open(fp) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                n_entries += 1
                actually_written += int(bool(entry.get("actually_written")))
                would_write += int(bool(entry.get("would_write")))
                for cand in entry.get("candidate_writes") or []:
                    n_cands += 1
                    target_store[str(cand.get("target_store"))] += 1
                    mem_type[str(cand.get("memory_type"))] += 1
                    auto_allowed += int(bool(cand.get("auto_write_allowed")))
                    flags = classify(cand, entry)
                    for f in flags:
                        flag_counts[f] += 1
                    rec = {"file": os.path.basename(fp), "memory_type": cand.get("memory_type"),
                           "target_store": cand.get("target_store"), "importance": cand.get("importance_score"),
                           "subject": cand.get("subject"), "object": (str(cand.get("object") or ""))[:240],
                           "reason": cand.get("reason"), "flags": flags, "label": ""}
                    (clean_cands if not flags else flagged_cands).append(rec)

    proxy_garbage = len(flagged_cands) / n_cands if n_cands else 0.0
    proxy_clean = len(clean_cands) / n_cands if n_cands else 0.0
    os.makedirs(args.out, exist_ok=True)
    rng = random.Random(args.seed)
    rng.shuffle(clean_cands); rng.shuffle(flagged_cands)
    sample = clean_cands[: max(1, args.sample * 2 // 3)]
    sample += flagged_cands[: args.sample - len(sample)]
    label_path = os.path.join(args.out, "to_label.jsonl")
    with open(label_path, "w") as f:
        for rec in sample:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    with open(os.path.join(args.out, "metrics.json"), "w") as f:
        json.dump({"entries": n_entries, "candidates": n_cands, "actually_written": actually_written,
                   "target_store": dict(target_store), "memory_type": dict(mem_type),
                   "flag_counts": dict(flag_counts), "proxy_garbage_rate": round(proxy_garbage, 4),
                   "proxy_clean_rate": round(proxy_clean, 4)}, f, ensure_ascii=False, indent=2)

    print("\nShadow Extractor Precision Audit\n" + "=" * 64)
    print(f"files: {len(files)} | entries: {n_entries} | candidates: {n_cands}")
    print(f"actually_written: {actually_written}  (expect ~0 = inert loop)")
    print(f"target_store: {dict(target_store)}")
    print("-" * 64)
    for flag, c in flag_counts.most_common():
        print(f"  {flag:28s} {c:5d}  ({c / n_cands * 100:.1f}%)")
    print("-" * 64)
    print(f"PROXY garbage rate: {proxy_garbage*100:.1f}%   PROXY clean rate: {proxy_clean*100:.1f}%")
    print(f"⚠️  PROXY ≠ precision. Label {len(sample)} samples in {label_path}, then --score it.")
    if flag_counts.get("contains_secret"):
        print(f"🚨 {flag_counts['contains_secret']} candidates contain SECRETS — redact at log time.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
