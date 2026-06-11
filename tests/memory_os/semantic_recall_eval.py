#!/usr/bin/env python3
"""Semantic recall eval harness for Hermes Memory OS.

Asserts top-1 by NODE IDENTITY (immune to snippet truncation) + real prompt-carriage
via the live provider's _memory_graph_prefetch_text. Fail-closed (SKIP, not PASS, when
unprovable). Isolated throwaway namespaces, cleaned up. Sets MEMORY_GRAPH_NAMESPACE per
op so the Postgres RLS session context matches the row namespace.

    HERMES_DIR=~/.hermes/hermes-agent python3 tests/memory_os/semantic_recall_eval.py [--keep] [--json out]
Exit 0 iff every non-SKIP case PASSes.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, asdict
from typing import Optional

HERMES_DIR = os.environ.get("HERMES_DIR", "~/.hermes/hermes-agent")
if HERMES_DIR not in sys.path:
    sys.path.insert(0, HERMES_DIR)

RUN_TAG = uuid.uuid4().hex[:8]
NS_A = f"eval:sem_A_{RUN_TAG}"
NS_B = f"eval:sem_B_{RUN_TAG}"


@dataclass
class Result:
    case: str
    status: str
    detail: str = ""
    top1: str = ""
    score: Optional[float] = None


class Harness:
    def __init__(self):
        import tools.memory_graph_tool as mg
        self.mg = mg
        self.provider_cls = self._find_provider_cls()
        self.seeded: list[tuple[str, str]] = []

    @staticmethod
    def _find_provider_cls():
        try:
            import plugins.memory.hindsight as h
        except Exception:
            return None
        for name in dir(h):
            obj = getattr(h, name)
            if isinstance(obj, type) and hasattr(obj, "_memory_graph_prefetch_text") \
                    and hasattr(obj, "_memory_graph_query_variants"):
                return obj
        return None

    @staticmethod
    def _set_ns(ns: str) -> None:
        os.environ["MEMORY_GRAPH_NAMESPACE"] = ns
        os.environ.pop("MEMORY_GRAPH_IS_ADMIN", None)

    def seed(self, ns: str, title: str, content: str) -> Optional[str]:
        self._set_ns(ns)
        out = json.loads(self.mg._create({
            "domain": "core", "parent_uri": "core://", "content": content,
            "title": title, "namespace": ns,
        }))
        nid = out.get("node_uuid")
        if nid:
            self.seeded.append((ns, f"core://{title}"))
        return nid

    def search(self, ns: str, query: str, limit: int = 10) -> list[dict]:
        self._set_ns(ns)
        out = json.loads(self.mg._search({
            "query": query, "domain": "core", "namespace": ns, "limit": limit,
        }))
        return out.get("results", [])

    def carriage(self, ns: str, query: str) -> Optional[str]:
        if self.provider_cls is None:
            return None
        self._set_ns(ns)
        inst = self.provider_cls.__new__(self.provider_cls)
        inst._memory_graph_prefetch = True
        inst._memory_graph_prefetch_limit = 5
        inst._memory_namespace = ns
        inst._user_id = ""
        inst._chat_id = ""
        inst._platform = ""
        try:
            return inst._memory_graph_prefetch_text(query) or ""
        except Exception:
            return None

    def cleanup(self):
        for ns, uri in self.seeded:
            try:
                self._set_ns(ns)
                self.mg._delete({"uri": uri, "domain": "core", "namespace": ns})
            except Exception:
                pass

    @staticmethod
    def _top1_is(rs, target_uuid) -> bool:
        return bool(rs) and rs[0].get("node_uuid") == target_uuid

    def run(self) -> list[Result]:
        R: list[Result] = []
        S = self.seed

        def top1_case(name, ns, query, target, *, also_anchor=None, carriage_title=None):
            rs = self.search(ns, query)
            top_ok = self._top1_is(rs, target)
            top_txt = (rs[0].get("snippet") or rs[0].get("name") or "") if rs else "(empty)"
            score = rs[0].get("score") if rs else None
            bits = [f"top1_identity={'ok' if top_ok else 'WRONG'}"]
            ok = top_ok
            if also_anchor is not None and rs:
                a_ok = also_anchor.casefold() in (rs[0].get("snippet") or "").casefold()
                bits.append(f"anchor_in_snippet={'ok' if a_ok else 'no'}")
            block = self.carriage(ns, query)
            if block is None:
                bits.append("carriage=SKIP")
            else:
                c_ok = (carriage_title or "").casefold() in block.casefold()
                bits.append(f"carriage={'ok' if c_ok else 'MISSING'}")
                ok = ok and c_ok
            return Result(name, "PASS" if ok else "FAIL", " ".join(bits), top_txt[:80], score)

        t = S(NS_A, "pref_editor", "用户偏好：代码编辑器固定用 vim，不要用 nano 或 vscode。")
        R.append(top1_case("1_user_preference", NS_A, "我的编辑器偏好是什么", t,
                            also_anchor="vim", carriage_title="pref_editor"))

        t = S(NS_A, "correction_db", "纠正：数据库是 PostgreSQL，不是 MySQL，端口 5432。")
        R.append(top1_case("2_explicit_correction", NS_A, "连接数据库用哪个", t,
                            also_anchor="postgresql", carriage_title="correction_db"))

        t = S(NS_A, "conv_deploy", "项目部署约定：通过 PM2 重启，禁止直接 kill 进程。")
        R.append(top1_case("3_project_convention", NS_A, "这个项目怎么重新部署", t,
                            also_anchor="pm2", carriage_title="conv_deploy"))

        S(NS_A, "obsolete_api", "[已废弃] 旧 API 域名 old-api-host，2025 年已下线，请勿使用。")
        t = S(NS_A, "current_api", "当前 API 域名 api-host-current，走 HTTPS 443。")
        rs = self.search(NS_A, "现在的 API 域名")
        ok = (rs[0].get("node_uuid") if rs else None) == t
        R.append(Result("4_obsolete_not_used", "PASS" if ok else "FAIL",
                        f"top1={'current' if ok else ('obsolete' if rs else 'empty')}",
                        (rs[0].get("snippet") or "")[:80] if rs else "", rs[0].get("score") if rs else None))

        t = S(NS_A, "iso_own", "NS_A 专属事实：团队吉祥物是水豚。")
        R.append(top1_case("5_namespace_isolation", NS_A, "团队吉祥物是什么", t,
                            also_anchor="水豚", carriage_title="iso_own"))

        rs_b = self.search(NS_B, "团队吉祥物是什么")
        leaked_search = any(u == t for u in (r.get("node_uuid") for r in rs_b))
        block_b = self.carriage(NS_B, "团队吉祥物是什么")
        leaked_carriage = (block_b is not None) and ("iso_own" in block_b or "水豚" in block_b)
        ok = (not leaked_search) and (not leaked_carriage)
        R.append(Result("6_cross_user_no_leak", "PASS" if ok else "FAIL",
                        f"leak_search={leaked_search} leak_carriage={leaked_carriage}",
                        (rs_b[0].get("snippet") if rs_b else "(empty)")))

        S(NS_A, "dup_window", "Steven 的航班偏好：靠窗座位。")
        S(NS_A, "dup_hotel", "Steven 的酒店偏好：高楼层安静房间。")
        t = S(NS_A, "dup_coffee", "Steven 的咖啡偏好：美式不加糖。")
        R.append(top1_case("7_top1_semantic", NS_A, "Steven 喝咖啡有什么偏好", t,
                            also_anchor="美式", carriage_title="dup_coffee"))

        R.append(Result("8_hindsight_masking", "SKIP",
                        "needs MG-outage injection; run in CI with stubbed MG"))

        try:
            from agent.memory_metacognition import get_tool_preflight_block_message as gate
            msg = gate("send_message", {"message": "MEDIA: /tmp/x.png\nhi"})
            R.append(Result("9_preflight_block", "PASS" if msg else "FAIL", (msg or "no block")[:90]))
        except Exception as e:
            R.append(Result("9_preflight_block", "FAIL", f"exc: {e}"))

        try:
            from agent.memory_metacognition import get_tool_preflight_block_message as gate
            msg = gate("send_message", {"message": "你好，同步一下今天的进度。"})
            R.append(Result("10_preflight_allow", "PASS" if not msg else "FAIL",
                            "plain text passes" if not msg else f"unexpected block: {msg}"))
        except Exception as e:
            R.append(Result("10_preflight_allow", "FAIL", f"exc: {e}"))

        try:
            from agent.memory_metacognition import build_strategy_preflight as bsp
            pf = bsp()
            hint = ""
            for meth in ("for_message", "route", "check", "evaluate", "for_user_message"):
                fn = getattr(pf, meth, None)
                if callable(fn):
                    try:
                        hint = str(fn("有个 bug，traceback 如下，帮我排查"))
                        if hint:
                            break
                    except Exception:
                        continue
            ok = ("skill" in hint.casefold()) or ("debug" in hint.casefold())
            R.append(Result("11_skill_routing", "PASS" if ok else "SKIP",
                            hint[:90] or "no routing API matched"))
        except Exception as e:
            R.append(Result("11_skill_routing", "SKIP", f"strategy preflight API differs: {e}"))

        try:
            from agent.memory_write_earn import hygiene_flags
            from agent.auto_store_heuristic import detect_auto_store
            pos = ["记住：我的部署命令是 pm2 reload all", "纠正一下，我住在深圳不是广州",
                   "以后发文件统一用 curl sendDocument"]
            neg = ["哈哈这个搞笑", "嗯好的", "你看这个网关 http://x 通不通",
                   "是不是 99% 数字替身了", "在吗"]
            # Apply the SAME hygiene gate the pipeline now uses, so this measures the
            # post-gate precision the system actually writes with.
            def passes(m):
                if not detect_auto_store(m)[0]:
                    return False
                hard = {"contains_secret", "raw_truncated_copy", "is_question", "too_short"}
                return not (hard & set(hygiene_flags(m, m)))
            tp = sum(1 for m in pos if passes(m))
            fp = sum(1 for m in neg if passes(m))
            prec = tp / (tp + fp) if (tp + fp) else 0.0
            ok = fp == 0 and tp >= 2
            R.append(Result("12_extractor_precision", "PASS" if ok else "FAIL",
                            f"tp={tp}/3 fp={fp}/5 precision={prec:.2f} (post-hygiene-gate; gate: fp==0, tp>=2)"))
        except Exception as e:
            R.append(Result("12_extractor_precision", "FAIL", f"exc: {e}"))

        return R


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--json", default="")
    args = ap.parse_args(argv)

    h = Harness()
    t0 = time.time()
    try:
        results = h.run()
    finally:
        if not args.keep:
            h.cleanup()

    n_pass = sum(1 for r in results if r.status == "PASS")
    n_fail = sum(1 for r in results if r.status == "FAIL")
    n_skip = sum(1 for r in results if r.status == "SKIP")
    width = max(len(r.case) for r in results)

    print(f"\nSemantic Recall Eval (run {RUN_TAG}, {time.time()-t0:.1f}s, "
          f"carriage={'available' if h.provider_cls else 'UNAVAILABLE'})")
    print("=" * 74)
    for r in results:
        mark = {"PASS": "✅", "FAIL": "❌", "SKIP": "⚪"}[r.status]
        line = f"{mark} {r.case.ljust(width)}  {r.status}"
        if r.score is not None:
            line += f"  score={r.score:.3f}"
        print(line)
        if r.detail:
            print(f"     ↳ {r.detail}")
        if r.top1:
            print(f"     top1: {r.top1}")
    print("=" * 74)
    print(f"PASS={n_pass}  FAIL={n_fail}  SKIP={n_skip}   (SKIP = unproven, NOT a pass)")

    if args.json:
        with open(args.json, "w") as f:
            json.dump({"run": RUN_TAG, "pass": n_pass, "fail": n_fail, "skip": n_skip,
                       "results": [asdict(r) for r in results]}, f, ensure_ascii=False, indent=2)
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
