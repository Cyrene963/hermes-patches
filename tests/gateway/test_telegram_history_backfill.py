import asyncio
import sys
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from gateway.config import Platform, PlatformConfig, load_gateway_config


def _make_adapter(*, require_mention=True, history_backfill=True, history_backfill_limit=5, bot_username="hermes_bot"):
    from gateway.platforms.telegram import TelegramAdapter

    adapter = object.__new__(TelegramAdapter)
    adapter.platform = Platform.TELEGRAM
    adapter.config = PlatformConfig(
        enabled=True,
        token="***",
        extra={
            "require_mention": require_mention,
            "history_backfill": history_backfill,
            "history_backfill_limit": history_backfill_limit,
            "allowed_topics": [],
            "allowed_chats": [],
        },
    )
    adapter._bot = SimpleNamespace(id=999, username=bot_username)
    adapter._mention_patterns = []
    adapter._dm_topics = {}
    adapter._dm_topic_chat_ids = set()
    adapter._topic_chat_config = []
    adapter._recent_group_context = {}
    return adapter


def _entity(text, mention="@hermes_bot"):
    offset = text.index(mention)
    return [SimpleNamespace(type="mention", offset=offset, length=len(mention))]


def _msg(message_id, text, *, chat_id=-100, thread_id=None, from_name="Alice", is_bot=False, reply_to=None):
    return SimpleNamespace(
        message_id=message_id,
        text=text,
        caption=None,
        photo=None,
        video=None,
        document=None,
        audio=None,
        voice=None,
        sticker=None,
        quote=None,
        reply_to_message=reply_to,
        entities=[],
        caption_entities=[],
        date=datetime(2026, 1, 1, 0, 0, message_id, tzinfo=timezone.utc),
        message_thread_id=thread_id,
        chat=SimpleNamespace(id=chat_id, type="group", title="Test Group"),
        from_user=SimpleNamespace(id=message_id + 1000, full_name=from_name, username=from_name.lower(), is_bot=is_bot),
        sender_chat=None,
    )


def test_reply_chain_backfill_stays_in_same_thread_and_chat():
    adapter = _make_adapter()

    root = _msg(1, "first context")
    second = _msg(2, "second context", reply_to=root)
    trigger = _msg(3, "@hermes_bot help", reply_to=second)
    trigger.entities = _entity(trigger.text)

    assert adapter._should_capture_channel_context(trigger) is False

    text = adapter._fetch_recent_channel_context(trigger)
    assert text.startswith("[Recent replied context]\n")
    assert "[Alice] first context" in text
    assert "[Alice] second context" in text


def test_backfill_ignores_cross_thread_messages():
    adapter = _make_adapter()

    wrong_thread = _msg(1, "other thread", thread_id=99)
    trigger = _msg(2, "@hermes_bot help", thread_id=7, reply_to=wrong_thread)
    trigger.entities = _entity(trigger.text)

    text = adapter._fetch_recent_channel_context(trigger)
    assert text == ""


def test_build_message_event_includes_channel_context_when_enabled():
    adapter = _make_adapter()

    trigger = _msg(3, "@hermes_bot summarize")
    trigger.entities = _entity(trigger.text)

    original_fetch = adapter._build_channel_context_for_trigger

    def fake_build(message):
        assert message is trigger
        return "[Recent replied context]\n[Alice] older note\n[Alice] latest note"

    adapter._build_channel_context_for_trigger = fake_build
    event = adapter._build_message_event(trigger, __import__("gateway.platforms.base", fromlist=["MessageType"]).MessageType.TEXT)
    adapter._build_channel_context_for_trigger = original_fetch

    assert event.channel_context == "[Recent replied context]\n[Alice] older note\n[Alice] latest note"


def test_cache_ignored_visible_group_messages_for_next_trigger():
    adapter = _make_adapter(history_backfill_limit=2)

    ignored_1 = _msg(1, "plain context 1", from_name="Alice")
    ignored_2 = _msg(2, "plain context 2", from_name="Bob")
    trigger = _msg(3, "@hermes_bot summarize", from_name="Carol")
    trigger.entities = _entity(trigger.text)

    assert adapter._should_process_message(ignored_1) is False
    adapter._cache_group_context_message(ignored_1)
    assert adapter._should_process_message(ignored_2) is False
    adapter._cache_group_context_message(ignored_2)

    event = adapter._build_message_event(trigger, __import__("gateway.platforms.base", fromlist=["MessageType"]).MessageType.TEXT)

    assert event.channel_context == "[Recent visible group messages]\n[Alice] plain context 1\n[Bob] plain context 2"


