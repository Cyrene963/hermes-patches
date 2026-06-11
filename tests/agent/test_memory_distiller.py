"""Unit tests for agent.memory_distiller.distill_fact.
Run: pytest tests/agent/test_memory_distiller.py -q
"""
import importlib.util
import os
import sys

_HERE = os.path.dirname(__file__)
_MOD = os.path.normpath(os.path.join(_HERE, "..", "..", "agent", "memory_distiller.py"))
spec = importlib.util.spec_from_file_location("memory_distiller", _MOD)
md = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = md
spec.loader.exec_module(md)
distill = md.distill_fact


def test_strip_leading_remember_colon():
    fact, ok = distill("记住：我的部署命令是 pm2 reload all")
    assert ok and fact == "我的部署命令是 pm2 reload all"


def test_strip_leading_remember_no_colon():
    fact, ok = distill("记住我喜欢用 PostgreSQL")
    assert ok and fact == "我喜欢用 PostgreSQL"


def test_strip_correction_preamble():
    fact, ok = distill("纠正一下，我住在深圳不是广州")
    assert ok and fact == "我住在深圳不是广州"


def test_strip_trailing_politeness():
    fact, ok = distill("记住部署用 pm2 reload all，谢谢")
    assert ok and "谢谢" not in fact and "pm2 reload all" in fact


def test_drop_reply_quote_block():
    fact, ok = distill("[Replying to: 我之前问的那个网关测试结果是什么] 实测结果是网关路由坏了")
    assert ok and "Replying to" not in fact and "实测结果是网关路由坏了" in fact


def test_english_remember():
    fact, ok = distill("Remember I prefer dark mode")
    assert ok and fact.lower() == "i prefer dark mode"


def test_long_ramble_first_sentence_low_confidence():
    ramble = ("我去问了那个网关然后发现路由坏了。" * 8) + "另外顺便说一下今天天气不错。还有别的事。又一句。再一句。"
    fact, ok = distill(ramble)
    # a sprawling multi-sentence ramble should not yield a confident fact
    assert ok is False


def test_clean_fact_passthrough():
    fact, ok = distill("我的数据库端口是 5432")
    assert ok and fact == "我的数据库端口是 5432"


def test_empty_is_not_ok():
    assert distill("   ") == ("", False)


def test_distillation_breaks_raw_truncated_copy_flag():
    # The whole point: after distillation, object is no longer a prefix of source,
    # so the hygiene gate's raw_truncated_copy check stops firing.
    we_spec = importlib.util.spec_from_file_location(
        "memory_write_earn",
        os.path.normpath(os.path.join(_HERE, "..", "..", "agent", "memory_write_earn.py")))
    we = importlib.util.module_from_spec(we_spec)
    sys.modules[we_spec.name] = we
    we_spec.loader.exec_module(we)

    source = "记住：" + ("我的部署流程是先构建再灰度然后全量并通知相关同事逐项确认无误后归档" * 4)
    raw_obj = source[:80]                       # old behaviour: raw slice of a long msg
    assert len(source) > len(raw_obj) + 15      # guard: genuine truncation
    fact, ok = distill(source)                  # new behaviour: distilled (preamble stripped)
    assert "raw_truncated_copy" in we.hygiene_flags(raw_obj, source)
    assert "raw_truncated_copy" not in we.hygiene_flags(fact, source)
