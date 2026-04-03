import asyncio
import types
import unittest
from unittest.mock import patch

from tests import _test_bootstrap  # noqa: F401

from astrbot_plugin_angel_heart.core.thread_window import ThreadWindowBuilder
from astrbot_plugin_angel_heart.roles.front_desk import FrontDesk


class _Config:
    alias = "AngelHeart"


class _Ledger:
    def mark_as_processed(self, chat_id, boundary_ts):
        return None


class _Event:
    def __init__(self):
        self.unified_msg_origin = "napcat:GroupMessage:925351983"
        self.angelheart_event_id = "ah-test-1"
        self._extras = {}
        self.stopped = False

    def get_message_outline(self):
        return "ai查一下最新的macbook air m5多少钱，24g内存的"

    def get_messages(self):
        return []

    def get_sender_id(self):
        return "913855876"

    def get_sender_name(self):
        return "LuckyCai"

    def get_timestamp(self):
        return 123.0

    def get_self_id(self):
        return "10000"

    def set_extra(self, key, value):
        self._extras[key] = value

    def get_extra(self, key, default=None):
        return self._extras.get(key, default)

    def stop_event(self):
        self.stopped = True


class _Req:
    def __init__(self):
        self.contexts = []
        self.prompt = ""
        self.image_urls = []
        self.system_prompt = "system"


class _Queue:
    def __init__(self):
        self.items = []

    def put_nowait(self, item):
        self.items.append(item)


class FrontDeskRewritePromptTests(unittest.IsolatedAsyncioTestCase):
    def _build_front_desk(self):
        queue = _Queue()
        front_desk = FrontDesk.__new__(FrontDesk)
        front_desk._config_manager = _Config()
        front_desk.context = types.SimpleNamespace(
            conversation_ledger=_Ledger(),
            astr_context=types.SimpleNamespace(
                get_using_provider=lambda chat_id: None,
                get_event_queue=lambda: queue,
            ),
            pop_deferred_event=lambda chat_id: None,
        )
        front_desk.astr_context = front_desk.context.astr_context
        front_desk.thread_window_builder = ThreadWindowBuilder(_Config())
        front_desk.secretary = None
        front_desk.filter_images_for_provider = lambda chat_id, contexts: contexts
        return front_desk

    async def test_group_chat_falls_back_to_current_event_when_ledger_is_empty(self):
        front_desk = self._build_front_desk()
        event = _Event()
        req = _Req()

        with patch("astrbot_plugin_angel_heart.roles.front_desk.partition_dialogue_raw", return_value=([], [], 0.0)):
            await front_desk.rewrite_prompt_for_llm(event.unified_msg_origin, event, req)

        self.assertFalse(event.stopped)
        self.assertFalse(event.get_extra("angelheart_blocked_no_context", False))
        self.assertIn("macbook air m5", req.prompt)
        self.assertTrue(req.contexts)


    async def test_resume_deferred_skips_replay_when_recent_context_is_gone(self):
        front_desk = self._build_front_desk()
        event = _Event()
        queue = front_desk.astr_context.get_event_queue()
        event.cleared = False
        event.continued = False
        event.clear_result = lambda: setattr(event, "cleared", True)
        event.continue_event = lambda: setattr(event, "continued", True)
        front_desk.context.pop_deferred_event = lambda chat_id: event

        with patch("astrbot_plugin_angel_heart.roles.front_desk.partition_dialogue_raw", return_value=([], [], 0.0)):
            await front_desk.resume_deferred_if_any(event.unified_msg_origin)

        self.assertEqual(queue.items, [])
        self.assertFalse(event.get_extra("angelheart_replayed", False))
        self.assertFalse(event.cleared)
        self.assertFalse(event.continued)


if __name__ == "__main__":
    unittest.main()