def test_cached_context_stays_scoped_to_thread():
    adapter = _make_adapter(history_backfill_limit=5)

    adapter._cache_group_context_message(_msg(1, "topic A", thread_id=10))
    adapter._cache_group_context_message(_msg(2, "topic B", thread_id=20))
    trigger = _msg(3, "@hermes_bot summarize", thread_id=10)
    trigger.entities = _entity(trigger.text)

    event = adapter._build_message_event(trigger, __import__("gateway.platforms.base", fromlist=["MessageType"]).MessageType.TEXT)

    assert "topic A" in event.channel_context
    assert "topic B" not in event.channel_context


def test_build_message_event_skips_channel_context_when_history_backfill_disabled():
    adapter = _make_adapter(history_backfill=False)
    trigger = _msg(1, "@hermes_bot ping")
    trigger.entities = _entity(trigger.text)

    event = adapter._build_message_event(trigger, __import__("gateway.platforms.base", fromlist=["MessageType"]).MessageType.TEXT)
    assert event.channel_context is None


def test_config_yaml_bridges_telegram_history_backfill_to_platform_extra(tmp_path, monkeypatch):
    hermes_home = tmp_path / "hermes"
    hermes_home.mkdir()
    (hermes_home / "config.yaml").write_text(
        """
telegram:
  enabled: true
  token: test-token
  require_mention: true
  history_backfill: true
  history_backfill_limit: 7
  context_cache_limit: 11
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    for key in [
        "TELEGRAM_REQUIRE_MENTION",
        "TELEGRAM_HISTORY_BACKFILL",
        "TELEGRAM_HISTORY_BACKFILL_LIMIT",
        "TELEGRAM_CONTEXT_CACHE_LIMIT",
    ]:
        monkeypatch.delenv(key, raising=False)

    config = load_gateway_config()
    telegram = config.platforms[Platform.TELEGRAM]

    assert telegram.enabled is True
    assert telegram.extra["require_mention"] is True
    assert telegram.extra["history_backfill"] is True
    assert telegram.extra["history_backfill_limit"] == 7
    assert telegram.extra["context_cache_limit"] == 11


def test_text_handler_caches_visible_ignored_group_message_then_injects_on_trigger():
    """End-to-end adapter flow for privacy-mode-off group messages.

    This simulates Telegram delivering an ordinary group message to the bot
    (which only happens when BotFather privacy mode is disabled). Hermes still
    ignores it because require_mention is enabled, but the adapter keeps it in
    the bounded same-chat/thread context cache. The next explicit @bot trigger
    is enqueued with that context in MessageEvent.channel_context.
    """
    adapter = _make_adapter(history_backfill=True, history_backfill_limit=5)
    adapter._ensure_forum_commands = AsyncMock()
    captured_events = []
    adapter._enqueue_text_event = captured_events.append

    visible_plain = _msg(10, "普通群消息：刚才讨论了A方案", from_name="Alice")
    trigger = _msg(11, "@hermes_bot 总结一下", from_name="Bob")
    trigger.entities = _entity(trigger.text)

    asyncio.run(adapter._handle_text_message(
        SimpleNamespace(effective_message=visible_plain, message=visible_plain, update_id=1001),
        SimpleNamespace(),
    ))
    assert captured_events == []
    assert adapter._fetch_cached_channel_context(trigger) == "[Recent visible group messages]\n[Alice] 普通群消息：刚才讨论了A方案"

    asyncio.run(adapter._handle_text_message(
        SimpleNamespace(effective_message=trigger, message=trigger, update_id=1002),
        SimpleNamespace(),
    ))

    assert len(captured_events) == 1
    event = captured_events[0]
    assert event.text == "总结一下"
    assert event.channel_context == "[Recent visible group messages]\n[Alice] 普通群消息：刚才讨论了A方案"
    adapter._ensure_forum_commands.assert_awaited_once_with(trigger)
